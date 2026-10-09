"""招待搭配引擎 —— 招待不是「买 N 杯一模一样的」。

规矩来自真实客情场景：

  R1 冷热搭配   按气温定冷热比；**永远至少留 1 杯热饮**
  R2 品类去重   同一 SKU 不超过总数的 60%
  R3 轻重搭配   含餐食时：主食 + 小食 + 蔬菜/玉米杯 各至少一
  R4 备损        ≥4 人时多备 1 份；在场人员忌口冲突则拆组、标注到人
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import planner as pl
from . import preferences as prefs_mod

COLD_KW = ("冰", "冷")
HOT_KW = ("热", "暖")
NO_CAFFEINE_KW = ("茶", "果汁", "牛奶", "豆浆", "水", "雪碧", "芬达")


@dataclass
class Offer:
    item: pl.MenuItem
    quantity: int
    temperature: str = "常温"   # 冰 / 热 / 常温
    note: str = ""

    @property
    def subtotal(self) -> float:
        return round(self.item.price * self.quantity, 2)


@dataclass
class HospitalityPlan:
    people: int
    backups: int
    temp_c: float
    cold_ratio_text: str
    offers: List[Offer] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def cups(self) -> int:
        return sum(o.quantity for o in self.offers)

    @property
    def total(self) -> float:
        return round(sum(o.subtotal for o in self.offers), 2)

    @property
    def items(self) -> List[Dict[str, Any]]:
        return [{"productCode": o.item.code, "quantity": o.quantity} for o in self.offers]

    def temperature_of(self, kw: Tuple[str, ...]) -> int:
        return sum(o.quantity for o in self.offers if o.temperature in kw)


def cold_hot_ratio(temp_c: float) -> Tuple[float, str]:
    """R1：气温 → 冷饮占比。"""
    if temp_c >= 28:
        return 0.6, "≥28℃ → 冷:热 ≈ 3:2"
    if temp_c >= 22:
        return 0.5, "22–28℃ → 冷:热 ≈ 2:2"
    return 0.0, "<22℃ → 全热饮"


def _temperature_of(name: str, default_cold: bool) -> str:
    if any(k in name for k in COLD_KW):
        return "冰"
    if any(k in name for k in HOT_KW):
        return "热"
    return "冰" if default_cold else "常温"


def build_plan(
    menu: List[pl.MenuItem],
    people: int,
    res: prefs_mod.Resolved,
    beverage_budget: float = 0.0,
) -> HospitalityPlan:
    """生成招待配单。"""
    people = max(1, int(people))
    backups = 1 if people >= 4 else 0
    cups = people + backups
    ratio, ratio_text = cold_hot_ratio(res.temp_c)

    plan = HospitalityPlan(
        people=people,
        backups=backups,
        temp_c=res.temp_c,
        cold_ratio_text=ratio_text,
    )

    pool = [
        i
        for i in menu
        if i.category in (pl.CAT_COFFEE, pl.CAT_DRINK) and i.price > 0
    ]
    pool = [
        i for i in pool
        if not any(bad and bad in i.name for bad in res.hard_avoid)
    ]
    if not pool:
        plan.warnings.append("菜单里没有可用饮品，招待方案无法生成")
        return plan

    default_cold = res.temp_c >= 26
    cold_pool = [i for i in pool if _temperature_of(i.name, default_cold) == "冰"]
    hot_pool = [i for i in pool if _temperature_of(i.name, default_cold) == "热"]
    ambient_pool = [i for i in pool if _temperature_of(i.name, default_cold) == "常温"]

    cold_target = int(round(cups * ratio))
    cold_target = min(cold_target, len(cold_pool) * 3)
    hot_target = cups - cold_target

    # 若冷饮不够，把缺口让给热饮
    if ratio > 0 and not cold_pool:
        plan.warnings.append("菜单无冰饮，冷热比按「全热」执行")
        cold_target, hot_target = 0, cups

    # 永远至少 1 杯热饮
    if hot_target < 1 and (hot_pool or ambient_pool):
        hot_target = 1
        cold_target = cups - 1

    # 一、冷饮分配（品类去重）
    if cold_target > 0 and cold_pool:
        plan.offers.extend(_spread(cold_pool, cold_target, "冰", cups))

    # 二、热饮分配
    #     现实约束：菜单里「可乐 / 雪碧 / 红茶」这类 SKU 本身不带冷热，
    #     冷热是靠**特制选项**指定的。所以这里分三种情况处理。
    hot_candidates = hot_pool + ambient_pool
    if hot_target > 0 and not hot_candidates:
        # 菜单没有任何带「热」标识的饮品 → 用同款 SKU 按常温下
        hot_candidates = cold_pool
        hot_label = "常温"
    else:
        hot_label = "热"

    if hot_target > 0 and not hot_pool:
        plan.warnings.append(
            "菜单未返回带「热」标识的饮品 —— 冷热在麦当劳属于**商品特制选项**，"
            f"已按「{hot_label}」下单，请下单时把这几杯改成热饮"
        )

    if hot_target > 0 and hot_candidates:
        # 2.1 先保证至少一杯无咖啡因
        no_caf = [i for i in hot_candidates if not prefs_mod.name_has_caffeine(i.name)]
        if no_caf:
            pick = min(no_caf, key=lambda i: i.price)
            plan.offers.append(Offer(pick, 1, hot_label, "无咖啡因 · 给不喝咖啡的人"))
            hot_target -= 1
        # 2.2 剩余热饮摊开品类
        if hot_target > 0:
            plan.offers.extend(_spread(hot_candidates, hot_target, hot_label, cups))

    # 三、去重检查
    _warn_duplication(plan, cups)

    # 四、预算检查
    if beverage_budget and plan.total > beverage_budget:
        plan.warnings.append(
            f"合计 ¥{plan.total:.2f} 超出招待额度 ¥{beverage_budget:.2f}，"
            "建议减 1 杯或换基础款"
        )
    return plan


def _spread(pool: List[pl.MenuItem], count: int, temperature: str, total_cups: int) -> List[Offer]:
    """在池子里尽量摊开品类，避免「一水儿美式」。"""
    cap = max(1, math.ceil(total_cups * 0.6))
    pool = sorted(pool, key=lambda i: (i.price, i.name))
    offers: List[Offer] = []
    used: Dict[str, int] = {}

    idx = 0
    while count > 0 and pool:
        item = pool[idx % len(pool)]
        if used.get(item.code, 0) < cap:
            if offers and offers[-1].item.code == item.code:
                idx += 1
                if idx > len(pool) * 3:
                    break
                continue
            used[item.code] = used.get(item.code, 0) + 1
            _add(offers, item, temperature)
            count -= 1
        idx += 1
        if idx > len(pool) * 6:
            break
    # 仍有余量就继续堆最便宜的
    while count > 0 and pool:
        _add(offers, pool[0], temperature)
        count -= 1
    return offers


def _add(offers: List[Offer], item: pl.MenuItem, temperature: str) -> None:
    for offer in offers:
        if offer.item.code == item.code and offer.temperature == temperature:
            offer.quantity += 1
            return
    offers.append(Offer(item, 1, temperature))


def _warn_duplication(plan: HospitalityPlan, cups: int) -> None:
    cap = max(1, math.ceil(cups * 0.6))
    for offer in plan.offers:
        if offer.quantity > cap:
            plan.warnings.append(
                f"「{offer.item.name}」占 {offer.quantity}/{cups} 杯，超过同款上限 {cap} 杯"
            )
    if not any(o.temperature == "热" for o in plan.offers):
        plan.warnings.append("没有热饮，长辈/女士可能不适")


def render(plan: HospitalityPlan) -> str:
    lines = [
        f"客户招待 · {plan.people} 人（备损 +{plan.backups}）· 共 {plan.cups} 杯",
        f"场景气温 {plan.temp_c:.0f}℃ → {plan.cold_ratio_text}",
        "",
    ]
    for idx, offer in enumerate(plan.offers, 1):
        note = f"   ← {offer.note}" if offer.note else ""
        lines.append(
            f"  {idx}. {offer.item.name} ×{offer.quantity}  "
            f"¥{offer.subtotal:.2f}{note}"
        )
    cold = plan.temperature_of(("冰",))
    hot = plan.temperature_of(("热",))
    ambient = plan.temperature_of(("常温",))
    lines.append("")
    lines.append(
        f"合计 ¥{plan.total:.2f} · 冷 {cold} / 热 {hot} / 常温 {ambient}"
        f" · 品类 {len({o.item.code for o in plan.offers})} 种"
    )
    lines.append("💼 记账：业务招待费（不占当日差旅餐补）")
    for warning in plan.warnings:
        lines.append(f"⚠️ {warning}")
    return "\n".join(lines)
