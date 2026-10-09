# MCP 集成说明 · MCP_INTEGRATION

> 本文说明「麦麦商旅美食专家」**实际使用了哪些麦当劳 MCP Tool、按什么顺序调用、产生了什么业务价值**，以及集成过程中的实测发现与踩坑记录。
>
> 实测环境：`mcd-mcp v1.0.0` · 接入地址 `https://mcp.mcd.cn` · 限流 600 次/分钟 · 复核日期 2026-10-09

---

## 一、接入方式

麦当劳 MCP Server 采用 **Streamable HTTP** 传输（JSON-RPC 2.0 over HTTP，响应可能是 JSON 或 SSE）。

本项目**没有引入任何 MCP SDK**，而是用 Python 标准库实现了一个约 200 行的极简客户端（`src/mcd_biztravel/mcp_client.py`），原因有三：

1. **零依赖** —— 评审和用户 clone 下来就能跑，不用配环境；
2. **可读性强** —— 一次 `initialize` + `tools/list` + `tools/call` 的完整链路全在明面上；
3. **单元测试可离线跑** —— 21 项测试不依赖网络。

```jsonc
// mcp-config.example.json（仓库内的脱敏示例，仅占位符）
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": { "Authorization": "Bearer ${MCD_MCP_TOKEN}" }
    }
  }
}
```

代码侧 Token 只从环境变量 `MCD_MCP_TOKEN` 读取，**不落盘、不写日志、不进仓库**。

---

## 二、实际使用的工具（15 个 / 服务端共 35 个）

### 2.1 门店发现

| 工具 | 用在哪 | 关键参数 |
| --- | --- | --- |
| `query-nearby-stores` | 到店自取门店（高铁站早餐、客户楼下买咖啡） | `beType=1`, `searchType=1` |
| `delivery-query-addresses` | 拉取外送地址，选「会场 / 酒店」收货点 | 无参 |
| `delivery-query-stores` | 按地址查可配送门店（落地第一餐、酒店夜宵） | `addressId`, `beType=2` |
| `delivery-create-address` | 把「会场 / 展位」建成临时收货地址 | `city`,`contactName`,`phone`,`address` ⚠️写操作 |

### 2.2 菜单、算价与营养

| 工具 | 用在哪 | 关键参数 |
| --- | --- | --- |
| `query-meals` | 取门店菜单（分类 + 餐品详情映射表） | `storeCode`, `orderType`, `beType` |
| `query-meal-detail` | 查看套餐组成 / 换特制（换燕麦奶、去酱） | `storeCode`,`code`,`beType`,`orderType` |
| `calculate-price` | **下单前必经**：取含优惠的到手价 | `storeCode`,`orderType`,`beType`,`items[]` |
| `list-nutrition-foods` | 当日热量 / 钠汇总（夜宵控卡控钠） | 无参 |

### 2.3 券与积分

| 工具 | 用在哪 | 说明 |
| --- | --- | --- |
| `query-store-coupons` | **指定门店 + 订单类型**下真正可用的券 | 只有这个能承诺"能用" |
| `query-my-coupons` | 卡包券总览（不校验门店可用性） | 仅用于展示 |
| `available-coupons` | 当前可领取的券 | 只读 |
| `query-my-account` | 积分余额 / 过期积分提醒 | 只读 |

### 2.4 订单与报销

| 工具 | 用在哪 |
| --- | --- |
| `order-list` | 拉当日/历史餐品订单 → 报销流水的**唯一数据源** |
| `query-order` | 单笔订单详情 / 配送进度 |

### 2.5 团队与招待（差异化部分）

| 工具 | 用在哪 |
| --- | --- |
| `delivery-query-stores`(`beType=6`) | 企业团餐通道，团队出差配送 |
| `query-meal-assistance` | 团餐**算价前**取助餐服务 |
| `query-promotions` | 团餐场景**满减 / 满折规则** |
| `now-time-info` | 服务端时间，用于倒推下单时点 |

> **未使用但已识别**：`create-order` / `cancel-order` / `auto-bind-coupons` / `draw-lottery` / `mall-*` / `party-*` / `campaign-calendar` / `query-survey-coupon` / `query-my-prizes`。这些工具在 `doctor` 命令里被显式标记为**写操作**并纳入护栏清单（共 7 个）。

---

## 三、调用链（以「一日四餐」为例）

```text
[00] now-time-info                      ← 取服务端时间，锁定"现在几点"
        │
[01] query-nearby-stores(searchType=1)  ← 收藏门店 → storeCode
        │
[02] query-meals(storeCode, orderType, beType)
        │        └─ 解析 categories[].meals[].code + meals{code:{name,currentPrice}}
        │
[03] preferences.resolve(城市, 气温, 时段, 当日营养)   ← 本地动态忌口结算
        │        └─ 硬禁忌过滤 → 冰量档位 → 咖啡因/油炸降权
        │
[04] planner.plan(menu, 预算, 已结算偏好)               ← 官方团餐搭配规则
        │        └─ ⩽20 小食 ｜ 20–30 汉堡+小食/饮料 ｜ 30–40 +薯条+饮料 ｜ 40–50 全配 ｜ >50 丰富组合
        │
[05] calculate-price(storeCode, items[])                ← 取含优惠的真实到手价
        │
[06] query-store-coupons(storeCode, orderType, beType)  ← 该门店真正可用的券
        │
[07] order-list                                        ← 当日订单 → 报销流水
```

招待场景在 `[03]` 与 `[04]` 之间插入 **hospitality 引擎**（冷热比 / 品类去重 / 备损 / 无咖啡因），再走 `[05]` 算价。

---

## 四、业务价值

| 能力 | 由哪些工具支撑 | 价值 |
| --- | --- | --- |
| 「来不来得及」判断 | `now-time-info` + `query-nearby-stores` | 商旅早餐的真痛点是**时间不可控**，不是选什么 |
| 「几点下单」倒推 | `delivery-query-stores`（含配送时长） | 手动点外卖最容易踩空的地方 |
| 预算内配餐 | `query-meals` + `calculate-price` | 把"随便吃"变成"额度内吃得合理" |
| 券真正可用 | `query-store-coupons`（而非 `query-my-coupons`） | 不承诺"我有券"而承诺"这单能用" |
| 客情体面 | `query-nearby-stores` + `query-meals` | 冷热搭配 + 品类去重，且**单独记业务招待** |
| 一天的账 | `order-list` | 睡前一句话出报销流水，不用翻手机 |
| 团队 / 团餐 | `delivery-query-stores`(6) + `query-meal-assistance` + `query-promotions` | 复用官方团餐专属工具，榜上罕有人做 |

---

## 五、护栏（写操作一律二次确认）

麦当劳官方工具描述里已经定死了这条规矩 —— 例如 `draw-lottery` 明确写「**必须先展示消耗并得到用户确认**」。本项目把它落成代码里的硬闸门（`guardrails.py`）：

```python
WRITE_TOOLS = {
    "create-order":          "创建订单（真实下单，会产生费用）",
    "cancel-order":          "取消订单（真实取消，可能影响已支付订单）",
    "auto-bind-coupons":     "一键领取全部可领券（会改动券包）",
    "draw-lottery":          "执行抽奖（消耗抽奖机会 / 积分）",
    "mall-create-order":     "积分商城兑换下单（消耗积分）",
    "party-order-create":    "主题派对预订下单（包场 / 拼团）",
    "delivery-create-address": "新建配送地址（写入账号地址簿）",
}
```

**默认行为**：命中写操作且未加 `--yes` → **打印「将要发生什么」后直接拦截**，交给用户确认：

```text
┌─ 写操作确认 ──────────────────────────────
│ 工具：create-order
│ 说明：创建订单（真实下单，会产生费用）
│ 参数：{'storeCode': '1950040', 'items': [...]}
└──────────────────────────────────────────
已拦截：未加 --yes，本次不执行。确认无误后请加 --yes 重跑。
```

另外两条护栏：**输出打码**（手机号 `138****5678`、身份证号、长订单号）与**Token 不落盘**。

---

## 六、实测发现与踩坑记录

以下是集成过程中**真机验证**出的问题，均已在本项目里处理：

### 6.1 响应体不是纯 JSON，而是「说明文字 + 原始 JSON」

`tools/call` 返回的 `content[].text` 形如：

```text
## Response Structure
- **data.list[].orderId**: 订单编码 (Type: string)
...
## Original Response

{"success":true,"code":200,...,"data":{"list":[...]}}
```

直接 `json.loads` **必然失败**。项目内用 `extract_json()` 从 `{"success"` 等锚点做增量解码（`JSONDecoder.raw_decode`）解决。

### 6.2 ⚠️ 金额单位不一致（最容易算错）

| 来源 | 字段 | 单位 |
| --- | --- | --- |
| `query-meals` | `meals[code].currentPrice` | **元**（字符串，如 `"21.0"`） |
| `calculate-price` | `price` / `productPrice` / `originalPrice` | **分**（整数，如 `2990`） |

未换算时输出会出现「算价 ¥1900.00」这种乌龙。已在 `planner.pick_amount()` 统一 ÷100。

### 6.3 `query-nearby-stores(searchType=2)` 需要真实定位

- `searchType=1`（收藏门店）→ ✅ 正常返回 `storeName/storeCode/beCode/reservation`；
- `searchType=2`（按位置）→ ❌ 传 `city` 或 `keyword` 均返回 `600058 城市名或者关键词不能为空`；
- 结论：无定位上下文时，**收藏门店是唯一可靠路径**（本项目按此实现，并在无命中时回退）。

### 6.4 冷热在麦当劳是「特制选项」，不是 SKU

菜单里 `可乐 / 雪碧 / 阳光柠檬红茶` 等 SKU **不带冷热属性**；热饮需要在下单时通过**商品特制选项**指定。

因此招待配单引擎不会假装"已经选好热饮"，而是：

1. 优先选菜单里带「热」标识的 SKU；
2. 没有时，按常温下单并**显式告警**：*"冷热属于商品特制选项，请下单时把这几杯改成热饮"*。

### 6.5 其他

- `beCode` 的传递规则因场景而异：**到店自取（beType=1）不传**，得来速(5)/外送(2)/团餐(6) **必传**，传错会直接报错；
- `calculate-price` 的 `items[]` 结构：`{productCode, quantity, couponCode?, modification:{values:[{key,code,quantity}]}, roundList?}`；
- 官方 README 的工具表与实际 `tools/list` 有出入（实际多出 `query-promotions`、`query-survey-coupon`，且 `query-partystore-session` 真名为 `query-party-store-session`）—— **以 `tools/list` 实测为准**。

---

## 七、复核方式

```bash
# 连通性 + 工具清单 + 只读/写操作分栏
mcd-biztravel doctor

# 直接看原始返回
mcd-biztravel mcp --tool query-my-account
mcd-biztravel mcp --tool query-meals \
  --args '{"storeCode":"1950040","orderType":1,"beType":1}'
```

或绕过本项目直接打服务端：

```bash
curl -s -X POST https://mcp.mcd.cn \
  -H "Authorization: Bearer $MCD_MCP_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```
