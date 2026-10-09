"""动态忌口引擎的回归测试 —— 「北京不加冰、深圳加冰」必须成立。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcd_biztravel import preferences as P  # noqa: E402


def _profile(ice: str = "正常冰", hard=None):
    return {
        "hard_avoid": hard or [],
        "taste": {"ice": ice},
    }


def test_beijing_winter_overrides_static_preference():
    """档案写「加冰」，10 月北京 12℃ 的动态层必须把它压成去冰。"""
    ctx = P.Context(city="北京", month=10, hour=8, meal="breakfast", temp_c=12)
    res = P.resolve(_profile("加冰"), ctx)
    assert res.ice_level <= -1, res.ice_level
    assert res.prefer_hot is True


def test_shenzhen_hot_day_turns_on_ice():
    """档案写「去冰」，深圳 32℃ 的动态层必须把它抬到加冰。"""
    ctx = P.Context(city="深圳", month=10, hour=15, meal="afternoon", temp_c=32)
    res = P.resolve(_profile("去冰"), ctx)
    assert res.ice_level == 2, res.ice_level


def test_same_rule_two_cities_two_answers():
    """同一条规则、同一份档案，两个城市出两个结果。"""
    prof = _profile("常温")
    beijing = P.resolve(prof, P.Context(city="北京", month=1, hour=12, temp_c=2))
    shenzhen = P.resolve(prof, P.Context(city="深圳", month=7, hour=12, temp_c=33))
    assert beijing.ice_level < shenzhen.ice_level


def test_climate_baseline_used_without_temp():
    """不传气温时用城市气候基线兜底，并标注是估算值。"""
    res = P.resolve(_profile(), P.Context(city="广州", month=7, hour=14))
    assert res.temp_is_estimate is True
    assert res.temp_c >= 30
    assert "估算" in res.temp_note


def test_hard_avoid_never_overridden():
    ctx = P.Context(city="深圳", month=7, hour=14, temp_c=33)
    res = P.resolve(_profile(hard=["花生", "香菜"]), ctx)
    assert res.hard_avoid == ["花生", "香菜"]
    assert P.filter_names(["花生麦旋风", "原味鸡块"], res) == ["花生麦旋风"]


def test_late_night_blocks_caffeine_and_drops_ice():
    ctx = P.Context(city="深圳", month=7, hour=22, meal="night", temp_c=33)
    res = P.resolve(_profile("正常冰"), ctx)
    assert res.avoid_caffeine is True
    assert res.ice_level < 2


def test_sodium_feedback_pushes_away_fried_food():
    ctx = P.Context(city="上海", month=10, hour=19, meal="dinner",
                    temp_c=20, sodium_today_mg=3100)
    res = P.resolve(_profile(), ctx)
    assert res.reduce_sodium is True
    assert res.avoid_fried is True
    assert P.name_is_fried("中薯条") is True
