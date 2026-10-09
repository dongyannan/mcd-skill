"""动态忌口引擎 —— 忌口不是静态标签，是随「当时当地」变的。

三层结构：

  L1 硬禁忌   过敏原 / 宗教约束 / 明确不吃     → 永不可覆盖，直接过滤
  L2 静态偏好  「我一般去冰」「少糖」          → 可被 L3 覆盖
  L3 动态层    气温 / 气候带 / 时段 / 当日营养  → 优先级最高

深圳那杯会**覆盖**你档案里的「默认去冰」——
默认值服务大多数情况，动态层服务当下这一次。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import climate

# 冰量档位：-2 去冰 / -1 少冰 / 0 常温 / +1 少冰多冰之间 / +2 加冰
ICE_LABELS = {-2: "去冰", -1: "少冰", 0: "常温", 1: "正常冰", 2: "加冰"}
ICE_ORDER = ["去冰", "少冰", "常温", "正常冰", "加冰"]
ICE_TO_LEVEL = {v: k for k, v in ICE_LABELS.items()}

CAFFEINE_KEYWORDS = ("咖啡", "美式", "拿铁", "卡布", "摩卡", "可乐", "红茶", "奶茶", "浓缩")
HIGH_SODIUM_KEYWORDS = ("薯条", "鸡块", "鸡翅", "盐", "培根", "烟肉", "腌")
FRIED_KEYWORDS = ("炸", "薯条", "鸡块", "鸡翅", "鸡排", "派")


@dataclass
class Context:
    """「当时当地」的上下文。"""

    city: str = ""
    month: int = 1
    hour: int = 12
    meal: str = "lunch"  # breakfast / lunch / afternoon / dinner / night
    temp_c: Optional[float] = None
    sodium_today_mg: float = 0.0
    kcal_today: float = 0.0
    kcal_target: float = 0.0
    people: int = 1

    def resolved_temp(self) -> Tuple[float, bool, str]:
        return climate.resolve_temp(self.city, self.month, self.temp_c)


@dataclass
class Resolved:
    """求值结果。"""

    temp_c: float = climate.DEFAULT_TEMP
    temp_is_estimate: bool = True
    temp_note: str = ""
    belt: str = "unknown"
    belt_label: str = "未知气候带"

    ice_level: int = 0
    prefer_hot: bool = False
    avoid_caffeine: bool = False
    avoid_fried: bool = False
    reduce_sodium: bool = False

    hard_avoid: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def ice_text(self) -> str:
        return ICE_LABELS.get(self.ice_level, "常温")

    def summary_lines(self) -> List[str]:
        lines = [
            f"气温 {self.temp_c:.0f}℃（{self.temp_note}）· {self.belt_label}",
            f"冰量 → {self.ice_text}" + ("（优先热饮）" if self.prefer_hot else ""),
        ]
        if self.avoid_caffeine:
            lines.append("咖啡因 → 避免（影响睡眠时段）")
        if self.reduce_sodium or self.avoid_fried:
            lines.append("油炸 / 高钠 → 降权")
        if self.hard_avoid:
            lines.append("硬禁忌 → " + "、".join(self.hard_avoid))
        return lines


def _ice_from_temp(temp_c: float) -> Tuple[int, str]:
    """气温 → 冰量档位（核心规则表的实现）。"""
    if temp_c >= 28:
        return 2, f"气温 {temp_c:.0f}℃ ≥ 28℃ → 加冰"
    if temp_c >= 22:
        return 1, f"气温 {temp_c:.0f}℃ 22–28℃ → 少冰"
    if temp_c >= 15:
        return 0, f"气温 {temp_c:.0f}℃ 15–22℃ → 常温"
    return -2, f"气温 {temp_c:.0f}℃ < 15℃ → 去冰"


def resolve(prefs: Dict[str, Any], ctx: Context) -> Resolved:
    """把「档案里的偏好」+「当时当地」结算成「这一单该怎么做」。"""
    res = Resolved()

    # ---- 基本信息
    temp, is_est, note = ctx.resolved_temp()
    res.temp_c = temp
    res.temp_is_estimate = is_est
    res.temp_note = note
    res.belt = climate.belt_of(ctx.city)
    res.belt_label = climate.belt_label(ctx.city)

    # ---- L1 硬禁忌（永不可覆盖）
    res.hard_avoid = [
        str(x) for x in (prefs.get("hard_avoid") or []) if str(x).strip()
    ]

    # ---- L2 静态偏好作为起点
    static = prefs.get("taste") or {}
    static_ice = static.get("ice", "正常冰")
    level = ICE_TO_LEVEL.get(str(static_ice), 0)
    res.notes.append(f"档案偏好：{static_ice}（L2，可被动态层覆盖）")

    # ---- L3 动态层：气温
    dyn_level, temp_reason = _ice_from_temp(temp)
    res.ice_level = dyn_level
    res.notes.append(f"动态层（气温）：{temp_reason}")
    if dyn_level != level:
        res.notes.append(
            f"⚠️ 动态层覆盖静态偏好：{ICE_LABELS[level]} → {ICE_LABELS[dyn_level]}"
        )

    # ---- L3 动态层：气候带修正（仅在气温处于中间区间时生效，避免双重叠加）
    belt = res.belt
    bias = climate.BELT_ICE_BIAS.get(belt, 0)
    if bias and 15 <= temp < 28 and bias > 0:
        res.ice_level = min(2, res.ice_level + 1)
        res.notes.append(f"动态层（气候带）：{res.belt_label} +1 档冰")
    elif bias < 0 and 15 <= temp < 22:
        res.ice_level = max(-2, res.ice_level - 1)
        res.notes.append(f"动态层（气候带）：{res.belt_label} -1 档冰")

    # ---- L3 动态层：时段
    if ctx.hour >= 21:
        res.avoid_caffeine = True
        if res.ice_level > 0:
            res.ice_level -= 1
        res.notes.append(f"动态层（时段）：{ctx.hour}:00 后 → 去冰 + 避咖啡因")
    if ctx.meal == "breakfast" and temp < 28:
        res.prefer_hot = True
        if res.ice_level > -2:
            res.ice_level -= 1
        res.notes.append("动态层（时段）：早餐时段 → 优先热饮")

    if ctx.hour >= 21 or ctx.meal == "night":
        res.reduce_sodium = True

    # ---- L3 动态层：当日营养反馈
    if ctx.sodium_today_mg and ctx.sodium_today_mg >= 2400:
        res.reduce_sodium = True
        res.avoid_fried = True
        res.notes.append(
            f"动态层（营养）：今日钠已 {ctx.sodium_today_mg:.0f}mg（≥2400）→ 少盐去酱"
        )
    if ctx.kcal_target and ctx.kcal_today >= ctx.kcal_target:
        res.avoid_fried = True
        res.notes.append(
            f"动态层（营养）：热量已达目标（{ctx.kcal_today:.0f}/{ctx.kcal_target:.0f}）"
            " → 推低卡替代"
        )

    if is_est:
        res.notes.append(f"（{note}，如需精确请传 --temp）")

    return res


def filter_names(names: List[str], res: Resolved) -> List[str]:
    """按硬禁忌过滤商品名，返回被排除的名字。"""
    hits = []
    for name in names:
        for bad in res.hard_avoid:
            if bad and bad in name:
                hits.append(name)
                break
    return hits


def name_has_caffeine(name: str) -> bool:
    return any(k in name for k in CAFFEINE_KEYWORDS)


def name_is_fried(name: str) -> bool:
    return any(k in name for k in FRIED_KEYWORDS)


def name_is_high_sodium(name: str) -> bool:
    return any(k in name for k in HIGH_SODIUM_KEYWORDS)
