# 中心化资金数据 API 接口说明

产品参考 ValueScan：https://www.valuescan.io/

详细接口文档：https://claw.valuescan.io/zh-CN/%E6%A6%82%E8%BF%B0.html



## 基础接口

| 接口名称 | 接口描述 | 请求方式 | 接口路径 | 积分消耗 |
|---------|---------|---------|---------|:-------:|
| 代币列表 | 获取 ValueScan 支持的代币列表，支持按代币全称或简称模糊搜索 | POST | `/open/v1/vs-token/list` | 1 |
| 代币基本信息 | 获取指定代币的基础信息，包括市场信息、链上基本信息、行情基本信息等 | POST | `/open/v1/vs-token/detail` | 1 |
| K 线数据 | 获取指定代币在指定时间段内不超过1000条的K线数据 | POST | `/open/v1/trade/kline/getTradeKLineList` | 1 |

## 资金数据

| 接口名称 | 接口描述 | 请求方式 | 接口路径 | 积分消耗 |
|---------|---------|---------|---------|:-------:|
| 实时资金积累 | 获取指定代币在中心化交易所的实时净流入数据及当日主力资金积累数据 | POST | `/open/v1/trade/getCoinTrade` | 3 |
| 资金快照 | 获取指定代币在最近100天内任意时间点的资金积累数据及主力资金积累数据 | POST | `/open/v1/trade/getCoinTradeSnapshot` | 3 |
| 板块资金列表 | 获取所有板块在不同时间窗口下的实时资金积累数据 | POST | `/open/v1/trade/categories/getTradeList` | 3 |
| 板块代币资金 | 获取指定板块下所有代币的现货或合约在不同时间窗口下的实时资金积累数据 | POST | `/open/v1/trade/categories/CoinTradeList` | 3 |
| 资金市值比 | 获取代币实时主力资金与市值的比值，支持现货和合约两种交易类型 | POST | `/open/v1/trade/getCoinTradeInflowMarketCapRatio` | 3 |

## 链上数据

| 接口名称 | 接口描述 | 请求方式 | 接口路径 | 积分消耗 |
|---------|---------|---------|---------|:-------:|
| 代币流向 | 获取代币在链上持仓地址与中心化交易所之间的资金流入/流出及变化率数据 | POST | `/open/v1/trade/getCoinTradeFlow` | 2 |
| 主力成本变化趋势 | 获取代币在多链上的大户实时平均持仓成本数据 | POST | `/open/v1/trade/getCoinTradeCost` | 2 |
| 大额交易 | 获取指定代币在20+主流公链上的大额交易数据 | POST | `/open/v1/chain/trade/large` | 2 |
| 持币地址 | 获取指定代币在链上的持仓地址列表及地址基础信息，支持指定地址查询 | POST | `/open/v1/chain/trade/token/holdPage` | 2 |
| 余额趋势 | 获取指定地址对某代币在指定链、时间段内的持仓余额变化趋势 | POST | `/open/v1/chain/trade/token/balanceTrend` | 2 |
| 盈亏趋势 | 获取指定地址对某代币在指定链、时间段内的盈亏统计数据 | POST | `/open/v1/chain/trade/token/profitLossTrend` | 2 |
| 持仓成本趋势 | 获取指定地址对某代币在指定链、时间段内的持仓成本变化趋势 | POST | `/open/v1/chain/trade/token/holdTrend` | 2 |
| 交易行为趋势 | 获取指定地址对某代币在指定链、时间段内的链上交易统计数据 | POST | `/open/v1/chain/trade/token/tradeCountTrend` | 2 |

## AI 追踪

| 接口名称 | 接口描述 | 请求方式 | 接口路径 | 积分消耗 |
|---------|---------|---------|---------|:-------:|
| 压力支撑位 | 获取AI通过多数据维度动态生成的代币智能压力位与支撑位价格数据 | POST | `/open/v1/indicator/getDenseAreaList` | 3 |
| 主力行为指标 | 获取BTC/ETH在特定时间范围内因主力动作可能影响价格趋势的特色指标数据 | POST | `/open/v1/indicator/getPriceMarketList` | 3 |
| 机会代币列表 | 获取AI追踪的当前行情下具有上涨潜力的代币列表 | POST | `/open/v1/ai/getChanceCoinList` | 3 |
| 机会代币消息 | 获取AI对具有上涨潜力代币的追踪消息数据 | POST | `/open/v1/ai/getChanceCoinMessageList` | 3 |
| 风险代币列表 | 获取AI追踪的当前行情下具有下跌风险趋势的代币列表 | POST | `/open/v1/ai/getRiskCoinList` | 3 |
| 风险代币消息 | 获取AI对具有下跌风险趋势代币的追踪消息数据 | POST | `/open/v1/ai/getRiskCoinMessageList` | 3 |
| 资金异动列表 | 获取在中心化交易所上监控到主力资金异动的代币列表 | POST | `/open/v1/ai/getFundsCoinList` | 3 |
| 资金异动消息 | 获取指定代币在中心化交易所上主力资金异动的历史监控消息记录 | POST | `/open/v1/ai/getFundsCoinMessageList` | 3 |
| 大盘分析订阅 | 大盘分析SSE流式订阅，ValueAgent对BTC/ETH行情的综合分析推送 | GET (SSE) | `https://stream.valuescan.ai/stream/market/subscribe` | - |
| 代币信号订阅 | 代币信号SSE流式订阅，当订阅代币产生机会/风险/资金异动信号时主动推送 | GET (SSE) | `https://stream.valuescan.ai/stream/signal/subscribe` | - |
| 社媒情绪 | 获取单个代币的市场情绪指标，包括看涨、看跌、中立观点比例及内容 | POST | `/open/v1/social-sentiment/getCoinSocialSentiment` | 3 |

---

> **Base URL（REST接口）：** `https://claw.valuescan.io`
> **Base URL（流式接口）：** `https://stream.valuescan.ai`

---



# DEX 数据 API 接口说明

产品参考 DexScan：https://dex.valuescan.ai/trend

详细接口文档：https://web3-dexscan.gitbook.io/api



> **Base URL：** `https://kcapi.dexscan.trade`

## 行情价格 API

| 接口名称 | 接口描述 | 请求方式 | 接口路径 |
|---------|---------|---------|---------|
| 获取历史K线 | 查询代币的历史K线，返回结果按时间倒序排列 | POST | `/v3/dex/market/kline-history` |
| 获取K线最新秒级数据 | 获取代币最新的秒级K线，用于历史K线调用或WebSocket断线重连后补充缺失数据 | POST | `/v3/dex/market/kline-latest-second` |
|  |  |  |  |
| K线 WebSocket | 连接地址 `wss://kcapi.dexscan.trade/websocket`，采用STOMP协议通信 | WebSocket | - |
| K线 | 通过WebSocket实时获取代币K线推送消息 | SUBSCRIBE | `/kline/{chainName}/{tokenContractAddress}` |
| 交易 | 通过WebSocket实时获取代币交易推送消息 | SUBSCRIBE | `/trade/{chainName}/{tokenContractAddress}` |
| 获取代币当前价格 | 获取代币的最新价格 | POST | `/v3/dex/market/current-price` |

## 币种及池子信息 API

| 接口名称 | 接口描述 | 请求方式 | 接口路径 |
|---------|---------|---------|---------|
| 获取代币统计信息（涨跌幅/成交量/最高价/最低价） | 批量获取代币统计信息，包括涨跌幅、成交量、最高价、最低价 | POST | `/v3/dex/market/stats` |
| 获取代币Liquidity（coin-liquid） | 获取代币的流动性 | POST | `/v3/dex/market/coin-liquid` |
| 批量获取代币Liquidity（coin-liquid-batch） | 批量获取代币的流动性 | POST | `/v3/dex/market/coin-liquid-batch` |
| 获取代币市值（coin-market-cap） | 获取代币的市值 | POST | `/v3/dex/market/coin-market-cap` |
| 获取价格信息（price-info） | 获取代币价格信息，包含市值及不同时间粒度的涨跌幅和成交量 | POST | `/v3/dex/market/price-info` |
| 榜单接口（coin-rank） | 获取代币榜单排行列表，支持按链、时间粒度、多种指标排序 | POST | `/v3/dex/market/coin-rank` |
| DEX交易记录（trade-scroll） | 获取代币交易列表 | POST | `/v3/dex/market/trade-scroll` |
| 代币Top 100持仓（coin-balance-top） | 获取代币持币数量Top 100列表 | POST | `/v3/dex/market/coin-balance-top` |
| 代币Top 5池子（liquid-pool-top） | 获取代币Top 5流动性池子列表 | POST | `/v3/dex/market/liquid-pool-top` |
| 代币流动性变化（liquid-change-scroll） | 获取代币流动性变化记录，支持添加/移除流动性筛选 | POST | `/v3/dex/market/liquid-change-scroll` |
| 获取代币信息（coin-infos） | 获取代币信息，包括价格、供应量、持有者数据等 | POST | `/v3/dex/market/coin-infos` |
| 获取代币风险标签（coin-risk-labels） | 获取代币风险等级标签 | POST | `/v3/dex/market/coin-risk-labels` |

## Alpha 代币 API

| 接口名称 | 接口描述 | 请求方式 | 接口路径 |
|---------|---------|---------|---------|
| 获取代币信息（coin-infos） | 获取Alpha代币信息，包括价格、交易量、持有者数据等 | POST | `/v3/dex/alpha/coin-infos` |

## Hyper Liquid

| 接口名称 | 接口描述 | 请求方式 | 接口路径 |
|---------|---------|---------|---------|
| 资产查询 | 获取用户资产信息，包括代币余额和价格 | GET | `/v3/hyper/asset` |
| 合约查询 | 获取用户合约持仓信息，包括仓位、杠杆、盈亏等 | GET | `/v3/hyper/contract` |
| 未完成订单查询 | 查询用户订单列表 | POST | `/v3/order/query` |
| 成交记录查询 | 查询用户成交记录列表 | POST | `/v3/trade/query` |
| 转账记录查询 | 查询用户账本变动列表 | POST | `/v3/ledger/query` |
| 爆仓交易查询 | 查询用户清算记录列表 | POST | `/v3/liquidation/query` |

## 社交热度 API

| 接口名称 | 接口描述 | 请求方式 | 接口路径 |
|---------|---------|---------|---------|
| 获取社交热度 | 获取代币的社交热度数据，包括热度值、热度涨跌幅、热度贡献及交易买入Top5 KOL、24小时价格走势与涨跌幅，以及推文AI总结 | POST | `/api/heat/heatList` |
