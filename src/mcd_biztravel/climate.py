"""内置城市气候基线 —— 让「动态忌口」在没有天气 API 时也能工作。

设计取舍（诚实设计，不假装知道天气）：
  1. 优先用调用方传入的真实气温（``--temp 31``）；
  2. 没传时，用「城市气候带 + 月份」估算基线温度；
  3. 输出里**明确标注**这是估算值，并提示如何传精确值。

数据为各城市月均最高气温（℃）的近似值，用于判断「今天这杯该不该加冰」，
不用于任何气象用途。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# 城市 -> 12 个月的平均最高气温（1..12 月）
CITY_CLIMATE: Dict[str, List[float]] = {
    # 华北 / 东北
    "北京": [2, 5, 12, 20, 26, 30, 31, 30, 26, 19, 10, 3],
    "天津": [2, 5, 12, 20, 26, 30, 31, 30, 26, 19, 10, 3],
    "石家庄": [3, 6, 13, 21, 27, 32, 32, 31, 27, 20, 11, 4],
    "郑州": [5, 8, 14, 21, 27, 31, 32, 31, 27, 21, 13, 6],
    "西安": [5, 9, 15, 22, 27, 32, 33, 32, 26, 20, 13, 6],
    "青岛": [4, 6, 10, 16, 21, 25, 28, 28, 24, 19, 12, 6],
    "沈阳": [-5, -1, 6, 15, 22, 27, 29, 28, 22, 14, 4, -3],
    "哈尔滨": [-12, -7, 1, 11, 19, 25, 27, 26, 19, 10, -1, -10],
    # 华东
    "上海": [8, 10, 14, 20, 25, 29, 33, 33, 29, 23, 17, 11],
    "苏州": [8, 10, 14, 20, 25, 29, 32, 32, 28, 23, 17, 11],
    "杭州": [8, 10, 15, 21, 26, 29, 33, 33, 29, 23, 17, 11],
    "南京": [7, 9, 14, 20, 26, 29, 32, 32, 28, 22, 16, 10],
    "合肥": [7, 9, 14, 21, 26, 30, 33, 32, 28, 22, 16, 10],
    "济南": [4, 7, 13, 21, 27, 31, 32, 31, 27, 21, 13, 6],
    "厦门": [17, 17, 20, 24, 28, 30, 32, 32, 30, 27, 23, 19],
    "长沙": [8, 10, 15, 21, 26, 30, 34, 34, 29, 23, 17, 11],
    "武汉": [8, 10, 15, 21, 27, 31, 34, 33, 29, 23, 17, 11],
    "南昌": [9, 11, 16, 22, 27, 30, 34, 34, 30, 24, 18, 12],
    # 华南 / 西南
    "广州": [18, 19, 22, 26, 30, 32, 33, 33, 32, 29, 24, 20],
    "深圳": [20, 20, 23, 27, 30, 32, 33, 33, 32, 29, 25, 21],
    "东莞": [19, 20, 23, 27, 30, 32, 33, 33, 32, 29, 25, 21],
    "珠海": [19, 19, 22, 26, 29, 31, 32, 32, 31, 28, 24, 20],
    "海口": [21, 22, 26, 30, 32, 33, 33, 32, 31, 29, 26, 22],
    "南宁": [17, 19, 23, 27, 31, 32, 33, 33, 32, 28, 24, 19],
    "成都": [10, 12, 17, 22, 26, 28, 31, 31, 26, 21, 16, 11],
    "重庆": [10, 12, 18, 23, 27, 30, 34, 34, 29, 22, 17, 11],
    "贵阳": [8, 11, 16, 21, 24, 26, 28, 28, 25, 20, 15, 10],
    "昆明": [16, 18, 22, 24, 25, 25, 25, 25, 24, 21, 18, 15],
    # 西北 / 高原
    "兰州": [2, 6, 13, 20, 25, 29, 30, 29, 24, 17, 9, 3],
    "乌鲁木齐": [-8, -6, 5, 16, 23, 28, 30, 29, 23, 13, 2, -6],
    "拉萨": [8, 10, 14, 17, 21, 24, 23, 22, 21, 18, 13, 9],
    "西宁": [1, 5, 11, 17, 21, 24, 26, 25, 20, 14, 7, 1],
}

# 气候带 —— 决定「冰量基线」的偏移
CLIMATE_BELT: Dict[str, str] = {
    "北京": "north", "天津": "north", "石家庄": "north", "济南": "north",
    "青岛": "north", "郑州": "north", "西安": "north",
    "沈阳": "northeast", "哈尔滨": "northeast",
    "上海": "east", "苏州": "east", "杭州": "east", "南京": "east",
    "合肥": "east", "武汉": "east", "长沙": "east", "南昌": "east",
    "广州": "south", "深圳": "south", "东莞": "south", "珠海": "south",
    "海口": "south", "南宁": "south", "厦门": "south",
    "成都": "southwest", "重庆": "southwest", "贵阳": "southwest", "昆明": "plateau",
    "兰州": "northwest", "乌鲁木齐": "northwest",
    "拉萨": "plateau", "西宁": "plateau",
}

BELT_LABEL = {
    "north": "华北",
    "northeast": "东北",
    "east": "华东",
    "south": "华南",
    "southwest": "西南",
    "northwest": "西北",
    "plateau": "高原凉爽带",
}

# 气候带对冰量的基线修正（档）
BELT_ICE_BIAS = {
    "south": 1,
    "southwest": 0,
    "east": 0,
    "north": -1,
    "northeast": -1,
    "northwest": -1,
    "plateau": -1,
}

DEFAULT_TEMP = 18.0


def normalize_city(city: str) -> str:
    """去掉「市 / 特别行政区」等后缀，便于查表。"""
    if not city:
        return ""
    for suffix in ("特别行政区", "自治区", "地区", "市", "自治州"):
        if city.endswith(suffix):
            return city[: -len(suffix)]
    return city


def belt_of(city: str) -> str:
    return CLIMATE_BELT.get(normalize_city(city), "unknown")


def belt_label(city: str) -> str:
    return BELT_LABEL.get(belt_of(city), "未知气候带")


def baseline_temp(city: str, month: int) -> Tuple[float, str]:
    """返回 (估算气温, 说明)。"""
    key = normalize_city(city)
    months = CITY_CLIMATE.get(key)
    if not months:
        return DEFAULT_TEMP, f"未收录「{city}」，按 {DEFAULT_TEMP:.0f}℃ 保守处理"
    month = max(1, min(12, int(month)))
    return months[month - 1], f"按「{key}」{month} 月气候基线估算"


def resolve_temp(
    city: str, month: int, temp_c: Optional[float] = None
) -> Tuple[float, bool, str]:
    """解析气温：返回 (气温, 是否为估算值, 说明)。"""
    if temp_c is not None:
        return float(temp_c), False, "来自 --temp 实传"
    est, note = baseline_temp(city, month)
    return est, True, note
