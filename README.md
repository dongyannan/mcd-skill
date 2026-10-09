# mcd-skill

> 麦当劳程序员节创意开发大赛参赛作品 · 开发中
>
> 本仓库为参赛预留骨架，项目主体（README 完整版 / MCP_INTEGRATION.md / 源代码 / workbuddy.md）将在确定 Skill 方向后一次性补齐。

## 这是什么

基于**麦当劳中国 MCP Server** 开发的创意 Skill 项目，参加「麦当劳程序员节创意开发大赛」。

## 参赛必备文件进度

| 文件 | 状态 |
|---|---|
| `README.md` | ⏳ 骨架（待补全：安装方法 / 使用示例 / 目标用户） |
| `CONTEST_DECLARATION.md` | ✅ 官方原文，未作任何改动 |
| `MCP_INTEGRATION.md` | ⏳ 待补（需确定实际调用的 Tool 列表） |
| `mcp-config.example.json` | ✅ 脱敏示例，仅环境变量占位符 |
| 源代码 | ⏳ 待补 |
| `workbuddy.md` | ⏳ 待补（WorkBuddy 专项积分奖励用） |

## 麦当劳 MCP 接入方式

1. 前往 <https://open.mcd.cn/mcp> 手机号登录 → 控制台 → 激活 → 复制 Token
2. 在支持 MCP 的客户端中按 `mcp-config.example.json` 的结构配置
3. 把 `${MCD_MCP_TOKEN}` 替换为你的真实 Token（**切勿提交到仓库**）

```bash
export MCD_MCP_TOKEN="your-token-here"
```

## 声明

本项目为参赛作品，由参赛者独立开发，**非麦当劳官方产品**。项目输出仅供参考，不构成医疗、营养或其他专业建议；餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。

详见 [CONTEST_DECLARATION.md](./CONTEST_DECLARATION.md)。
