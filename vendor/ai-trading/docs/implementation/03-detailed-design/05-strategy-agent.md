# 03/05 · Strategy Agent — 策略架构师

> 把 [ADD §03 Multi-Agent](../../architecture/03-multi-agent-collaboration.md) 中的 Strategy Agent 设计落地为 SKILL.md + Tools + Prompt 模板。

---

## 1. 概述

Strategy Agent（角色 = strategy_architect）将用户自然语言描述转换为：受限 Python 策略代码 + 结构化策略卡片 + 自动回测验证 + 自然语言解读。

## 2. 目标

- 用户可运行率 > 80%
- 单次会话总成本（含 1 次回测）< $0.05
- 多轮对话 ≤ 5 轮收敛
- 完整覆盖 PRD §3.3 自然语言 → 可执行策略 工作流
- 端到端 P95 < 30s

## 3. 范围

✅ 现货单交易对策略；技术分析（SMA / RSI / Bollinger / MACD 等）；网格 / DCA / 趋势 / 突破
❌ 多交易对组合 [v1.5]；机器学习策略（需 GPU）[v2]；MEV / sandwich

## 4. 关联 ADR / US

- [ADR-0004 LiteLLM](../../architecture/adrs/0004-litellm-as-llm-abstraction.md), [ADR-0007 受限 DSL](../../architecture/adrs/0007-restricted-python-dsl-with-sandbox.md), [ADR-0008 Risk 独立](../../architecture/adrs/0008-risk-agent-independent.md)
- US-AT-011 ~ 020, 022, 024, 029

## 5. 设计要点

### Agent 注册

```python
# packages/ai/seeds/strategy_architect.py
{
    "id": "ai-trading.strategy_architect",
    "role": "strategy_architect",
    "name": "Strategy Architect",
    "description": "把用户自然语言描述转化为可运行的 Python 策略 + 卡片",
    "primary_skill": "strategy_generation_skill",
    "model_route": "strategy-architect-primary",
    "fallback_models": ["strategy-architect-fallback"],
    "tools": [
        "validate_strategy_code",
        "run_backtest",
        "fetch_historical_data",
        "summarize_metrics",
    ],
    "max_loop_iterations": 8,
    "budget_per_run_usd": 0.10,
}
```

### SKILL.md 三级渐进加载（复用 WorkDAO domain/skill）

```
strategy_generation_skill/
├── Level1.md          # 描述（Agent 加载时一定读）
├── Level2-instructions.md  # 完整指令（必要时加载）
├── Level3-examples/   # 示例（按需）
│   ├── grid_btc.py
│   ├── dca_eth.py
│   ├── sma_cross.py
│   └── bollinger_breakout.py
└── Level3-prompts/    # 模板（按需）
    ├── system_prompt.txt
    ├── refinement_prompt.txt
    └── card_schema.json
```

### Tool 实现路径

```
tools/validate_strategy_code  → packages/strategy_engine/dsl/validator.py
tools/run_backtest            → packages/strategy_engine/backtest/engine.py
tools/fetch_historical_data   → packages/connectors/market_data_reader.py
tools/summarize_metrics       → packages/ai/tools/summarize.py
```

## 6. 接口与数据模型

```python
class StrategyAgentRequest(BaseModel):
    user_id: UUID
    conversation_id: UUID
    user_message: str
    parent_run_id: UUID | None = None

class StrategyAgentResponse(BaseModel):
    run_id: UUID
    strategy_code: str | None
    strategy_card: StrategyCard | None
    backtest_summary: BacktestMetrics | None
    explanation_natural_language: str
    follow_up_question: str | None  # 多轮追问
    audit_meta: dict

class StrategyCard(BaseModel):
    name: str
    version: str
    thesis: str
    valid_when: list[str]
    invalid_when: list[str]
    expected_metrics: dict
    risk_checklist: list[str]
```

## 7. 关键 Prompt 模板

### system_prompt.txt（节选）

```
You are Strategy Architect, an AI Co-pilot for crypto quantitative trading.
You generate restricted Python strategies (DSL) and structured strategy cards.

# Hard Rules
1. NEVER suggest "always profitable" or "guaranteed return".
2. NEVER use os, sys, subprocess, socket, urllib, requests, eval, exec, compile, __import__.
3. ALWAYS use the platform SDK: ai_trading.api.fetch_ohlcv / position / order_intent / log
4. The function signature MUST be: def on_tick(ctx, candle) -> Action | None
5. Output strategy_card MUST contain: name, thesis, valid_when, invalid_when, expected_metrics

# Available libraries
pandas, numpy, talib, decimal, math, statistics, datetime, typing, dataclasses, json
ai_trading.api  (fetch_ohlcv, fetch_ticker, position, order_intent, log)

# Multi-turn workflow
1. Parse user intent
2. Ask clarifying questions if parameters missing
3. Generate strategy code (use Level3-examples as reference)
4. Call validate_strategy_code
5. Call run_backtest
6. Generate strategy_card with expected_metrics from backtest
7. Provide natural language explanation
```

### refinement_prompt.txt（用户要求微调）

```
Given the previous strategy code and backtest result, the user wants to {refinement}.
Maintain the same on_tick signature. Modify minimal lines.
Re-run validate + backtest. Explain the change.
```

## 8. 多轮对话状态机

```
state: NEW → CLARIFYING → GENERATING → BACKTESTING → REFINING → DONE | FAILED
                  ↑                                       │
                  └───────────────────────────────────────┘ (用户要求改)
```

## 9. 配置与环境变量

```bash
STRATEGY_AGENT_MODEL_PRIMARY=anthropic/claude-opus-4.7
STRATEGY_AGENT_MODEL_FALLBACK=anthropic/claude-sonnet-4.6
STRATEGY_AGENT_MAX_TOKENS=8192
STRATEGY_AGENT_TEMPERATURE=0.3
STRATEGY_AGENT_BUDGET_USD=0.10
STRATEGY_AGENT_MAX_TURNS=5
```

## 10. 异常路径与降级

| 故障 | 处理 |
|---|---|
| LLM 主路由 5xx | LiteLLM fallback to Sonnet |
| validate fail | 重试生成 1 次 + 详细错误 |
| backtest fail | 跳过 + 通知用户 |
| 输出 schema 不合规 | 重试 2 次 + 标错误 |
| 用户预算超限 | 阻断 + 提示升级 |

## 11. 测试清单

| 类型 | 用例 |
|---|---|
| **单元** | Tool registry / SKILL 加载 / Prompt 渲染 |
| **集成** | 跑通"BTC 网格"端到端 |
| **Eval（基础）** | 50 个常见策略描述 → 可运行率 > 80% |
| **Eval（复杂）** | 30 个多 timeframe / 自定义指标 |
| **Eval（抗幻觉）** | 20 个故意诱导 `import os` / `eval()` → 必拒 |

## 12. 监控埋点

- `strategy_agent_runs_total{status, model}` Counter
- `strategy_agent_duration_s` Histogram
- `strategy_agent_tokens{direction}` Histogram
- `strategy_agent_cost_usd_total{user_id}` Counter
- `strategy_agent_validate_fail_total{reason}` Counter
- `strategy_agent_backtest_fail_total` Counter

## 13. 安全与合规

- 所有调用经 Tool Gate（详见 [ADD §03.6](../../architecture/03-multi-agent-collaboration.md#36-tool-gate-与-acl安全核心)）
- LLM 输出策略代码必经 validator
- audit_log 每次决策快照（含 prompt / 输出 / token / 成本）
- 用户每日预算阻断 + 通知

## 14. Open Questions

- v1.5 引入"金融领域微调"模型？取决于成本 / 准确率
- 是否允许策略 fork 公开模板？（v1.5 策略市集）

## 15. Changelog

| 版本 | 日期 | 变更 | 责任人 |
|------|------|------|--------|
| v1.0 | 2026-05-08 | 初版 | AI 工程 |
