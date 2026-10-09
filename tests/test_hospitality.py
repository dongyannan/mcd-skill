"""招待搭配引擎的回归测试 —— 冷热搭配、品类去重、备损、无咖啡因。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcd_biztravel import hospitality as H  # noqa: E402
from mcd_biztravel import planner as PL  # noqa: E402
from mcd_biztravel import preferences as P  # noqa: E402


def _menu():
    return [
        PL.MenuItem("C1", "冰美式", 9.5, category=PL.CAT_COFFEE),
        PL.MenuItem("C2", "冰拿铁", 12.0, category=PL.CAT_COFFEE),
        PL.MenuItem("C3", "热拿铁", 12.0, category=PL.CAT_COFFEE),
        PL.MenuItem("C4", "热卡布奇诺", 12.0, category=PL.CAT_COFFEE),
        PL.MenuItem("C5", "热红茶", 8.0, category=PL.CAT_DRINK),
        PL.MenuItem("C6", "鲜榨橙汁", 10.0, category=PL.CAT_DRINK),
    ]


def _res(city, temp, hour=15):
    return P.resolve({"hard_avoid": [], "taste": {"ice": "常温"}},
                     P.Context(city=city, month=7, hour=hour, temp_c=temp))


def test_hot_day_orders_mostly_cold():
    plan = H.build_plan(_menu(), people=3, res=_res("深圳", 31))
    assert plan.temperature_of(("冰",)) >= plan.temperature_of(("热",))


def test_cold_day_orders_mostly_hot():
    plan = H.build_plan(_menu(), people=3, res=_res("北京", 12))
    assert plan.temperature_of(("热",)) >= plan.temperature_of(("冰",))
    assert plan.cups == 3


def test_always_at_least_one_hot_drink():
    plan = H.build_plan(_menu(), people=6, res=_res("深圳", 33))
    assert plan.temperature_of(("热",)) >= 1


def test_backup_cup_for_groups_of_four_or_more():
    assert H.build_plan(_menu(), 3, _res("上海", 25)).backups == 0
    plan4 = H.build_plan(_menu(), 4, _res("上海", 25))
    assert plan4.backups == 1
    assert plan4.cups == 5


def test_no_single_sku_exceeds_60_percent():
    plan = H.build_plan(_menu(), people=5, res=_res("深圳", 30))
    cups = plan.cups
    for offer in plan.offers:
        assert offer.quantity <= max(1, -(-cups * 6 // 10)), offer


def test_hard_avoid_filters_menu():
    res = P.resolve({"hard_avoid": ["红茶"], "taste": {"ice": "常温"}},
                    P.Context(city="上海", month=10, hour=15, temp_c=19))
    plan = H.build_plan(_menu(), people=2, res=res)
    assert all("红茶" not in o.item.name for o in plan.offers)


def test_ratio_table():
    assert H.cold_hot_ratio(30)[0] > H.cold_hot_ratio(25)[0] > H.cold_hot_ratio(10)[0]
