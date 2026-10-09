"""命令行入口 —— 麦麦商旅美食专家。

    mcd-biztravel doctor                     连通性自检
    mcd-biztravel prefs  --city 深圳 --temp 32       看动态忌口怎么结算
    mcd-biztravel plan   --city 上海 --meal lunch --budget 60
    mcd-biztravel hospital --city 深圳 --people 4 --temp 32
    mcd-biztravel report --date today
    mcd-biztravel profile show

所有命令**默认只读**；涉及写操作的命令必须显式加 ``--yes``。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from typing import Any, Dict, List, Optional

from . import guardrails, hospitality, planner, preferences, profile as profile_mod, receipt, stores
from .climate import belt_label, normalize_city
from .mcp_client import MCDClient, MCPError

OK = "✅"
WARN = "⚠️"


def _client() -> MCDClient:
    return MCDClient()


def _today() -> str:
    return _dt.date.today().isoformat()


def _now_hour() -> int:
    return _dt.datetime.now().hour


def _month() -> int:
    return _dt.datetime.now().month


def _ctx_from_args(args: argparse.Namespace) -> preferences.Context:
    return preferences.Context(
        city=args.city or "",
        month=args.month or _month(),
        hour=args.hour if args.hour is not None else _now_hour(),
        meal=args.meal or "lunch",
        temp_c=args.temp,
        sodium_today_mg=getattr(args, "sodium", 0) or 0,
        kcal_today=getattr(args, "kcal", 0) or 0,
        kcal_target=getattr(args, "kcal_target", 0) or 0,
        people=getattr(args, "people", 1) or 1,
    )


# --------------------------------------------------------------------- doctor


def cmd_doctor(args: argparse.Namespace) -> int:
    client = _client()
    print("麦麦商旅美食专家 · 连通性自检")
    print("─" * 46)

    info = client.initialize()
    server = info.get("serverInfo") or {}
    print(f"{OK} 协议握手    {server.get('name', '?')} v{server.get('version', '?')}")

    names = client.tool_names()
    readonly, writable = guardrails.audit_tools(names)
    print(f"{OK} 工具清单    {len(names)} 个（只读 {len(readonly)} / 写操作 {len(writable)}）")
    print(f"   {WARN} 写操作：{'、'.join(writable)}")

    time_env = client.call("now-time-info")
    stamp = ((time_env.get("data") or {}).get("formatted")) or "?"
    print(f"{OK} 服务端时间  {stamp}")

    fav = stores.list_favorite_stores(client)
    print(f"{OK} 收藏门店    {len(fav)} 家")
    for store in fav[:5]:
        print(f"   · {store.get('storeName')}（storeCode={store.get('storeCode')}）")

    addresses = stores.list_addresses(client)
    print(f"{OK} 外送地址    {len(addresses)} 个")
    for addr in addresses[:3]:
        print(f"   · {guardrails.mask_text(str(addr.get('fullAddress', '')))}")

    accounts = client.call("query-my-account")
    points = ((accounts.get("data") or {}).get("availablePoint")) if isinstance(accounts.get("data"), dict) else None
    print(f"{OK} 积分账户    可用积分 {points}")

    print("─" * 46)
    print("全部通过。可以开始用了。")
    return 0


# ---------------------------------------------------------------------- prefs


def cmd_prefs(args: argparse.Namespace) -> int:
    prof = profile_mod.load()
    ctx = _ctx_from_args(args)
    res = preferences.resolve(prof, ctx)

    print("动态忌口结算")
    print("─" * 46)
    print(f"场景：{ctx.city or '（未指定城市）'} · {ctx.month} 月 · {ctx.hour}:00 · "
          f"餐次 {profile_mod.MEAL_LABEL.get(ctx.meal, ctx.meal)}")
    for line in res.summary_lines():
        print(f"  {line}")
    print()
    print("推导过程：")
    for note in res.notes:
        print(f"  - {note}")
    return 0


# ----------------------------------------------------------------------- plan


def cmd_plan(args: argparse.Namespace) -> int:
    client = _client()
    prof = profile_mod.load()
    ctx = _ctx_from_args(args)
    res = preferences.resolve(prof, ctx)

    budget = args.budget if args.budget is not None else profile_mod.budget_for(prof, ctx.meal)

    print(f"配餐方案 · {profile_mod.MEAL_LABEL.get(ctx.meal, ctx.meal)} · "
          f"{ctx.city or '（未指定城市）'}")
    print("─" * 58)
    for line in res.summary_lines():
        print(f"  {line}")
    print(f"  本餐额度 ¥{budget:.2f}")
    print()

    store = None
    if args.store_code:
        store = {"storeCode": args.store_code, "storeName": args.store_name or "指定门店",
                 "beCode": args.be_code or "", "address": ""}
    else:
        store = stores.pick_store(client, city=normalize_city(ctx.city), keyword=args.keyword or "")
    if not store:
        print(f"{WARN} 没找到可用门店（无定位上下文时只能查收藏门店）")
        return 1
    print(f"门店：{stores.describe(store)}")
    print()

    menu, env = planner.fetch_menu(
        client, str(store.get("storeCode")), order_type=1, be_type=1
    )
    if not menu:
        print(f"{WARN} 菜单为空：{env.get('code')} {env.get('message')}")
        return 1
    print(f"菜单：{len(menu)} 项（已按忌口过滤）")
    print()

    combos = planner.plan(menu, budget, res, limit=args.limit)
    if not combos:
        print(f"{WARN} 预算内没有合适组合，建议放宽额度")
        return 1

    for idx, combo in enumerate(combos, 1):
        tag = chr(ord("A") + idx - 1)
        bar_len = 10
        filled = int(min(1.0, combo.total / budget) * bar_len) if budget else 0
        bar = "█" * filled + "░" * (bar_len - filled)
        save = max(0.0, budget - combo.total)
        print(f"方案 {tag}  ¥{combo.total:.2f}   {bar}   余 ¥{save:.2f}")
        print(f"  {combo.describe()}")
        if combo.reason:
            print(f"  依据：{combo.reason}")

        if args.price:
            priced = planner.price_of(client, str(store.get("storeCode")), combo)
            amount = planner.pick_amount(priced)
            print(f"  算价：{'¥%.2f' % amount if amount else '（接口未返回实付金额）'}")
        print()

    print(f"{OK} 说「下单」我再给出 create-order 的参数（默认只读，不会自动下单）")
    return 0


# ------------------------------------------------------------------- hospital


def cmd_hospital(args: argparse.Namespace) -> int:
    client = _client()
    prof = profile_mod.load()
    ctx = _ctx_from_args(args)
    res = preferences.resolve(prof, ctx)

    budget = (
        args.budget
        if args.budget is not None
        else float(prof.get("business_entertain_budget") or 0)
    )

    print(f"客户招待配单 · {ctx.people} 人 · {ctx.city or '（未指定城市）'}")
    print("─" * 58)
    print(f"  场景气温 {res.temp_c:.0f}℃（{res.temp_note}）")
    print(f"  招待额度 ¥{budget:.2f} · 单列「业务招待」不占餐补")
    print()

    store = stores.pick_store(client, city=normalize_city(ctx.city), keyword=args.keyword or "")
    if not store:
        print(f"{WARN} 没找到可用门店")
        return 1
    print(f"门店：{stores.describe(store)}")
    print()

    menu, env = planner.fetch_menu(client, str(store.get("storeCode")), order_type=1, be_type=1)
    if not menu:
        print(f"{WARN} 菜单为空：{env.get('code')} {env.get('message')}")
        return 1

    plan = hospitality.build_plan(menu, ctx.people, res, beverage_budget=budget)
    print(hospitality.render(plan))
    print()

    wrap = planner.Combo("招待", [planner.Line(o.item, o.quantity) for o in plan.offers])
    if args.price and plan.offers:
        priced = planner.price_of(client, str(store.get("storeCode")), wrap)
        amount = planner.pick_amount(priced)
        print(f"算价：{'¥%.2f' % amount if amount else '（接口未返回实付金额）'}")
    return 0


# --------------------------------------------------------------------- report


def cmd_report(args: argparse.Namespace) -> int:
    client = _client()
    prof = profile_mod.load()

    date = _today() if args.date in ("today", "今天", None) else args.date
    records = receipt.fetch_orders(client)
    if not records:
        print(f"{WARN} 没查到历史订单（或接口未返回）")
        return 1

    scoped = receipt.filter_date(records, date)
    print(receipt.render_report(scoped, prof, date=date))

    if args.csv:
        text = receipt.to_csv(scoped)
        with open(args.csv, "w", encoding="utf-8-sig") as fh:
            fh.write(text)
        print(f"\n{OK} 已导出 CSV：{args.csv}")
    return 0


# -------------------------------------------------------------------- profile


def cmd_profile(args: argparse.Namespace) -> int:
    prof = profile_mod.load()
    if args.action == "show":
        print(profile_mod.render(prof))
        print(f"\n档案位置：{profile_mod.PROFILE_PATH}")
        return 0
    if args.action == "init":
        path = profile_mod.save(prof)
        print(f"{OK} 已写入默认档案：{path}")
        print("编辑该文件即可改成你自己的城市 / 餐补 / 忌口。")
        return 0
    if args.action == "set":
        updates: Dict[str, Any] = {}
        if args.hard_avoid is not None:
            updates["hard_avoid"] = [s.strip() for s in args.hard_avoid.split(",") if s.strip()]
        if args.ice:
            updates.setdefault("taste", {})["ice"] = args.ice
        if args.hotel_address:
            updates["hotel_address"] = args.hotel_address
        if args.home_city:
            updates["home_city"] = args.home_city
        if args.budget:
            for pair in args.budget.split(","):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    updates.setdefault("daily_budget", {})[key.strip()] = float(value)
        if not updates:
            print("没有需要更新的项（用 --help 看可用参数）")
            return 1
        _merge(prof, updates)
        path = profile_mod.save(prof)
        print(f"{OK} 已更新：{path}")
        return 0
    print(f"未知动作：{args.action}")
    return 1


def _merge(base: Dict[str, Any], extra: Dict[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


# ------------------------------------------------------------------------- mcp


def cmd_mcp(args: argparse.Namespace) -> int:
    """直通调用任意麦当劳工具（默认只读）。"""
    client = _client()
    payload: Dict[str, Any] = json.loads(args.args) if args.args else {}

    if guardrails.is_write_tool(args.tool):
        if not guardrails.confirm(args.tool, payload, assume_yes=args.yes):
            return 2

    env = client.call(args.tool, payload)
    print(json.dumps(guardrails.mask_dict(env), ensure_ascii=False, indent=2)[:6000])
    return 0 if env.get("code") in (200, "200") else 1


# ------------------------------------------------------------------------ main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcd-biztravel",
        description="麦麦商旅美食专家 —— 出差在外，吃什么是你最不想花脑子的事。",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("doctor", help="连通性自检")
    p.set_defaults(func=cmd_doctor)

    def add_ctx(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--city", help="城市，如 上海 / 深圳市")
        sp.add_argument("--month", type=int, help="月份（默认当前月）")
        sp.add_argument("--hour", type=int, help="小时（默认当前时间）")
        sp.add_argument("--meal", default="lunch",
                        choices=["breakfast", "lunch", "afternoon", "dinner", "night"])
        sp.add_argument("--temp", type=float, help="实测气温℃；不传则按城市气候基线估算")
        sp.add_argument("--sodium", type=float, default=0, help="今日已摄入钠 mg")
        sp.add_argument("--kcal", type=float, default=0, help="今日已摄入热量 kcal")
        sp.add_argument("--kcal-target", type=float, default=0, help="每日热量目标 kcal")
        sp.add_argument("--keyword", help="门店关键词过滤")
        sp.add_argument("--store-code", help="指定门店 storeCode")
        sp.add_argument("--store-name", help="指定门店名称")
        sp.add_argument("--be-code", help="指定门店 beCode")

    p = sub.add_parser("prefs", help="看动态忌口怎么结算")
    add_ctx(p)
    p.set_defaults(func=cmd_prefs)

    p = sub.add_parser("plan", help="配餐方案（核心）")
    add_ctx(p)
    p.add_argument("--budget", type=float, help="本餐预算；默认取档案")
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--price", action="store_true", help="调用 calculate-price 取真实到手价")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("hospital", help="客户招待配单（冷热搭配）")
    add_ctx(p)
    p.add_argument("--people", type=int, default=2, help="在场人数")
    p.add_argument("--budget", type=float, help="招待额度；默认取档案")
    p.add_argument("--price", action="store_true")
    p.set_defaults(func=cmd_hospital)

    p = sub.add_parser("report", help="报销流水")
    p.add_argument("--date", default="today", help="日期 YYYY-MM-DD 或 today")
    p.add_argument("--csv", help="导出 CSV 到指定路径")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("profile", help="差旅档案")
    p.add_argument("action", choices=["show", "init", "set"])
    p.add_argument("--hard-avoid", help="逗号分隔，如 香菜,花生")
    p.add_argument("--ice", help="默认冰量：去冰/少冰/常温/正常冰/加冰")
    p.add_argument("--home-city")
    p.add_argument("--hotel-address")
    p.add_argument("--budget", help="如 breakfast=20,lunch=60")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("mcp", help="直通调用任意工具（默认只读）")
    p.add_argument("--tool", required=True)
    p.add_argument("--args", help="JSON 字符串")
    p.add_argument("--yes", action="store_true", help="确认执行写操作")
    p.set_defaults(func=cmd_mcp)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except MCPError as exc:
        print(f"{WARN} {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("\n已中断。", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
