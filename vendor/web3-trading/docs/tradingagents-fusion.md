# TradingAgents 与本服务融合说明

本页说明 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 多智能体图在 `ai-web3-trading-agent` 中的挂接方式、数据域、配置与回退。

## 行为概览

### 1. DeepThink 入口（SSE 聊天流）

- **入口**：`DeepThinkAgent` 在「需要工具」的 plan 模式（`use_plan_mode`）下，若 `use_trading_agents: true`，优先尝试走 TradingAgents；成功则写 `trading_agents_completed` 并**跳过**原有 MCP 工具 DAG（见 [src/agent/deep_think.py](src/agent/deep_think.py)）。
- **回退**：以下任一情况走原有 [DAG 流程](src/agent/dag_execution.py)：`use_trading_agents: false`、未安装 `tradingagents` 包、无法从问句解析主交易符号（见 `resolve_ticker_from_query`）、`trading_agents_allowed_intents` 白名单不通过、或图执行抛错。

### 2. LLM 信号分析入口（Dashboard API）

- **入口**：`/dashboard/llm-signal-analysis` 端点新增 `use_trading_agents` 参数（默认 `true`）。
- **流程**：后台异步任务中，TradingAgents 多智能体辩论图与市场数据（K线、链上、新闻、ValueScan）**并行**拉取。TA 辩论结果作为第六维数据注入 LLM 上下文。
- **桥接层**：[ta_signal_bridge.py](src/web/api/ta_signal_bridge.py) 负责调用 `run_propagate_sync`、格式化 TA 输出为 LLM 可读文本、提取信号 hints。
- **回退**：TA 不可用或超时时，信号分析正常进行（仅缺少 TA 维度数据）。

## 数据面

- `trading_agents_data_source: all`（推荐）或 `kucoin`：使用项目内 [default_registry](src/agent/tools/registry.py) 的 `valueScan_api` / `kucoin_openapi_public`，由 [KucoinTradingAgentsGraph](src/agent/trading_agents/crypto_graph.py) 替换上游 ToolNode，**不**依赖 Yahoo/yfinance 作为事实源。`all` 在 [crypto_ta_tools](src/agent/trading_agents/crypto_ta_tools.py) 各工具内追加更多 ValueScan operation（如 `support_resistance`、`kline`、`whale_cost`、多类 `ai_messages`、`large_transactions` 等）；`kucoin` 为同一路径的精简子集、调用更省。
- `trading_agents_data_source: upstream`：使用上游 `TradingAgentsGraph` 原生的 yfinance 等工具，适用于对照与联调，生产请谨慎评估与产品域是否一致。

## 主要配置项（`conf/default.yaml` 或 Apollo）

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `use_trading_agents` | bool | `false` | 是否启用 TradingAgents 多智能体图 |
| `trading_agents_data_source` | str | `kucoin` | `kucoin` / `all` / `upstream` |
| `trading_agents_max_debate_rounds` | int | 上游默认 | 多空辩论轮次上限 |
| `trading_agents_max_risk_discuss_rounds` | int | 上游默认 | 风控讨论轮次上限 |
| `trading_agents_selected_analysts` | list | `["market","social","news"]` | 启用的分析师子集 |
| `trading_agents_allowed_intents` | list | `[]` | 白名单 intent（空=不做 intent 过滤） |
| `trading_agents_trace_llm` | bool | `true` | 是否记录 TA 内部 LLM 链日志 |

## 架构图

```
                          ┌─────────────────────────────────┐
                          │    /dashboard/llm-signal-analysis│
                          │         (dashboard_api.py)       │
                          └──────────┬──────────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
            ┌───────▼──────┐  ┌─────▼─────┐  ┌──────▼───────┐
            │ Market Data  │  │ ValueScan │  │ TradingAgents│
            │ K-line/News  │  │  Onchain  │  │ Debate Graph │
            │  (parallel)  │  │ (parallel)│  │  (parallel)  │
            └───────┬──────┘  └─────┬─────┘  └──────┬───────┘
                    │                │                │
                    └────────────────┼────────────────┘
                                     │
                          ┌──────────▼──────────┐
                          │  ta_signal_bridge.py │
                          │  (format TA → text)  │
                          └──────────┬──────────┘
                                     │
                          ┌──────────▼──────────┐
                          │ llm_signal_analyzer  │
                          │ (6-dim LLM context)  │
                          │ + system prompt with  │
                          │ TA debate discipline  │
                          └──────────┬──────────┘
                                     │
                          ┌──────────▼──────────┐
                          │   SignalOutput       │
                          │ + tradingAgentsDebate│
                          │   block              │
                          └─────────────────────┘
```

## LLM 信号分析中的 TA 集成细节

### 数据流

1. `dashboard_api.py` 的 `_run_llm_signal_task` 并行启动 6 个数据拉取任务：
   - 新闻、链上、链上指标、K线、ValueScan、**TradingAgents**
2. `ta_signal_bridge.py` 的 `run_trading_agents_for_signal()` 调用 `compat.run_propagate_sync()`，在线程中运行 LangGraph 图。
3. TA 结果结构化后注入 `aggregated["tradingAgents"]`。
4. `llm_signal_analyzer.py` 的 `_fmt_trading_agents()` 将 TA 数据格式化为 LLM 可读文本。
5. LLM system prompt 包含专门的「TradingAgents 辩论数据使用纪律」。
6. `_enrich_result()` 将 TA 数据填充到 `SignalOutput.tradingAgentsDebate` 块。

### LLM 使用纪律

- TA 最终决策作为「高权重参考」，非直接采纳
- 与 K 线价格行为交叉验证：一致则提高置信度 5-10 分，冲突则以 K 线为主
- 多头/空头分析师辩论需综合双方论点
- 风控经理评估直接纳入 risks 分析
- 交易员价位参考需与技术面和 ValueScan 交叉验证

### 输出结构

`SignalOutput` 新增 `tradingAgentsDebate` 字段（`TradingAgentsDebateBlock`）：

| 字段 | 说明 |
|------|------|
| `available` | TA 是否已执行 |
| `dataSource` | 数据来源模式 |
| `latencyMs` | TA 图执行耗时 |
| `marketSummary` | 市场分析师摘要 |
| `sentimentSummary` | 情绪分析师摘要 |
| `newsSummary` | 新闻分析师摘要 |
| `fundamentalsSummary` | 基本面分析师摘要 |
| `bullArgument` | 多头分析师论点 |
| `bearArgument` | 空头分析师论点 |
| `riskAssessment` | 风控经理评估 |
| `traderPlan` | 交易员投资计划 |
| `finalDecision` | 最终交易决策 |

### API 用法

```bash
# 启用 TradingAgents 辩论（默认）
GET /dashboard/llm-signal-analysis?symbol=BTC&use_trading_agents=true

# 禁用 TradingAgents（仅用 5 维数据）
GET /dashboard/llm-signal-analysis?symbol=BTC&use_trading_agents=false

# 轮询结果
GET /dashboard/llm-signal-analysis/poll?taskId=xxx
```

## 文件清单

| 文件 | 职责 |
|------|------|
| `src/agent/trading_agents/__init__.py` | 包入口，导出可用性检测 |
| `src/agent/trading_agents/compat.py` | 依赖检测、配置合并、Yahoo 符号、执行入口 |
| `src/agent/trading_agents/crypto_graph.py` | KucoinTradingAgentsGraph 子类 |
| `src/agent/trading_agents/crypto_ta_tools.py` | LangChain 工具（KuCoin/ValueScan 数据） |
| `src/agent/trading_agents/pipeline.py` | DeepThink SSE 流式集成 |
| `src/web/api/ta_signal_bridge.py` | **新增** — TA ↔ LLM 信号桥接层 |
| `src/web/api/signal_schema.py` | **更新** — 新增 `TradingAgentsDebateBlock` |
| `src/web/api/llm_signal_analyzer.py` | **更新** — TA 上下文格式化、数据质量、系统提示词 |
| `src/web/api/dashboard_api.py` | **更新** — `use_trading_agents` 参数、并行 TA 拉取 |