# ADR-0008：Risk Agent 独立于 Strategy Agent（双重保险）

**状态**：accepted
**日期**：2026-05-08
**决策者**：CTO + 产品负责人 + 安全负责人

---

## 1. 背景与问题

PRD §3.2 / §6.3 规定 Risk Agent 在实盘运行期间，**独立于策略代码**监控所有策略的风险敞口并主动干预。

但实现上面临一个选型问题：

- **方案合并**：把 Risk 功能内嵌到 Strategy Agent 内部（每次 on_tick 调用 Risk 校验）
- **方案分离**：Risk Agent 是独立的 AgentInstance + 独立 trigger，物理隔离

如何选？

## 2. 决策驱动力

- **PRD §10.4**：明确要求"AI 错误提议导致用户决策偏差 → 风控引擎全局兜底"
- **PRD §10.1**：LLM 生成错误代码导致资金损失风险 = 极高
- **WorkDAO 已有基础**：`core/scheduling/trigger_daemon.py` + `domain/approval` 直接可用
- **金融领域常识**：交易系统的"风控"和"策略"必须物理隔离（防止策略 bug / LLM 幻觉同时摧毁两者）
- **可观测性**：独立 Agent 便于单独追踪 / 监控 / 审计

## 3. 候选方案

### 方案 A：合并入 Strategy Agent（每次 on_tick 内联 Risk 校验）
- 优点：实现简单 / 调用链短
- 缺点：
  - Strategy 崩溃 / 死循环 / 模型幻觉同时摧毁 Risk
  - LLM 改写 Strategy 时可能"忘记"调 Risk（设计陷阱）
  - 难以单独审计 / 限速 / 升级
- 推荐度：⭐

### 方案 B：Risk 是 RiskManager 类（同进程，但与 Strategy 解耦）
- 优点：实现中等 / 性能高
- 缺点：仍然在同进程；Strategy 崩溃时 Risk 也挂
- 推荐度：⭐⭐⭐

### 方案 C（推荐）：Risk Agent = 独立 AgentInstance + 独立 trigger + 独立 LLM 实例
- 优点：
  - 物理隔离（双重保险）
  - 独立审计 + 独立速率 + 独立升级
  - 复用 WorkDAO trigger_daemon + approval（零开发）
  - 异常熔断不依赖 Strategy 健康
- 缺点：实现稍复杂；多一组进程 / 内存开销
- 推荐度：⭐⭐⭐⭐⭐

## 4. 选定方案

**方案 C：Risk Agent 独立于 Strategy Agent**

### 实现结构

```
┌─────────────────────────────────────────────────────────┐
│  Strategy Agent（特化 AgentInstance）                    │
│  角色 = strategy_architect                              │
│  绑定 SKILL: strategy_generation_skill                  │
│  Tool: validate_code / run_backtest / fetch_data        │
│  调用频率: 用户对话触发                                  │
└─────────────────────────────────────────────────────────┘

                                    并行 + 物理隔离

┌─────────────────────────────────────────────────────────┐
│  Risk Agent（特化 AgentInstance）                        │
│  角色 = risk_guardian                                   │
│  绑定 SKILL: risk_monitoring_skill                      │
│  Tool: query_position / check_risk_rules / trigger_halt │
│  调用频率: trigger_daemon 每秒巡检 + 事件驱动           │
└─────────────────────────────────────────────────────────┘
                       │
                       ├── 异常 → Approval Service
                       │       └── 用户审批 → 自动平仓 / 告警
                       │
                       └── 紧急 → 熔断 + Telegram 推送
```

### 触发机制

```python
# 复用 WorkDAO core/scheduling/trigger_daemon.py
# 在 risk_agent 角色下注册一个常驻 trigger
{
    "trigger_id": "risk_agent_main",
    "kind": "interval",
    "interval_seconds": 1,        # 每秒巡检
    "agent_role": "risk_guardian",
    "tool_call": "scan_all_positions",
    "active": True,
}

# 事件驱动补充（OrderRouter 提交订单时同步通知）
on_event("order.submitted", lambda e: risk_agent.fast_check(e))
```

### 4 级风控规则（MVP 5 条核心）

| 级别 | 规则 | 触发动作 |
|---|---|---|
| **告警（默认）** | 单策略持仓 > 账户 30% | LLM 解释原因 + Telegram |
| **告警** | 单交易对滑点 > 1% | 拒绝当次下单 + 告警 |
| **提案 + 审批** | 单日 PNL < -5% | ApprovalRequest（暂停所有策略） |
| **提案 + 审批** | 异常订单簿（流动性枯竭 / 极端报价） | ApprovalRequest（拒绝下单） |
| **自动执行（用户预授权）** | 单日 PNL < -10% | 自动平仓所有持仓 + 强制告警 |

### Risk Agent 输出结构

```json
{
  "risk_event_id": "uuid",
  "severity": "critical | high | medium | low",
  "trigger": "single_day_loss > 5%",
  "context": {
    "current_pnl_24h": -0.082,
    "affected_strategies": ["GridBTC", "DCAETH"],
    "position_summary": {...}
  },
  "explanation": "策略 GridBTC 触发熔断：BTC 在过去 1 小时下跌 8% 突破网格下沿。",
  "proposal": {
    "action": "halt_all_strategies",
    "rationale": "防止网格下沿继续亏损叠加",
    "alternatives": [
      {"action": "调整网格区间到 16k-22k", "expected_outcome": "..."},
      {"action": "等待企稳 2h 后人工评估", "expected_outcome": "..."}
    ]
  },
  "approval_required": true,
  "approver": "user@example.com",
  "deadline_minutes": 15
}
```

## 5. 后果

### 正面

- **双重保险**：Strategy bug / LLM 幻觉不影响 Risk Agent
- **独立审计**：所有 Risk 决策可追溯到 Risk Agent，与 Strategy 决策物理分开
- **便于演进**：v1.5 引入 ML 风控模型时仅升级 Risk Agent，不动 Strategy
- **复用 WorkDAO**：trigger_daemon + approval 零开发

### 负面

- 多一组进程（Risk Agent 运行时）
- LLM token 多一份成本（每次告警都生成解释）
  - 缓解：仅 critical / high 级别调 LLM；low / medium 用模板

### 中性 / 待观察

- v1.5 Risk Agent 是否需要专属小模型（vs Claude Opus）？取决于 token 成本
- v2.0 是否引入"用户自定义 Python 风控规则"？需新 ADR

### 触发的后续工作

- 新建 `domain/risk_rule/`（5 条 MVP 规则）
- 新建 `services/risk_engine/`（轻量规则引擎，挂在 trigger + approval 上）
- Risk Agent SKILL.md（定义角色 + tool 注册）
- Approval 模板：`risk_halt_request` / `risk_threshold_change`
- 监控 dashboard：Risk Agent 决策准确率（用户接受 vs 拒绝比例）

## 6. 关联

- 相关 ADR：[ADR-0001](0001-fork-workdao-baseline.md), [ADR-0007](0007-restricted-python-dsl-with-sandbox.md)
- PRD 章节：[PRD §3.2 三层 Agent](../../prd.md#32-三层-agent-架构核心创新), [PRD §6.3 Risk Agent](../../prd.md#63-risk-agent-风控守护者)
- 架构文档：[ADD §03 Multi-Agent Collaboration](../03-multi-agent-collaboration.md)
- 复用评估：[workdao-reuse-assessment.md §8 风险管控](../../workdao-reuse-assessment.md#8-风险管控risk-agent实现路径)

## 7. Changelog

| 版本 | 日期 | 变更 | 责任人 |
|------|------|------|--------|
| 1.0 | 2026-05-08 | 初版 | CTO |
