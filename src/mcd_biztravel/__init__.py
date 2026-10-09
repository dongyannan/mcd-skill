"""麦麦商旅美食专家 —— 出差在外，吃什么是你最不想花脑子的事。

一个面向商旅场景的麦当劳 MCP 助手：
  省心（不用想）> 省事（不用算）> 省钱（顺带）

模块：
  mcp_client   极简 MCP Streamable HTTP 客户端（仅标准库）
  climate      内置城市气候基线（无外网也能动态调整）
  preferences  动态忌口引擎（硬禁忌 / 静态偏好 / 动态层）
  profile      差旅档案（城市 / 餐补 / 酒店地址）
  stores       门店发现（到店 / 外送 / 团餐）
  planner      预算配餐引擎
  hospitality  招待搭配引擎（冷热搭配 + 品类去重）
  receipt      报销流水
  guardrails   写操作护栏 + 敏感信息打码
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
