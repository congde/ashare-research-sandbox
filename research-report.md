# Web3 研究与模拟策略验证台：用户与方案调研

> 虚构教学资产「示例协议（WEB3-DEMO/USDT）」仅用于课程演示。本报告支撑
> [product-brief.md](product-brief.md) 与 [prd.md](prd.md) 的范围决定。

## Facts

- F1: Web3 行情与链上数据通常分散在交易所、区块浏览器和数据平台，实时接入
  往往需要 API Key、账户、网络或付费额度。
- F2: 课程学习者需要的是可复查的研究与模拟流程，而不是一次性市场结论。
- F3: [web3-trading](https://github.com/congde/web3-trading) 提供回测、报告、
  Web 前端和运行时能力，是本课程主代码案例；其生产形态依赖外部服务。
- F4: [ai-trading](https://github.com/johnnywuj81/ai-trading) 的受限策略 DSL、
  风险控制和 React 前端可补充主案例。

## Inferences

- I1: 固定离线 Web3 数据能消除 API Key、账户、网络波动和数据口径变化，让
  每位学习者得到相同验收结果。Supports: F1, F2
- I2: 第一版应直接沿用 web3-trading 的产品形状，选择性复用纯回测与报告能力，
  暂不启用实时交易和外部服务。Supports: F3
- I3: ai-trading 应作为能力补充，而不是第二套并行产品。Supports: F4

## Recommendations

- R1: **Go（继续）**：实现固定 Web3 样本、来源卡、双均线回测、浏览器界面与
  自动验收。
- R2: 保留上游代码基线和来源记录，逐项适配并为每项行为增加确定性测试。
- R3: 其他市场研究可作为后续数据适配方向，不承担当前课程的贯穿数据依赖。

## Unknowns

- U1: 后续是否需要导入用户自己的 CSV 数据。
- U2: 是否需要增加第二段固定样本来展示策略对行情区间的敏感性。
- U3: 若未来接入真实 Web3 数据，来源授权、口径和合规成本如何审查。

## 方案对照

| 方案 | 优势 | 第一版决定 |
|---|---|---|
| `web3-trading` 主案例 | 回测、报告、前端、运行时较完整 | 保留基线，选择性适配 |
| `ai-trading` 能力补充 | 受限 DSL、风险控制、React 前端 | 按需融合 |
| 实时交易所与链上 API | 数据新鲜 | 暂不接入，避免密钥与不可复现依赖 |
