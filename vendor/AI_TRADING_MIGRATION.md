# ai-trading 迁移清单

`vendor/ai-trading/` 是只读上游对照。可运行代码只进入仓库根目录 `src/`。
下表按 **第一版教学边界**（固定离线样本、不连接交易所、不下单）评估。

## 已迁入 `src/`

| 上游路径 | 本地路径 | 状态 |
|---|---|---|
| `app/strategy_engine/dsl/` | `src/strategy_engine/dsl/` | 已适配：safelist、validator、lookahead、loader |
| `app/strategy_engine/backtest/engine.py` | `src/strategy_engine/backtest/engine.py` | 已适配：事件驱动循环 |
| `app/strategy_engine/backtest/portfolio.py` | `src/strategy_engine/backtest/portfolio.py` | 已复制并去依赖 |
| `app/strategy_engine/backtest/models.py` | `src/strategy_engine/backtest/models.py` | 已复制；教学版默认 ZeroFee/ZeroSlippage |
| `app/domain/market_data/models.py`（Candle） | `src/strategy_engine/backtest/candles.py` | 已收窄为教学 Candle |
| `app/connectors/protocol.py`（OrderIntent 等） | `src/strategy_engine/backtest/protocol.py` | 已收窄 |
| `app/strategy_engine/runtime/risk_manager.py` | `src/risk/simulation.py` | 已适配为**回测后**模拟门，非实时拦截 |
| MA 交叉思路 | `src/strategy_engine/strategies/ma_crossover.py` | 已实现 `on_tick` 策略 |

## 建议下一批迁入（仍符合教学边界）

| 上游路径 | 建议本地路径 | 价值 | 前置条件 |
|---|---|---|---|
| `app/strategy_engine/dsl/loader.py` | 已有；需**接线** | 把校验通过的 DSL 编译成 `on_tick` 并接入引擎 | 完成 `compile_strategy` → `BacktestEngine` 路径 |
| `app/strategy_engine/backtest/candles.py` | `src/strategy_engine/backtest/candles_utils.py` | K 线校验、重采样，防脏数据进回测 | 只依赖 stdlib / 本地 Candle |
| `app/strategy_engine/backtest/walk_forward.py` | `src/strategy_engine/backtest/walk_forward.py` | 样本外窗口验证，教「不能只看一段行情」 | 固定 CSV 第二段样本或切分规则 |
| `app/services/backtest_service.py`（编排层） | `src/backtest/service.py` | 统一「加载策略 → 跑引擎 → 出报告」 | 去掉 DB / MinIO / 外部 API |
| `app/strategy_engine/backtest/result_builder.py`（Parquet 部分可选） | `src/backtest/artifacts.py` | 结构化导出 trades / equity | 第一版可继续 JSON，Parquet 可选 |

## 暂留 `vendor/`，不进入第一版

| 上游模块 | 原因 |
|---|---|
| `app/strategy_engine/runtime/*`（runner、runtime、order router） | 实时交易与交易所连接，超出 PRD |
| `app/connectors/ws_aggregator.py` | 需要实时行情与 WebSocket |
| `app/services/research_agent.py`、`strategy_architect_*` | 依赖 LLM / 外部 Agent 编排 |
| `app/services/strategy_research_adapter.py` | 生产研究流水线，非固定样本 MVP |
| `web/` React Quant Atelier | 完整前端栈；当前教学页在 `src/web/static/` |
| `result_builder.py` 的 MinIO/S3 上传 | 需要对象存储与 pyarrow 运行时依赖 |

## 迁移顺序（推荐）

1. **DSL 接线**：`validate_strategy_code` → `compile_strategy` → `BacktestEngine`
2. **K 线工具**：`validate_candles` / `resample_candles` 接入 `src/backtest/runner.py`
3. **Walk-forward**：固定双样本或时间切分 + 报告字段
4. **编排层**：从 `backtest_service` 提取纯函数服务，替换 `runner.py` 里零散调用
5. **前端（可选）**：从 `vendor/ai-trading/web` 挑 Backtests 面板，对接 `/api/report`

## 验收

每迁入一块，应满足：

- 代码位于 `src/`，不直接 `import vendor.ai_trading`
- `py scripts/course.py check` 或 `python verify.py` 通过
- 新行为有 `tests/` 覆盖，且仍显示「不构成投资建议 / 不能执行交易」
