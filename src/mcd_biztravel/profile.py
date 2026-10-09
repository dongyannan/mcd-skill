"""差旅档案 —— 一次配置，整趟出差都省心。

档案存在 ``~/.mcd_biztravel/profile.json``，**不进仓库、不进 vault**。
里面是「餐补标准」和「口味偏好」，不含任何账号凭证。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

PROFILE_DIR = os.path.join(os.path.expanduser("~"), ".mcd_biztravel")
PROFILE_PATH = os.path.join(PROFILE_DIR, "profile.json")

DEFAULT_PROFILE: Dict[str, Any] = {
    "name": "",
    "home_city": "北京",
    "hotel_address": "",
    "daily_budget": {
        "breakfast": 20,
        "lunch": 60,
        "afternoon": 40,
        "dinner": 80,
        "night": 30,
    },
    "business_entertain_budget": 120,
    "hard_avoid": ["香菜"],
    "taste": {
        "ice": "正常冰",
        "sugar": "少糖",
        "prefer": [],
    },
    "kcal_target": 2000,
    "dynamic_enabled": True,
    "temp_override": None,
}

MEALS: List[str] = ["breakfast", "lunch", "afternoon", "dinner", "night"]

MEAL_LABEL = {
    "breakfast": "早餐",
    "lunch": "午餐",
    "afternoon": "下午茶",
    "dinner": "晚餐",
    "night": "夜宵",
}


def load(path: str = PROFILE_PATH) -> Dict[str, Any]:
    """读取档案；不存在时返回默认档案（不落盘）。"""
    data: Dict[str, Any] = json.loads(json.dumps(DEFAULT_PROFILE))
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                user = json.load(fh)
            if isinstance(user, dict):
                _deep_update(data, user)
        except (OSError, ValueError):
            pass
    return data


def save(profile: Dict[str, Any], path: str = PROFILE_PATH) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, ensure_ascii=False, indent=2)
    return path


def _deep_update(base: Dict[str, Any], extra: Dict[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def budget_for(profile: Dict[str, Any], meal: str) -> float:
    """取某餐的餐补额度。"""
    budgets = profile.get("daily_budget") or {}
    return float(budgets.get(meal, 0) or 0)


def daily_total(profile: Dict[str, Any]) -> float:
    return sum(float(v or 0) for v in (profile.get("daily_budget") or {}).values())


def render(profile: Dict[str, Any]) -> str:
    budgets = profile.get("daily_budget") or {}
    lines = [
        "差旅档案",
        f"  姓名      {profile.get('name') or '（未填）'}",
        f"  常驻城市  {profile.get('home_city') or '（未填）'}",
        f"  酒店地址  {profile.get('hotel_address') or '（未填）'}",
        f"  日餐补    ¥{daily_total(profile):.2f}",
    ]
    for meal in MEALS:
        lines.append(f"    - {MEAL_LABEL[meal]:<4} ¥{float(budgets.get(meal, 0) or 0):.2f}")
    lines.append(f"  招待额度  ¥{float(profile.get('business_entertain_budget', 0) or 0):.2f}")
    lines.append(f"  硬禁忌    {'、'.join(profile.get('hard_avoid') or []) or '（无）'}")
    taste = profile.get("taste") or {}
    lines.append(
        f"  口味偏好  冰={taste.get('ice', '未设')} 糖={taste.get('sugar', '未设')}"
    )
    lines.append(f"  热量目标  {profile.get('kcal_target', 0)} kcal/日")
    return "\n".join(lines)
