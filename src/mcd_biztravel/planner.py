"""预算配餐引擎 —— 按「餐补 + 忌口 + 营养目标」配出 2–3 个方案。

搭配规则直接采用官方在 ``query-meals`` 描述里给出的团餐配餐算法：

  ⩽20 元      小食
  20–30 元     汉堡 + 小食 ／ 汉堡 + 饮料
  30–40 元     汉堡 + 薯条/小食 + 饮料
  40–50 元     汉堡 + 薯条 + 小食 + 饮料
  >50 元       丰富组合，优先不重复小食

在此之上叠加：硬禁忌过滤、冰量偏好、控卡控钠降权。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import preferences as prefs_mod
from .mcp_client import MCDClient, is_ok

_PRICE_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")

BURGER_KW = ("堡", "汉堡", "麦满分", "双吉", "巨无霸", "安格斯", "板烧", "麦辣", "脆鸡腿")
FRIES_KW = ("薯条", "薯")
SNACK_KW = ("鸡块", "鸡翅", "鸡排", "派", "玉米杯", "沙拉", "爆米花", "摇摇")
DRINK_KW = ("可乐", "雪碧", "咖啡", "美式", "拿铁", "卡布", "茶", "果汁", "牛奶", "豆浆", "水", "芬达", "奶昔")
DESSERT_KW = ("冰淇淋", "新地", "麦旋风", "甜筒", "圆筒", "蛋糕")

CAT_BURGER = "汉堡"
CAT_FRIES = "薯条"
CAT_SNACK = "小食"
CAT_DRINK = "饮料"
CAT_DESSERT = "甜品"
CAT_COFFEE = "咖啡"
CAT_OTHER = "其他"

COFFEE_KW = ("咖啡", "美式", "拿铁", "卡布", "摩卡", "浓缩", "澳白")


@dataclass
class MenuItem:
    code: str
    name: str
    price: float
    original_price: float = 0.0
    category: str = CAT_OTHER
    discount_type: str = ""
    tags: List[str] = field(default_factory=list)

    @property
    def discount(self) -> float:
        if self.original_price and self.original_price > self.price:
            return self.original_price - self.price
        return 0.0


@dataclass
class Line:
    item: MenuItem
    quantity: int = 1

    @property
    def subtotal(self) -> float:
        return self.item.price * self.quantity


@dataclass
class Combo:
    label: str
    lines: List[Line]
    reason: str = ""

    @property
    def total(self) -> float:
        return round(sum(line.subtotal for line in self.lines), 2)

    @property
    def items(self) -> List[Dict[str, Any]]:
        return [
            {"productCode": line.item.code, "quantity": line.quantity}
            for line in self.lines
        ]

    def describe(self) -> str:
        return " + ".join(
            (f"{line.item.name}×{line.quantity}" if line.quantity > 1 else line.item.name)
            for line in self.lines
        )


def _to_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    match = _PRICE_RE.search(str(value or ""))
    return float(match.group()) if match else 0.0


def classify(name: str) -> str:
    if any(k in name for k in COFFEE_KW):
        return CAT_COFFEE
    if any(k in name for k in BURGER_KW):
        return CAT_BURGER
    if any(k in name for k in FRIES_KW):
        return CAT_FRIES
    if any(k in name for k in DESSERT_KW):
        return CAT_DESSERT
    if any(k in name for k in DRINK_KW):
        return CAT_DRINK
    if any(k in name for k in SNACK_KW):
        return CAT_SNACK
    return CAT_OTHER


def parse_menu(envelope: Dict[str, Any]) -> List[MenuItem]:
    """把 ``query-meals`` 的返回体解析成菜单列表。"""
    data = envelope.get("data") or {}
    if not isinstance(data, dict):
        return []

    details = data.get("meals") or {}
    items: List[MenuItem] = []
    seen = set()

    for category in data.get("categories") or []:
        cat_name = str(category.get("name") or "")
        for entry in category.get("meals") or []:
            code = str(entry.get("code") or "")
            if not code or code in seen:
                continue
            detail = details.get(code) or {}
            name = str(detail.get("name") or entry.get("name") or code)
            seen.add(code)
            items.append(
                MenuItem(
                    code=code,
                    name=name,
                    price=_to_float(detail.get("currentPrice")),
                    original_price=_to_float(detail.get("originalPrice")),
                    category=classify(name),
                    discount_type=str(detail.get("discountType") or ""),
                    tags=[str(t) for t in (entry.get("tags") or [])],
                )
            )
    return items


def fetch_menu(
    client: MCDClient, store_code: str, order_type: int = 1, be_type: int = 1,
    be_code: Optional[str] = None,
) -> Tuple[List[MenuItem], Dict[str, Any]]:
    args: Dict[str, Any] = {
        "storeCode": store_code,
        "orderType": order_type,
        "beType": be_type,
    }
    if be_code:
        args["beCode"] = be_code
    env = client.call("query-meals", args)
    return parse_menu(env), env


def _cheapest(items: List[MenuItem], category: str, exclude: Optional[set] = None) -> Optional[MenuItem]:
    pool = [i for i in items if i.category == category and (exclude is None or i.code not in exclude)]
    pool = [i for i in pool if i.price > 0]
    return min(pool, key=lambda i: i.price) if pool else None


def _legalize(items: List[MenuItem], res: prefs_mod.Resolved) -> List[MenuItem]:
    """硬禁忌过滤 + 控卡控钠降权（降权 = 价格上浮，排序时自然靠后）。"""
    kept = []
    for item in items:
        if any(bad and bad in item.name for bad in res.hard_avoid):
            continue
        if res.avoid_fried and prefs_mod.name_is_fried(item.name):
            continue
        if res.reduce_sodium and prefs_mod.name_is_high_sodium(item.name):
            continue
        kept.append(item)
    return kept or items


def _pick_drink(items: List[MenuItem], res: prefs_mod.Resolved) -> Optional[MenuItem]:
    pool = [i for i in items if i.category in (CAT_DRINK, CAT_COFFEE) and i.price > 0]
    if not pool:
        return None
    if res.avoid_caffeine:
        non_caffeine = [i for i in pool if not prefs_mod.name_has_caffeine(i.name)]
        if non_caffeine:
            pool = non_caffeine
    hot_kw = ("热", "暖")
    if res.prefer_hot:
        hot = [i for i in pool if any(k in i.name for k in hot_kw)]
        if hot:
            return min(hot, key=lambda i: i.price)
    return min(pool, key=lambda i: i.price)


def plan(menu: List[MenuItem], budget: float, res: prefs_mod.Resolved, limit: int = 3) -> List[Combo]:
    """按官方搭配规则 + 预算，产出候选组合。"""
    legal = _legalize(menu, res)
    combos: List[Combo] = []

    if budget < 20:
        snack = _cheapest(legal, CAT_SNACK) or _cheapest(legal, CAT_OTHER)
        if snack and snack.price <= budget * 1.2:
            combos.append(Combo("轻食", [Line(snack, 1)], "预算 <20 元 → 小食即够"))
        return combos[:limit]

    burger = _cheapest(legal, CAT_BURGER)
    fries = _cheapest(legal, CAT_FRIES)
    snack = _cheapest(legal, CAT_SNACK)
    drink = _pick_drink(legal, res)

    if not burger:
        return combos[:limit]

    def add(label: str, lines: List[Line], reason: str) -> None:
        combo = Combo(label, lines, reason)
        if combo.total <= budget and all(line.item for line in lines):
            combos.append(combo)

    if budget < 30:
        add("A", [Line(burger), Line(snack or burger)], "20–30 元 → 汉堡 + 小食")
        if drink:
            add("B", [Line(burger), Line(drink)], "20–30 元 → 汉堡 + 饮料")
    elif budget < 40:
        if drink:
            add("A", [Line(burger), Line(fries or snack or burger), Line(drink)],
                "30–40 元 → 汉堡 + 薯条/小食 + 饮料")
    elif budget < 50:
        if fries and snack and drink:
            add("A", [Line(burger), Line(fries), Line(snack), Line(drink)],
                "40–50 元 → 汉堡 + 薯条 + 小食 + 饮料")
    else:
        # >50 元：丰富组合，优先不重复小食
        second_snack = None
        used = {snack.code} if snack else set()
        for cand in sorted(legal, key=lambda i: i.price):
            if cand.category == CAT_SNACK and cand.code not in used:
                second_snack = cand
                break
        lines = [Line(burger)]
        if fries:
            lines.append(Line(fries))
        if snack:
            lines.append(Line(snack))
        if second_snack:
            lines.append(Line(second_snack))
        if drink:
            lines.append(Line(drink))
        add("A", lines, ">50 元 → 丰富组合，小食不重复")

    # 兜底：预算内最贵单品组合
    if not combos:
        affordable = [i for i in legal if 0 < i.price <= budget]
        if affordable:
            best = max(affordable, key=lambda i: i.price)
            combos.append(Combo("兜底", [Line(best, 1)], "预算内取最接近上限的单项"))

    # 去重 + 按金额降序
    uniq: Dict[str, Combo] = {}
    for combo in combos:
        uniq.setdefault(combo.describe(), combo)
    return sorted(uniq.values(), key=lambda c: c.total, reverse=True)[:limit]


def price_of(client: MCDClient, store_code: str, combo: Combo,
             order_type: int = 1, be_type: int = 1,
             be_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """调用 ``calculate-price`` 取真实到手价（含优惠）。失败返回 None。"""
    args: Dict[str, Any] = {
        "storeCode": store_code,
        "orderType": order_type,
        "beType": be_type,
        "items": combo.items,
    }
    if be_code:
        args["beCode"] = be_code
    env = client.call("calculate-price", args)
    if not is_ok(env):
        return None
    data = env.get("data")
    return data if isinstance(data, dict) else {"raw": data}


def pick_amount(priced: Optional[Dict[str, Any]]) -> Optional[float]:
    """从 ``calculate-price`` 结果里挑出「实付金额」，单位换算成**元**。

    ⚠️ 实测单位不一致（2026-10-09）：

    * ``query-meals`` 的 ``currentPrice`` 是**元**（字符串，如 ``"21.0"``）；
    * ``calculate-price`` 的 ``price`` / ``productPrice`` 是**分**（整数，如 ``2990``）。

    本函数统一按**分**处理并除以 100，避免出现「算价 ¥1900.00」这种乌龙。
    """
    if not priced:
        return None
    for key in (
        "realTotalAmount", "totalAmount", "payAmount", "actualAmount",
        "price", "productPrice", "totalPrice", "amount",
    ):
        if key in priced:
            value = _to_float(priced[key])
            if value > 0:
                return round(value / 100.0, 2)
    return None
