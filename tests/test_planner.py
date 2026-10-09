"""配餐引擎 + 护栏 的回归测试。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcd_biztravel import guardrails as G  # noqa: E402
from mcd_biztravel import planner as PL  # noqa: E402
from mcd_biztravel import preferences as P  # noqa: E402


def _menu():
    return [
        PL.MenuItem("B1", "板烧鸡腿堡", 21.0, category=PL.CAT_BURGER),
        PL.MenuItem("B2", "双层吉士汉堡", 17.0, category=PL.CAT_BURGER),
        PL.MenuItem("F1", "中薯条", 11.0, category=PL.CAT_FRIES),
        PL.MenuItem("S1", "玉米杯", 9.0, category=PL.CAT_SNACK),
        PL.MenuItem("S2", "麦乐鸡 5 块", 12.0, category=PL.CAT_SNACK),
        PL.MenuItem("D1", "无糖可乐", 9.0, category=PL.CAT_DRINK),
        PL.MenuItem("D2", "鲜煮咖啡", 10.0, category=PL.CAT_COFFEE),
    ]


def _res():
    return P.resolve({"hard_avoid": [], "taste": {"ice": "常温"}},
                     P.Context(city="上海", month=10, hour=12, temp_c=20))


def test_budget_band_20_to_30_gives_burger_plus_snack():
    combos = PL.plan(_menu(), 28.0, _res())
    assert combos
    assert all(c.total <= 28.0 for c in combos)
    assert any(any(l.item.category == PL.CAT_BURGER for l in c.lines) for c in combos)


def test_budget_band_over_50_is_rich_combo():
    combos = PL.plan(_menu(), 60.0, _res())
    assert combos
    top = combos[0]
    cats = {l.item.category for l in top.lines}
    assert PL.CAT_BURGER in cats


def test_no_combo_exceeds_budget():
    for budget in (18, 28, 36, 46, 60):
        for combo in PL.plan(_menu(), float(budget), _res()):
            assert combo.total <= budget, (budget, combo.describe(), combo.total)


def test_caffeine_avoided_at_night():
    res = P.resolve({"hard_avoid": [], "taste": {"ice": "常温"}},
                    P.Context(city="上海", month=10, hour=22, meal="night", temp_c=20))
    combos = PL.plan(_menu(), 30.0, res)
    for combo in combos:
        for line in combo.lines:
            if line.item.category in (PL.CAT_DRINK, PL.CAT_COFFEE):
                assert not P.name_has_caffeine(line.item.name), line.item.name


def test_parse_menu_from_envelope():
    envelope = {
        "data": {
            "categories": [
                {"name": "汉堡", "meals": [{"code": "B1", "tags": []}]},
                {"name": "饮料", "meals": [{"code": "D1", "tags": []}]},
            ],
            "meals": {
                "B1": {"name": "板烧鸡腿堡", "currentPrice": "21.0", "originalPrice": "23.0"},
                "D1": {"name": "无糖可乐", "currentPrice": "9.0"},
            },
        }
    }
    items = PL.parse_menu(envelope)
    assert [i.name for i in items] == ["板烧鸡腿堡", "无糖可乐"]
    assert items[0].price == 21.0 and items[0].category == PL.CAT_BURGER


def test_guardrails_block_write_without_yes():
    assert G.is_write_tool("create-order") is True
    assert G.is_write_tool("query-meals") is False
    assert G.confirm("create-order", {"x": 1}, assume_yes=False, echo=lambda _: None) is False
    assert G.confirm("create-order", {"x": 1}, assume_yes=True, echo=lambda _: None) is True


def test_guardrails_mask_sensitive_text():
    text = "联系人 13812345678 地址 北京市通州区京东总部 订单 1030491750000795047679896644"
    masked = G.mask_text(text)
    assert "13812345678" not in masked
    assert "138****5678" in masked
    assert "1030491750000795047679896644" not in masked
