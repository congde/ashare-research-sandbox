# ADR-0009：自研事件驱动回测引擎（借鉴 jesse 设计）

**状态**：accepted
**日期**：2026-05-08
**决策者**：CTO + 量化负责人

---

## 1. 背景与问题

PRD §4.1 F-SE-02 要求事件驱动回测，含手续费 / 滑点 / 资金管理。M2 里程碑要求与 freqtrade PNL 偏差 < 5%。

是直接用 freqtrade / vectorbt？还是自研？

## 2. 决策驱动力

- 与 Strategy Agent 紧耦合（受限 DSL on_tick 签名）
- 需自定义滑点 / 资金管理 / 多交易对 / 多 timeframe
- jesse 设计是开源中最严谨的，参考其架构
- 完全控制权 vs 复用社区

## 3. 候选方案

### 方案 A：直接用 freqtrade
- 优点：成熟 / 社区强
- 缺点：
  - GPL-3.0（污染闭源 SaaS）
  - Strategy class 与 AI-Trading DSL 不兼容
  - 改造成本 > 自研
- 推荐度：⭐

### 方案 B：直接用 vectorbt
- 优点：性能极致（向量化）
- 缺点：
  - 不是真正事件驱动（vectorize 不适合实盘代码复用）
  - 与 AI-Trading on_tick 范式不匹配
- 推荐度：⭐⭐

### 方案 C（推荐）：自研事件驱动 + 借鉴 jesse 设计
- 优点：
  - 与 DSL on_tick 完全一致（实盘代码即回测代码）
  - 完全控制滑点 / 资金管理 / 多策略
  - Apache-2.0 友好
- 缺点：
  - 工作量 ~2 周
  - 需 M2 与 freqtrade 对齐验证
- 推荐度：⭐⭐⭐⭐⭐

### 方案 D：fork jesse 改造
- 优点：起点高
- 缺点：jesse 是 MIT，但代码量大；维护双侧成本
- 推荐度：⭐⭐

## 4. 选定方案

**方案 C：自研事件驱动 + 借鉴 jesse 设计**

### 核心设计

```
Event Loop（按时间戳）
  ├── on_candle(candle)       ← K 线事件（每个 timeframe）
  │   └── strategy.on_tick(ctx, candle) → OrderIntent | None
  │       ↓
  │   RiskManager.check(intent) → pass | reject
  │       ↓
  │   simulate_order(intent, slippage_model, fee_model)
  │       ↓
  │   PositionTracker.update(fill)
  │
  └── on_funding（衍生品资金费率）  [v1.5]

输出：
  - PNL 时间序列
  - drawdown 曲线
  - trades 列表（每笔含 entry/exit/pnl/duration）
  - metrics（Sharpe / Sortino / Calmar / win_rate / max_drawdown / …）
  - daily/weekly summary
```

### 关键模块

```python
# packages/core/backtest/

class BacktestEngine:
    def __init__(
        self,
        strategy_code: str,
        data_provider: DataProvider,
        slippage_model: SlippageModel,
        fee_model: FeeModel,
        risk_manager: RiskManager,
        initial_capital: Decimal,
    ): ...

    async def run(start, end) -> BacktestResult: ...

class SlippageModel(Protocol):
    def calculate(intent: OrderIntent, orderbook: OrderBook) -> Decimal: ...

class FeeModel(Protocol):
    def maker_fee(...) -> Decimal: ...
    def taker_fee(...) -> Decimal: ...
```

### 滑点模型（v1.0 内置）

| 模型 | 公式 |
|---|---|
| **Constant Bps** | slippage = price × bps / 10000 |
| **Volume-aware** | slippage = price × (qty / candle.volume) × factor |
| **Orderbook walk** | 模拟扫单簿（v1.5） |

### 关键算法（伪代码）

```python
async def run(self, start, end):
    candles = self.data_provider.fetch_ohlcv(start, end)
    portfolio = Portfolio(self.initial_capital)
    trades = []

    for candle in candles:
        intent = await self.strategy.on_tick(ctx, candle)
        if intent is None:
            continue

        if not self.risk_manager.check(intent, portfolio, candle):
            continue

        slippage = self.slippage_model.calculate(intent, candle)
        fee = self.fee_model.calc(intent)

        fill = simulate_fill(intent, candle, slippage)
        portfolio.update(fill, fee)
        trades.append(Trade(intent, fill, fee, ts=candle.ts))

    return BacktestResult(trades, portfolio.equity_curve, metrics(trades))
```

### M2 对齐方法

```
1. 选 1 个简单策略（SMA 20/50 cross BTC/USDT）
2. 同样数据期 / 同样手续费 / 同样滑点
3. AI-Trading 跑 → freqtrade 跑
4. 对比 PNL 总和、交易笔数、单笔 entry/exit 价格
5. 偏差 < 5% 视为通过
6. 文档化所有差异（如 fee 计算精度差异）
```

## 5. 后果

### 正面

- 与 AI-Trading DSL 完全一致（实盘代码即回测代码）
- 完全控制滑点 / 资金管理 / 多策略
- Apache-2.0 友好
- 借鉴 jesse 设计成熟度高

### 负面

- 工作量 ~2 周
- 需 M2 验证一致性（额外 1 周）

### 中性 / 待观察

- v2.0 是否 Rust 化？取决于性能
- 是否引入 vectorbt 用于"快速参数扫描"？v1.5 评估

### 触发的后续工作

- packages/core/backtest/ 实现
- 滑点模型 / 手续费模型 / 风控模型集成
- M2 一致性 Eval 集（vs freqtrade）
- 回测结果可视化（PNL / drawdown / trades 散点图）
- Hyperopt v1（基础参数推荐）；完整 v1.5

## 6. 关联

- 相关 ADR：[ADR-0007 受限 DSL](0007-restricted-python-dsl-with-sandbox.md), [ADR-0006 ClickHouse](0006-clickhouse-for-timeseries.md)
- PRD 章节：[PRD §4.1 F-SE-02](../../prd.md#41-p0--mvp-必备6-个月发布的最小集合), [PRD §8.3 M2](../../prd.md#83-关键里程碑)
- 架构文档：[ADD §08 Tech Stack](../08-tech-stack-rationale.md)
- 详细设计：[SDLC §03-detailed-design/03 backtest-engine](../../implementation/03-detailed-design/03-backtest-engine.md)

## 7. Changelog

| 版本 | 日期 | 变更 | 责任人 |
|------|------|------|--------|
| 1.0 | 2026-05-08 | 初版 | CTO |
