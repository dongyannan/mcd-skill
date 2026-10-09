"""门店发现 —— 到店自取 / 得来速 / 麦乐送 / 企业团餐。

实测结论（2026-10-09，mcd-mcp v1.0.0）：

* ``query-nearby-stores(searchType=1)`` → 返回**收藏/常用门店**，可用；
* ``query-nearby-stores(searchType=2)`` → 需要真实定位，无定位上下文时返回
  ``600058 城市名或者关键词不能为空``，**当前不可用**；
* ``delivery-query-stores`` 需要先有 ``addressId``（来自 ``delivery-query-addresses``）。

因此本模块的策略是：**收藏门店优先**，拿不到再引导用户补一个外送地址。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .mcp_client import MCDClient, is_ok

BE_ONSTORE = 1      # 到店自提
BE_DELIVERY = 2     # 麦乐送
BE_DRIVE = 5        # 得来速
BE_CATERING = 6     # 企业团餐


def list_favorite_stores(client: MCDClient) -> List[Dict[str, Any]]:
    """收藏门店（到店自取场景）。"""
    env = client.call(
        "query-nearby-stores", {"beType": BE_ONSTORE, "searchType": 1}
    )
    if not is_ok(env):
        return []
    data = env.get("data") or []
    return data if isinstance(data, list) else []


def find_stores(
    client: MCDClient, city: str = "", keyword: str = ""
) -> List[Dict[str, Any]]:
    """按城市/关键词挑门店；命中不了就返回全部收藏门店。"""
    stores = list_favorite_stores(client)
    if not stores:
        return []

    def match(s: Dict[str, Any]) -> bool:
        text = f"{s.get('storeName', '')}{s.get('address', '')}"
        if city and city not in text:
            return False
        if keyword and keyword not in text:
            return False
        return True

    hit = [s for s in stores if match(s)]
    return hit or stores


def pick_store(
    client: MCDClient, city: str = "", keyword: str = ""
) -> Optional[Dict[str, Any]]:
    stores = find_stores(client, city=city, keyword=keyword)
    return stores[0] if stores else None


def list_addresses(client: MCDClient) -> List[Dict[str, Any]]:
    """外送地址列表。"""
    env = client.call("delivery-query-addresses", {})
    if not is_ok(env):
        return []
    data = env.get("data") or {}
    addresses = data.get("addresses") if isinstance(data, dict) else None
    return addresses if isinstance(addresses, list) else []


def pick_address(client: MCDClient, keyword: str = "") -> Optional[Dict[str, Any]]:
    addresses = list_addresses(client)
    for addr in addresses:
        if keyword and keyword in str(addr.get("fullAddress", "")):
            return addr
    return addresses[0] if addresses else None


def delivery_stores(
    client: MCDClient, address_id: str, catering: bool = False
) -> List[Dict[str, Any]]:
    """按地址查可配送门店；``catering=True`` 走企业团餐通道（beType=6）。"""
    env = client.call(
        "delivery-query-stores",
        {"addressId": address_id, "beType": BE_CATERING if catering else BE_DELIVERY},
    )
    if not is_ok(env):
        return []
    data = env.get("data") or []
    return data if isinstance(data, list) else []


def describe(store: Optional[Dict[str, Any]]) -> str:
    if not store:
        return "（未找到门店）"
    name = store.get("storeName", "?")
    code = store.get("storeCode", "?")
    be = store.get("beCode") or "-"
    addr = store.get("address", "")
    return f"{name}｜storeCode={code}｜beCode={be}｜{addr}"
