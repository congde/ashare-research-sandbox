# 03/03 · Backtest Engine — 自研事件驱动回测

> 把 [ADR-0009 自研事件驱动回测](../../architecture/adrs/0009-self-built-event-driven-backtest.md) 落地为可与 freqtrade 对齐（PNL < 5%）的 v1.0 引擎。

---

## 1. 概述

事件驱动循环模拟策略在历史数据上的表现，输出 PNL / Sharpe / MDD / trades 等指标 + 可视化 + 自然语言解读。

## 2. 目标

- 1 年 1m 数据 < 60s 完成
- vs freqtrade SMA cross 偏差 < 5%（M2 验收）
- 与 LiveRuntime 复用同一 strategy on_tick 签名
- 内置 3 种滑点模型 + 2 种手续费模型
- 输出可视化 .parquet 报告

## 3. 范围

✅ 现货单交易对 / 多 timeframe / 自定义 fee/slippage / walk-forward 标记
❌ 多交易对组合回测 [v1.5]；orderbook walk 滑点 [v1.5]；衍生品 funding 模拟 [v1.5]

## 4. 关联 ADR / US

- [ADR-0009](../../architecture/adrs/0009-self-built-event-driven-backtest.md), [ADR-0007](../../architecture/adrs/0007-restricted-python-dsl-with-sandbox.md)
- US-AT-022 / 023 / 026 / 027 / 028 / 029 / 030

## 5. 设计要点

### 类图

```
BacktestEngine
  ├── DataProvider (ClickHouse)
  ├── StrategyExecutor (Sandbox)
  ├── SlippageModel (ConstantBps / VolumeAware)
  ├── FeeModel (ConstantBps / TierBased)
  ├── RiskManager (复用)
  ├── Portfolio (cash / positions / equity_curve)
  └── ResultBuilder (metrics + .parquet)
```

### 时序

```
BacktestEngine.run(start, end)
  → load candles from ClickHouse
  → init Portfolio(initial_capital)
  → for each candle:
      → strategy_executor.on_tick(ctx, candle) → OrderIntent | None
      → RiskManager.check → pass / reject
      → simulate_fill(intent, candle, slippage_model)
      → Portfolio.update(fill, fee)
      → trades.append(...)
  → metrics = Metrics.compute(trades, equity_curve)
  → write .parquet to MinIO
  → return BacktestResult
```

## 6. 接口与数据模型

```python
class BacktestEngine:
    def __init__(
        self,
        strategy_code: str,
        data_provider: MarketDataReader,
        slippage_model: SlippageModel,
        fee_model: FeeModel,
        risk_manager: RiskManager,
        initial_capital: Decimal,
    ): ...
    async def run(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> BacktestResult: ...

class BacktestResult(BaseModel):
    backtest_id: UUID
    metrics: BacktestMetrics
    trades: list[Trade]
    equity_curve: list[tuple[datetime, Decimal]]
    s3_report_url: str

class BacktestMetrics(BaseModel):
    period_start: datetime
    period_end: datetime
    total_trades: int
    win_rate: float
    pnl_pct: float
    pnl_usd: Decimal
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown_pct: float
    avg_holding_hours: float
    walk_forward_pass: bool   # 简单期外样本验证
```

## 7. 关键算法

### 主循环（伪代码）

```python
async def run(self, ...):
    candles = await self.data_provider.fetch_ohlcv(symbol, timeframe, start, end)
    portfolio = Portfolio(self.initial_capital)
    trades: list[Trade] = []

    for i, candle in enumerate(candles):
        ctx = StrategyContext(symbol, timeframe, portfolio.position(symbol), candles[:i+1])
        intent = await self.strategy_executor.on_tick(ctx, candle)
        if intent is None:
            portfolio.mark_to_market(candle)
            continue

        if not self.risk_manager.check(intent, portfolio, candle):
            continue

        slippage = self.slippage_model.calculate(intent, candle)
        fee = self.fee_model.calc(intent)
        fill = simulate_fill(intent, candle, slippage)
        portfolio.apply(fill, fee)
        trades.append(Trade.from_fill(intent, fill, fee, ts=candle.ts))

    metrics = Metrics.compute(trades, portfolio.equity_curve)
    s3_url = await self._write_report_parquet(trades, portfolio.equity_curve)
    return BacktestResult(...)
```

### 滑点模型

```python
class ConstantBpsSlippage:
    def __init__(self, bps: float = 5):
        self.bps = bps
    def calculate(self, intent, candle):
        return intent.price * Decimal(self.bps) / Decimal(10000)

class VolumeAwareSlippage:
    def __init__(self, factor: float = 0.5):
        self.factor = factor
    def calculate(self, intent, candle):
        ratio = float(intent.qty) / float(candle.volume)
        return intent.price * Decimal(ratio * self.factor)
```

### 手续费模型

```python
class ConstantBpsFee:
    def __init__(self, maker_bps: float = 10, taker_bps: float = 15):
        self.maker_bps = maker_bps
        self.taker_bps = taker_bps
    def calc(self, intent):
        bps = self.maker_bps if intent.type == "limit" else self.taker_bps
        return intent.qty * intent.price * Decimal(bps) / Decimal(10000)
```

### Walk-forward 简单实现

```python
def walk_forward_check(trades: list[Trade], split_ratio: float = 0.7):
    cutoff = int(len(trades) * split_ratio)
    in_sample_pnl = sum(t.pnl for t in trades[:cutoff])
    out_sample_pnl = sum(t.pnl for t in trades[cutoff:])
    # 期外不能完全反向
    return out_sample_pnl > 0 and out_sample_pnl > in_sample_pnl * -0.5
```

## 8. 配置与环境变量

```bash
BACKTEST_DEFAULT_FEE_MAKER_BPS=10
BACKTEST_DEFAULT_FEE_TAKER_BPS=15
BACKTEST_DEFAULT_SLIPPAGE_BPS=5
BACKTEST_REPORT_BUCKET=s3://ai-trading-reports
BACKTEST_PARALLELISM=4   # 同时跑的回测数
```

## 9. 异常路径与降级

| 故障 | 处理 |
|---|---|
| 数据缺口 > 5% | 拒绝运行 + 提示用户回填 |
| Strategy 抛异常 | 标记该 candle skip + 记录 + 继续 |
| Sandbox 超时 | 终止该回测 + 告警 |
| Portfolio 余额负 | 拒绝 fill + 标记错误 |
| OOM | 限制 candles 批次大小 |

## 10. 测试清单

| 类型 | 用例 |
|---|---|
| **单元** | 滑点 / 手续费 / Portfolio update / Metrics 公式 |
| **集成** | 简单 SMA cross 跑通 + 输出 BacktestResult |
| **一致性 Eval（M2）** | vs freqtrade SMA cross BTC/USDT 1y → PNL 偏差 < 5% |
| **抗 lookahead bias** | 验证策略只能看到当前及之前 candle |
| **性能** | 1y BTC 1m < 60s（单线程） |

## 11. 监控埋点

- `backtest_run_total{status}` Counter
- `backtest_duration_s{symbol, timeframe}` Histogram
- `backtest_candles_processed_total` Counter
- `backtest_trades_per_run` Histogram

## 12. 安全与合规

- 跑在 Sandbox（与实盘相同）
- 不允许策略代码访问 ClickHouse 直连（必经 ctx.fetch_ohlcv API）
- 报告 .parquet 写 MinIO 时按 user_id 分桶 + RLS

## 13. Open Questions

- v1.5 是否引入 vectorbt 用于"参数扫描快查"（事件驱动用于精确）？
- v2.0 Rust 化主循环（当前估计 5-10x 加速）？

## 14. Changelog

| 版本 | 日期 | 变更 | 责任人 |
|------|------|------|--------|
| v1.0 | 2026-05-08 | 初版 | 量化 owner |
