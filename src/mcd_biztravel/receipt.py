"""报销流水 —— 一句话把一天的账结出来。

数据源：``order-list``（历史餐品订单）+ ``query-order``（单笔详情）。
按「日期 × 城市 × 餐次」归集，与档案里的餐补标准比对，标出超标餐次。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from . import profile as profile_mod
from .mcp_client import MCDClient, is_ok

# 下单时间落在哪个区间 → 算哪一餐
_MEAL_WINDOWS = [
    (5, 10, "breakfast"),
    (10, 14, "lunch"),
    (14, 17, "afternoon"),
    (17, 21, "dinner"),
    (21, 24, "night"),
    (0, 5, "night"),
]


@dataclass
class OrderRecord:
    order_id: str
    create_time: str
    store_name: str
    store_code: str
    status: str
    amount: float
    items: List[str] = field(default_factory=list)

    @property
    def date(self) -> str:
        return (self.create_time or "")[:10]

    @property
    def hour(self) -> int:
        text = (self.create_time or "")[11:13]
        return int(text) if text.isdigit() else 12

    @property
    def meal(self) -> str:
        for start, end, meal in _MEAL_WINDOWS:
            if start <= self.hour < end:
                return meal
        return "lunch"


def _to_float(value: Any) -> float:
    try:
        return float(str(value).replace("¥", "").strip() or 0)
    except ValueError:
        return 0.0


def parse_orders(envelope: Dict[str, Any]) -> List[OrderRecord]:
    data = envelope.get("data") or {}
    rows = data.get("list") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []

    records: List[OrderRecord] = []
    for row in rows:
        products = []
        for item in row.get("orderProductList") or []:
            name = str(item.get("productName") or "")
            qty = item.get("quantity") or 1
            products.append(f"{name}×{qty}" if int(qty) > 1 else name)
        records.append(
            OrderRecord(
                order_id=str(row.get("orderId") or ""),
                create_time=str(row.get("createTime") or ""),
                store_name=str(row.get("storeName") or ""),
                store_code=str(row.get("storeCode") or ""),
                status=str(row.get("orderStatus") or ""),
                amount=_to_float(row.get("realTotalAmount")),
                items=products,
            )
        )
    return records


def fetch_orders(client: MCDClient) -> List[OrderRecord]:
    env = client.call("order-list", {})
    if not is_ok(env):
        return []
    return parse_orders(env)


def filter_date(records: Iterable[OrderRecord], date: Optional[str]) -> List[OrderRecord]:
    if not date:
        return list(records)
    return [r for r in records if r.date == date]


def group_by_meal(records: Iterable[OrderRecord]) -> Dict[str, List[OrderRecord]]:
    grouped: Dict[str, List[OrderRecord]] = {}
    for record in records:
        grouped.setdefault(record.meal, []).append(record)
    return grouped


def render_report(
    records: List[OrderRecord],
    profile: Dict[str, Any],
    date: Optional[str] = None,
) -> str:
    records = sorted(records, key=lambda r: r.create_time)
    if not records:
        return "商旅餐饮流水\n  （没有查到订单）"

    grouped = group_by_meal(records)
    total = round(sum(r.amount for r in records), 2)
    budget = profile_mod.daily_total(profile)

    lines = [f"商旅餐饮流水 · {date or '（全部）'}"]
    lines.append("┌────────┬──────┬──────────────────────┬────────┬────────┐")
    lines.append("│ 时间   │ 餐次 │ 门店 / 内容           │ 金额   │ 餐补   │")
    lines.append("├────────┼──────┼──────────────────────┼────────┼────────┤")
    for record in records:
        meal = profile_mod.MEAL_LABEL.get(record.meal, record.meal)
        summary = f"{record.store_name[:8]} {'、'.join(record.items)[:8]}"
        limited = profile_mod.budget_for(profile, record.meal)
        lines.append(
            f"│ {record.create_time[11:16]:<6} │ {meal:<4} │ {summary:<20} │ "
            f"¥{record.amount:>6.2f} │ ¥{limited:>5.0f} │"
        )
    lines.append("└────────┴──────┴──────────────────────┴────────┴────────┘")

    travel_total = round(sum(r.amount for r in records), 2)
    lines.append("")
    lines.append(f"合计 ¥{travel_total:.2f} / 日餐补标准 ¥{budget:.2f}", )
    if travel_total > budget:
        lines.append(f"⚠️ 超出标准 ¥{travel_total - budget:.2f}，建议备注事由")
    else:
        lines.append(f"未超标 ✅（结余 ¥{budget - travel_total:.2f}）")

    lines.append("")
    lines.append("按餐次小计：")
    for meal in profile_mod.MEALS:
        if meal in grouped:
            amount = round(sum(r.amount for r in grouped[meal]), 2)
            lines.append(
                f"  - {profile_mod.MEAL_LABEL[meal]}：¥{amount:.2f}"
                f"（{len(grouped[meal])} 单）"
            )
    return "\n".join(lines)


def to_csv(records: List[OrderRecord]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["时间", "餐次", "门店", "内容", "金额", "订单号"])
    for record in sorted(records, key=lambda r: r.create_time):
        writer.writerow([
            record.create_time,
            profile_mod.MEAL_LABEL.get(record.meal, record.meal),
            record.store_name,
            "、".join(record.items),
            f"{record.amount:.2f}",
            record.order_id,
        ])
    return buffer.getvalue()
