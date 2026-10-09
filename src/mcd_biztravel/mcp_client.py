"""极简 MCP Streamable HTTP 客户端（仅标准库，零依赖）。

麦当劳 MCP 服务端：https://mcp.mcd.cn
协议：JSON-RPC 2.0 over HTTP，响应可能是 JSON 也可能是 SSE（text/event-stream）。
工具的返回体是一段「字段说明 + 原始 JSON」的文本，本模块负责把原始 JSON 抽出来。

设计要点：
- 只用标准库，`pip install` 都不需要；
- 不缓存 Token、不落盘、不写日志（Token 只从环境变量 `MCD_MCP_TOKEN` 读）；
- 401 / 429 给出可读的处置建议，而不是抛裸异常。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_ENDPOINT = "https://mcp.mcd.cn"
ENV_TOKEN = "MCD_MCP_TOKEN"
PROTOCOL_VERSION = "2024-11-05"

_JSON_DECODER = json.JSONDecoder()


class MCPError(RuntimeError):
    """MCP 调用失败（网络 / 鉴权 / 限流 / 协议）。"""


def extract_json(text: str) -> Optional[Any]:
    """从「说明文字 + JSON」混合文本里抽出第一个合法 JSON 对象。

    麦当劳工具的返回体形如：``## Response Structure ... {"success":true,...}``
    直接 ``json.loads`` 会失败，因此从每个 ``{`` 起点尝试增量解码。
    """
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return _JSON_DECODER.raw_decode(stripped)[0]
        except ValueError:
            pass

    # 优先从 {"success" 或 {"code" 这种「响应信封」起点找
    for anchor in ('{"success"', '{"code"', '{"data"', '{"message"'):
        idx = text.find(anchor)
        if idx >= 0:
            try:
                return _JSON_DECODER.raw_decode(text, idx)[0]
            except ValueError:
                continue

    idx = 0
    while True:
        idx = text.find("{", idx)
        if idx < 0:
            return None
        try:
            return _JSON_DECODER.raw_decode(text, idx)[0]
        except ValueError:
            idx += 1


def _parse_body(raw: str) -> Dict[str, Any]:
    """把响应体（JSON 或 SSE）解析成 JSON-RPC 信封。"""
    text = raw.strip()
    if not text:
        raise MCPError("服务端返回空响应")

    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except ValueError:
            pass

    # SSE：逐行取 data: 负载，取最后一个能解析出 result 的
    fallback: Optional[Dict[str, Any]] = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            parsed = json.loads(payload)
        except ValueError:
            continue
        if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
            return parsed
        fallback = parsed
    if fallback is not None:
        return fallback
    raise MCPError("无法解析服务端响应（既不是 JSON 也不是 SSE）")


class MCDClient:
    """麦当劳 MCP 客户端。

    用法::

        client = MCDClient()                     # 自动读 $MCD_MCP_TOKEN
        print(client.call("now-time-info"))
        print(client.call("query-meals", {
            "storeCode": "1950040", "orderType": 1, "beType": 1,
        }))
    """

    def __init__(
        self,
        token: Optional[str] = None,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: int = 40,
    ) -> None:
        self.token = (token or os.environ.get(ENV_TOKEN) or "").strip()
        if not self.token:
            raise MCPError(
                "缺少麦当劳 MCP Token。\n"
                "  1) 打开 https://open.mcd.cn/mcp → 控制台 → 激活 → 复制 Token\n"
                f"  2) export {ENV_TOKEN}=<你的Token>\n"
                "  ⚠️ 切勿把 Token 写进代码或提交到仓库。"
            )
        self.endpoint = endpoint
        self.timeout = timeout
        self._seq = 0
        self._tools: Optional[List[Dict[str, Any]]] = None

    # ------------------------------------------------------------------ 内部

    def _rpc(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._seq += 1
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": self._seq, "method": method, "params": params},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:  # pragma: no cover - 网络相关
            code = exc.code
            if code == 401:
                raise MCPError("401：Token 无效或已失效，请到 open.mcd.cn/mcp 重新激活。") from exc
            if code == 429:
                raise MCPError("429：触发限流（600 次/分钟），稍后重试。") from exc
            raise MCPError(f"HTTP {code}：{exc.reason}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover - 网络相关
            raise MCPError(f"网络不可达：{exc.reason}（如在国内网络，请检查代理是否开启）") from exc

        envelope = _parse_body(raw)
        if "error" in envelope:
            err = envelope["error"] or {}
            raise MCPError(f"MCP 错误 {err.get('code')}: {err.get('message')}")
        return envelope

    # ------------------------------------------------------------------ 公开

    def initialize(self) -> Dict[str, Any]:
        """协议握手，返回服务端信息。"""
        env = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcd-biztravel-gourmet", "version": "0.1.0"},
            },
        )
        return env.get("result", {})

    def list_tools(self) -> List[Dict[str, Any]]:
        """列出服务端全部工具（带缓存）。"""
        if self._tools is None:
            env = self._rpc("tools/list", {})
            self._tools = (env.get("result") or {}).get("tools") or []
        return self._tools

    def tool_names(self) -> List[str]:
        return [t.get("name", "") for t in self.list_tools()]

    def call_raw(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """调用工具并返回原始文本内容。"""
        env = self._rpc(
            "tools/call", {"name": name, "arguments": arguments or {}}
        )
        result = env.get("result") or {}
        chunks = result.get("content") or []
        text = "".join(
            c.get("text", "") for c in chunks if isinstance(c, dict)
        )
        if not text:
            text = json.dumps(result, ensure_ascii=False)
        return text

    def call(
        self, name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """调用工具并返回解析后的信封 ``{success, code, message, data}``。

        麦当劳工具的成功/失败都体现在信封的 ``code`` 上（200 成功，
        600058 之类为业务错误），因此不抛异常，交由调用方判断。
        """
        text = self.call_raw(name, arguments)
        parsed = extract_json(text)
        if not isinstance(parsed, dict):
            return {
                "success": False,
                "code": -1,
                "message": "返回体不是 JSON",
                "raw": text[:2000],
            }
        parsed.setdefault("raw", text)
        return parsed


def is_ok(envelope: Dict[str, Any]) -> bool:
    """判断工具调用是否业务成功。"""
    return bool(envelope.get("success")) and envelope.get("code") in (200, "200")


def require_ok(envelope: Dict[str, Any], what: str = "接口") -> Dict[str, Any]:
    """业务失败时抛出带上下文的异常。"""
    if not is_ok(envelope):
        raise MCPError(
            f"{what}调用失败：code={envelope.get('code')} "
            f"message={envelope.get('message')}"
        )
    return envelope
