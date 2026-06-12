# 03/07 · Risk Agent — 风控守护者

> 把 [ADR-0008 Risk Agent 独立](../../architecture/adrs/0008-risk-agent-independent.md) 落地为常驻巡检 + 事件驱动 + 5 条 MVP 风控规则。

---

## 1. 概述

Risk Agent（角色 = risk_guardian）独立于 Strategy Agent，通过 trigger_daemon 每秒巡检 + on_event 事件驱动，监控所有用户的实盘策略持仓 / PNL / 异常并产出干预提案。

## 2. 目标

- 实盘期间双重保险（Strategy 单点失效不影响熔断）
- 5 条 MVP 风控规则全覆盖
- 用户接受率 > 80%（合理的提案）
- LLM 仅 critical/high 才调（成本控制）

## 3. 范围

✅ 持仓上限 / 单日最大损失 / 滑点上限 / 异常订单簿 / 紧急熔断 5 条
❌ ML 风控模型 [v1.5] / 用户自定义 Python 风控 [v2.0]

## 4. 关联 ADR / US

- [ADR-0008 Risk Agent 独立](../../architecture/adrs/0008-risk-agent-independent.md), [ADR-0007](../../architecture/adrs/0007-restricted-python-dsl-with-sandbox.md)
- US-AT-039 ~ 044, 048

## 5. 设计要点

### Agent 注册

```python
{
    "id": "ai-trading.risk_guardian",
    "role": "risk_guardian",
    "primary_skill": "risk_monitoring_skill",
    "model_route": "risk-guardian",   # Sonnet（速度优先）
    "tools": [
        "query_position",
        "query_pnl_24h",
        "query_orderbook",
        "check_risk_rules",
        "create_approval_request",
        "send_notification",
    ],
    "max_loop_iterations": 4,
    "budget_per_run_usd": 0.01,   # 大量调用 → 严控
}
```

### 触发机制（双轨）

```
轨 1：TriggerDaemon 巡检（复用 WorkDAO core/scheduling）
  - kind: interval, interval_seconds: 1
  - tool_call: scan_all_positions

轨 2：on_event 事件驱动
  - on_event("order.submitted") → fast_check
  - on_event("trade.filled") → recalc_position_risk
  - on_event("market.abnormal_orderbook") → critical_check
```

### 5 条 MVP 风控规则

| 级别 | 规则 | 触发动作 |
|---|---|---|
| 告警 | 单策略持仓 > 账户 30% | LLM 解释 + Telegram |
| 告警 | 单交易对滑点 > 1% | 拒绝当次下单 + 告警 |
| 提案 + 审批 | 单日 PNL < -5% | ApprovalRequest（暂停所有策略） |
| 提案 + 审批 | 异常订单簿（流动性枯竭 / 极端报价） | ApprovalRequest（拒绝下单） |
| 自动执行（用户预授权） | 单日 PNL < -10% | 自动平仓所有持仓 + 强制告警 |

## 6. 接口与数据模型

```python
class RiskRule(BaseModel):
    id: UUID
    user_id: UUID
    scope: Literal["global", "account", "strategy"]
    kind: str   # 见上表
    threshold: dict
    action: Literal["alert", "propose", "auto_halt"]
    active: bool

class RiskEvent(BaseModel):
    id: UUID
    user_id: UUID
    rule_id: UUID
    severity: Literal["critical", "high", "medium", "low"]
    trigger: str
    context: dict
    explanation_llm: str | None
    proposal: dict | None
    approval_request_id: UUID | None
    created_at: datetime

class CheckRiskRulesIn(BaseModel):
    user_id: UUID
    strategy_run_id: UUID | None = None

class CheckRiskRulesOut(BaseModel):
    triggered_rules: list[RuleResult]
    requires_action: bool
```

## 7. 关键算法

### 巡检主循环（TriggerDaemon）

```python
async def scan_all_positions():
    active_runs = await get_active_strategy_runs()   # 全平台
    for run in active_runs:
        portfolio = await get_portfolio(run.exchange_account_id)
        rules = await get_active_rules(run.user_id)

        for rule in rules:
            triggered, ctx = check_rule(rule, portfolio, run)
            if not triggered:
                continue

            severity = classify_severity(rule, ctx)
            if severity in ("critical", "high"):
                explanation = await call_llm_explain(rule, ctx)  # Sonnet
            else:
                explanation = render_template(rule, ctx)        # 模板节省成本

            event = await create_risk_event(
                user_id=run.user_id, rule_id=rule.id,
                severity=severity, context=ctx,
                explanation=explanation,
            )

            if rule.action == "alert":
                await send_notification(user_id=run.user_id, event=event)
            elif rule.action == "propose":
                ar = await create_approval_request(
                    kind="halt_all" if severity == "critical" else "review",
                    payload={"event_id": event.id},
                    deadline_minutes=15,
                )
            elif rule.action == "auto_halt" and user_preauthorized(run.user_id):
                await emergency_halt(run.exchange_account_id)
                await send_notification(... severity="critical")
```

### LLM 解释（Sonnet）

```
prompt:
You are Risk Guardian. The following risk rule has been triggered:
  Rule: {rule.kind}
  Threshold: {rule.threshold}
  Current state: {ctx}

Explain in natural language WHY this is risky and propose:
  1. Recommended action (halt / review / continue with caution)
  2. Rationale
  3. 2-3 alternatives

Format: JSON matching schema {...}
```

## 8. 配置与环境变量

```bash
RISK_AGENT_ENABLED=true
RISK_AGENT_TRIGGER_INTERVAL_S=1
RISK_AGENT_LLM_MODEL=anthropic/claude-sonnet-4.6
RISK_AGENT_LLM_BUDGET_PER_DAY_USD=2.0   # 全平台共享
RISK_AGENT_ALERT_TEMPLATE_PATH=./templates/risk_alerts/

# 用户预授权
RISK_AUTO_HALT_DAILY_LOSS_PCT=10.0   # 默认值，用户可调
```

## 9. 异常路径与降级

| 故障 | 处理 |
|---|---|
| TriggerDaemon 崩溃 | systemd restart + Redis lock 防双跑 |
| LLM 限流 | 退化到模板解释 + 日志告警 |
| Approval 创建失败 | 重试 3 次 + 退化为强制告警 |
| 单条规则计算抛异常 | 跳过该规则 + audit log + 继续其他 |

## 10. 测试清单

| 类型 | 用例 |
|---|---|
| **单元** | 5 条规则各自的 check 函数 |
| **集成** | 模拟仓位 → 触发规则 → 创建 RiskEvent + ApprovalRequest |
| **Eval** | 20 个历史"应该熔断"场景 → 真实触发率 ≥ 95% |
| **Eval** | 20 个"误熔断"场景 → 误报率 ≤ 10% |
| **Chaos** | TriggerDaemon kill 后双实例不重复触发 |

## 11. 监控埋点

- `risk_agent_scan_total` Counter
- `risk_agent_scan_duration_ms` Histogram
- `risk_event_total{severity, rule_kind}` Counter
- `risk_proposal_approved_total` Counter
- `risk_proposal_rejected_total` Counter（用户拒绝率）
- `risk_auto_halt_total` Counter（critical 自动熔断）
- `risk_agent_llm_cost_usd_total` Counter

## 12. 安全与合规

- 自动熔断仅在用户预授权下触发（默认关）
- 所有 RiskEvent 写 audit_log（不可篡改）
- 平台 admin 仅审计权限，无业务操作权
- LLM 解释包含完整 ctx 输入，便于后续审计

## 13. Open Questions

- v1.5 引入 ML 风控模型（异常检测）？
- 是否允许用户自定义 Python 风控规则（受限 DSL）？

## 14. Changelog

| 版本 | 日期 | 变更 | 责任人 |
|------|------|------|--------|
| v1.0 | 2026-05-08 | 初版 | AI 工程 + 安全 |
