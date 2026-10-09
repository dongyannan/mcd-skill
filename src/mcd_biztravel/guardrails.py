"""护栏 —— 默认只读；写操作先「讲清楚要发生什么」，用户点头才执行。

麦当劳官方工具描述里已经把这条写死了（例如 ``draw-lottery``：
"必须先展示消耗并得到用户确认"）。这个模块把它变成代码里的硬约束。

同时负责输出打码：手机号、详细门牌、订单号中间段。
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------- 写操作清单

# 会真实改动账号状态的工具；调用前必须过 confirm()
WRITE_TOOLS = {
    "create-order": "创建订单（真实下单，会产生费用）",
    "cancel-order": "取消订单（真实取消，可能影响已支付订单）",
    "auto-bind-coupons": "一键领取全部可领券（会改动券包）",
    "draw-lottery": "执行抽奖（消耗抽奖机会 / 积分）",
    "mall-create-order": "积分商城兑换下单（消耗积分）",
    "party-order-create": "主题派对预订下单（包场 / 拼团）",
    "delivery-create-address": "新建配送地址（写入账号地址簿）",
}


class GuardrailError(RuntimeError):
    """未确认的写操作被拦截。"""


def is_write_tool(name: str) -> bool:
    return name in WRITE_TOOLS


def describe_write(name: str) -> str:
    return WRITE_TOOLS.get(name, "未知写操作")


def confirm(
    name: str,
    args: Dict[str, Any],
    *,
    assume_yes: bool = False,
    echo: Optional[Callable[[str], None]] = None,
) -> bool:
    """写操作闸门。

    ``assume_yes=False``（默认）时**不执行**，只打印「将要发生什么」并返回 False。
    调用方拿到 False 就应该停止，把这段话交给用户确认。
    """
    say = echo or print
    if not is_write_tool(name):
        return True

    say("")
    say("┌─ 写操作确认 ──────────────────────────────")
    say(f"│ 工具：{name}")
    say(f"│ 说明：{describe_write(name)}")
    if args:
        say(f"│ 参数：{_safe_args(args)}")
    say("└──────────────────────────────────────────")
    if assume_yes:
        say("⚠️ 已按 --yes 直接执行（本次调用会真实改动账号）")
        return True
    say("已拦截：未加 --yes，本次不执行。确认无误后请加 --yes 重跑。")
    return False


def _safe_args(args: Dict[str, Any]) -> str:
    masked = {k: (mask_text(str(v)) if isinstance(v, str) else v) for k, v in args.items()}
    text = str(masked)
    return text if len(text) <= 300 else text[:300] + "…"


# ------------------------------------------------------------------ 打码

_PHONE = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")
_ID_CARD = re.compile(r"(?<!\d)(\d{6})(\d{8})(\d{3}[\dXx])(?!\d)")
_ORDER = re.compile(r"(?<!\d)(\d{6})\d{14,}(\d{4})(?!\d)")


def mask_phone(text: str) -> str:
    return _PHONE.sub(lambda m: f"{m.group(1)}****{m.group(3)}", text)


def mask_id_card(text: str) -> str:
    return _ID_CARD.sub(lambda m: f"{m.group(1)}********{m.group(3)}", text)


def mask_order(text: str) -> str:
    return _ORDER.sub(lambda m: f"{m.group(1)}…{m.group(2)}", text)


def mask_text(text: str) -> str:
    """统一打码入口。"""
    if not text:
        return text
    return mask_order(mask_id_card(mask_phone(text)))


def mask_dict(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: mask_dict(v) for k, v in data.items()}
    if isinstance(data, list):
        return [mask_dict(v) for v in data]
    if isinstance(data, str):
        return mask_text(data)
    return data


def audit_tools(tools: List[str]) -> Tuple[List[str], List[str]]:
    """把工具名清单分成（只读, 写操作）两栏。"""
    readonly, writable = [], []
    for name in tools:
        (writable if is_write_tool(name) else readonly).append(name)
    return readonly, writable
