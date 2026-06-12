# KuCoin「AI 带单员」技术方案（CTO 汇报版）

> **版本**：v1.0-cto-review | **日期**：2026-05-14 | **状态**：待评审
>
> 本文档在以下三方对齐基础上撰写，并经 CTO 视角审查补强：
>
> 1. **产品定位**：`docs/kucoin-ai-trading-overview.drawio`（以 AI 带单竞技为核心 IP，驱动关注、讨论与跟单，赋能现货/合约/机器人/理财等，并定义经营与技术指标）。
> 2. **行业实践参照**：`docs/AI Trading Bot Strategy and Implementati(1).pdf`（AI 交易员分层上线、跟单机制、风控与运营打法等行业归纳）。
> 3. **当前工程现实**：本仓库 `ai-web3-trading-agent` 为 **单体 FastAPI + Gateway + BaseAgent** 的智能体服务，**不内嵌交易所撮合与实盘下单**，与「跟单执行、Smart Ratio、仓位级交易风控」在所内交易系统对接。
> 4. **量化理论框架**：[QSDoc (QuantStudio)](https://qsdoc.readthedocs.io/zh-cn/latest/index.html) —— 组合优化（§8）、Barra 风险模型（§7）、回测引擎（§9）、因子评估（§10）、策略类型库（§13）、绩效归因（§14）。详见 [附录 D：QSDoc 引用索引](#附录-dqsdoc-量化理论引用索引)。

---

## 目录

1. [目标与边界](#1-目标与边界)
2. [行业参照摘要](#2-行业参照摘要)
3. [总体架构](#3-总体架构)
4. [核心业务方案](#4-核心业务方案)
5. [技术实施要点](#5-技术实施要点)
6. [分阶段路线](#6-分阶段路线)
7. [指标与实验](#7-指标与实验)
8. [风险与合规清单](#8-风险与合规清单)
9. [**附录 A：CTO FAQ（必读）**](#附录-acto-faq必读)
10. [**附录 B：P1 关键路径与依赖**](#附录-bp1-关键路径与依赖)
11. [**附录 C：风险—应对矩阵**](#附录-c风险应对矩阵)
12. [**附录 D：QSDoc 量化理论引用索引**](#附录-dqsdoc-量化理论引用索引)
13. [文档与图形索引](#文档与图形索引)

---

## 1. 目标与边界

### 1.1 产品目标

| 维度 | 目标 | 可衡量指标 |
|------|------|-----------|
| **核心 IP** | AI 带单员 + **竞技/榜单**，形成可讨论、可跟单的持续内容 | 榜单日活、讨论量、内容生产频率 |
| **交易侧结果** | 提升现货与合约 **交易量、手续费、活跃资金** | 现货+合约 GMV 环比、手续费收入、日均活跃资金 |
| **过程指标** | 带单渗透率与机器人转化 | **带单渗透率** = 跟单用户数 / 暴露于 AI 带单内容的活跃用户数；**机器人转化率** = 通过带单入口开通机器人的用户 / 跟单用户 |
| **能力主张** | 多源特征融合、可审计信号链、与 **撮合 / 跟单 / 风控** 在 **产品规则层** 联动 | 特征源可用率（SLA）、信号发布→展示延迟、跨系统接口成功率 |

> **CTO 关切回应**：新技术必须能在 **「决策质量—可追溯—仿真验证—上线后交易量/费率归因」** 上闭环；仅靠 Feed CTR 不足，需与 **下单、跟单、手续费** 的实验与埋点一致。详见 [附录 A - Q3 实验归因](#q3-实验归因链路怎么闭环)。

### 1.2 工程边界

| 能力 | 本仓库（Agent 服务）可承接 | 须所内交易系统 / 中台承接 |
|------|---------------------------|---------------------------|
| 行情、链上、资讯、特征加工 | 是（工具、ValueScan、signal_analysis、backtest 等） | 可与行情/数据中台合并架构 |
| 对话、解读、推荐话术、流式体验 | 是（chat、Gateway、LLM） | — |
| 内容合规与查询风控 | 是（LLM Shield、配置开关） | — |
| **竞技榜单数据生成与排名** | 是（signal_analysis → 指标计算 → 排名服务） | 展示层可与 Feed/活动页对齐 |
| 实盘下单、跟单复制、保证金比例 | 否（对接面） | Smart Ratio、订单路由、强平 |
| 交易级风控（仓位、杠杆、日亏停损） | 规则可下沉为 **策略约束输入** | 执行闸门在所内 |

---

## 2. 行业参照摘要

下列结论来自内部综述材料，用于指导 **阶段节奏** 与 **产品设计**，不替代 KuCoin 自有数据与合规口径。

- **分阶段**：先 **信息/对话类 AI** 建立信任与习惯，再上线 **AI 跟单**，再叠加活动与 Copilot 式主动协作——与本概览图中「触达 → 赋能交易」一致。
- **跟单侧**：**比例跟单（Smart Ratio 类）** 保持主从资金 **风险敞口比例** 一致；参数侧需 **最大仓位、杠杆上限、日亏损阈值、止盈止损** 等与所内引擎对齐。
- **运营与商业化**：常见组合为 **低利润分成 + 手续费** 或 **基础能力免费 + 增值**；需单独做 **经济模型与法务** 评审。
- **信任与排序**：展示 **真实资金/可核对口径** 下的业绩时，排序宜偏向 **风险调整后收益、回撤可控性**，而非单一绝对利润（与「诊币/风险」用户需求一致）。
- **合规与反滥用**：交易员行为规范、API/KYB、自动化交易授权、反欺诈等与 **所内风控、合规** 统一方案绑定，Agent 侧主要承担 **内容合规与异常行为上报**，不替代交易反欺诈系统。

---

## 3. 总体架构

### 3.1 业务赋能视图

- **输入**：市场与数据（行情、安全态势、爬虫资讯、账户与资产画像、站内行为）。
- **中枢**：AI+ 交易引擎；**核心 IP** 为 AI 带单员 / 竞技（信号 · 回测 · 跟单路由）；并列智能理财、推荐×机器人。
- **输出**：内向 **机器人 / 跟单 / 合约 / 现货 / 理财 / 钱包** 赋能；外向 **SEO / PUSH / Feed / 广告** 带量回流。
- **指标**：Feed 与机器人推荐的 CTR/转化/活跃资金；技术侧 **A/B、量价归因、跟单渗透、熔断** 等。

### 3.2 运行时视图

- **入口**：HTTP/SSE → `web/application`、`web/router` 挂载各 `api/*`。
- **编排**：`agent/plan/gateway.py`（FastFilter、Router、ToolPolicy、Skill 注入）→ `BaseAgent` + Mixins。
- **推理路径**：DAG / Quick / `trading_agents`（可选）/ 其他 plan·skills。
- **数据与工具**：`agent/tools`、`libs/valuescan`、`mcp`、KuCoin 公共行情等。
- **横切**：
  - `llm` + Shield（内容风控）
  - `memory/mem0` 与 Redis 会话
  - `backtest` 与 `signal_analysis`（离线验证）
  - **TraceId 纵向贯穿**：HTTP 入口注入 → Gateway → Agent → 工具调用 → 日志/埋点统一采集（详见 §5 建议增量）
  - **circuit_breaker** 保护
- **边界**：**所内** 撮合、实盘下单、跟单引擎、交易强风控。

#### TraceId 可观测性设计（新增）

```
HTTP Request (SSE/WebSocket)
    │
    ▼  [注入 TraceId / SpanId 到 context]
Gateway (FastFilter → Router → ToolPolicy)
    │   └── TraceId: ku-ai-{timestamp}-{random8}
    ▼
BaseAgent + Mixins
    │   ├── LLM 调用: span "llm.inference" {model, tokens, latency}
    │   ├── 工具调用: span "tool.{name}" {input_hash, output_size, latency}
    │   └── 信号生成: span "signal.generate" {strategy_ver, feature_ver}
    ▼
Tool Registry (crypto_ta, valuescan, mcp...)
    │   └── span "tool.exec" {source, latency, status}
    ▼
[输出层]
    ├── 用户响应: TraceId 写入 response header (X-Trace-Id)
    ├── 结构化信号: TraceId 作为 signal_metadata.trace_id
    └── 埋点事件: TraceId 附着至所有 analytics events
         └── → 归因链路: uid + trace_id → exposure → click → copy_trade → order → fee
```

> **实现方式**：在 `gateway.py` 的请求入口中间件注入 OpenTelemetry-compatible TraceId；通过 Python `contextvars` 在协程间传播；工具层自动提取并附加到日志与埋点。

### 3.3 组合构建与优化

公开文档 [《组合优化》](https://qsdoc.readthedocs.io/zh-cn/latest/%E7%BB%84%E5%90%88%E4%BC%98%E5%8C%96.html)（QSDoc / Scorpi000）将「多策略、多标的资金分配」表述为 **带约束的最优化问题**。

**约束口径（QSDoc §8.1.1）**：

| 约束类型 | 数学表达 | 工程映射 |
|----------|---------|---------|
| 权重上下限 | \(l \le w \le u\) 或相对基准 \(w_b\) | 策略元数据 / 跟单引擎共享规则集 |
| 预算约束 | \(\mathbf{1}^T w = a\) | 全额配置 / 部分仓 |
| 因子暴露 | \(x^T(w-w_b)=0\) | 风格中性 / 板块暴露限制 |
| 波动率/跟踪误差 | \((w-w_b)^T\Sigma(w-w_b)\le\sigma^2\) | 风险预算上限 |
| 换手约束 | 总量 / 单券阈值 / 成交额加权 | 组合调仓成本控制 |
| 稀疏持仓 | \(\text{nnz}(w)\le N\) | 混合整数规划（可选） |

**目标模型路线图**（不限于已实现的某一种）：

- **均值–方差 + 交易成本**：\(\max_{w\in\mathfrak{C}} \gamma\mu^T w - \frac{\lambda}{2}w^T\Sigma w - \text{TC}(w)\)
- **Black–Litterman**：LLM/策略观点结构化接入，贝叶斯融合均衡先验
- **Bayes–Stein 压缩**：降低收益估计噪声，与稳健回测并排评估
- **最大夏普**：凸规划 + 一维搜索
- **风险预算 / 风险平价**：按风险贡献匹配预算；\(b_i=1/n\) 为平价
- **最大分散度**：竞技场集中度惩罚的补充指标

落地建议：**组合层**以 `ensemble`、`signal_analysis`、`metrics` 与所内「最大仓位 / 杠杆 / 单日亏损」并联设计；若引入凸优化求解器，应独立模块化并保证 **可追溯输入（μ,Σ）、版本与 reproducibility**，走 `walk_forward` 同源门禁。

---

## 4. 核心业务方案

### 4.1 AI 带单员：定义与输出物

#### 定义

平台注册的「带单员」实体可为 **人类 KOL** 与 **AI 带单员** 并列。AI 侧需固定以下三要素，支持审计与回放：

| 要素 | 内容 | 版本化管理 |
|------|------|-----------|
| **策略版本** | 信号生成逻辑、选品种过滤器、持仓周期参数 | Git SHA + 语义版本（如 v2.1.3-momentum） |
| **特征与模型版本** | 输入特征集合、模型权重/超参 | MLflow / 自研 registry 记录 |
| **风控档位** | 最大仓位上限、杠杆倍数、止损线 | 配置中心枚举（conservative / moderate / aggressive） |

#### 对用户输出物

| 输出物 | 格式 | 用途 |
|--------|------|------|
| **可解释观点/信号** | 自然语言 + 结构化字段（品种、方向、周期、风险提示） | 对话展示、Feed 卡片、Push 推送 |
| **结构化信号** | JSON Schema 标准化（含时间戳、置信度、来源策略 ID） | 展示与回测同源、榜单数据输入 |
| **跟单标识** | trader_id + strategy_instance_id + risk_tier | 跟单关系在所内账户系统维护，本服务仅传递 |

#### 竞技榜单系统（补强）

**排名框架（v1 候选公式）**：

$$
\text{Score}_i = w_1 \cdot \text{Sharpe}_i + w_2 \cdot (1 - \text{MDD}_i) + w_3 \cdot \text{Stability}_i + w_4 \cdot \log(\text{Volume}_i + 1)
$$

其中：
- \(\text{Sharpe}_i\)：年化夏普比率（滚动 90 日）
- \(\text{MDD}_i\)：最大回撤（归一化至 [0,1]）
- \(\text{Stability}_i\)：**波动环境分段表现一致性**——将历史按市场波动率分为高/中/低三段，分别计算收益，取最低段收益作为稳定性得分（避免仅在牛市表现好的策略排高）
- \(\text{Volume}_i\)：累计交易量（对数压缩防止头部垄断）
- 初始权重建议：\(w_1=0.35, w_2=0.25, w_3=0.25, w_4=0.15\)

**数据流**（新增节点）：

```
backtest/ (策略回测引擎)
    │  输出: 各策略每日 PnL, positions, metrics
    ▼
signal_analysis/tracker.py
    │  计算: Sharpe, MDD, Calmar, 波动分段收益, 换手率
    ▼
signal_analysis/weight_optimizer_.py
    │  聚合: 多维度原始指标 → 标准化 → 加权合成
    ▼
【竞技榜单服务】(新增)
    │  功能:
    │   ① 排名计算 & 定时刷新 (每 4h / 事件驱动)
    │   ② 分段表现面板 (牛/熊/震荡)
    │   ③ 异常检测 (gaming 检测: 收益突变/相关性异常)
    │   ④ API: GET /api/v1/leaderboard?period=90d&category=risk_adjusted
    ▼
输出渠道:
    ├── Dashboard 监控页面
    ├── Feed / 活动页榜单卡片
    └── Agent 对话引用 ("当前排名第 X，近 90 日 Sharpe Y.Y")
```

> **防 Gaming 机制**：
> - 收益相关性聚类：若两个带单员信号相关性 > 0.9，标记为疑似同源，降权处理
> - 收益突变检测：单日收益超过 3σ 触发人工审核 flag
> - 分段暴露：强制展示高波动/低波动环境下各自表现，让用户自行判断

### 4.2 信号—回测—发布 流水线

#### 第一步：离线验证

策略/信号逻辑在 `backtest/` 与 `signal_analysis/` 可复现。重大变更走以下门禁：

| 门禁 | 触发条件 | 标准 |
|------|---------|------|
| **回归集测试** | 策略代码变更 | 全部预设回归 case 通过，指标偏差 < 阈值 |
| **Walk-Forward** | 新策略上线前 / 季度复审 | 滚动窗口样本内外表现一致，无严重过拟合迹象 |
| **压力场景** | 市场极端事件复盘 | 黑天鹅日（如 2024 BTC 单日跌幅 >10%）策略行为合理 |

#### 第二步：发布

通过配置与版本号将「可跟单策略」与 **Agent 推理路径**、**展示渠道**绑定。核心原则：

- **禁止「线下口径」与「线上展示」不一致**——所有对外数字必须源自同一套 signal_analysis 管道
- 版本号语义化（如 `strat-v2.1.3-backtest-v20260514`），支持一键回滚
- 发布记录写入不可变 log，支持审计查询

#### 第三步：线上 LLM 辅助

LLM 用于 **解读、问答、综述** 三种场景，严格遵循以下原则：

| 场景 | LLM 权限 | 硬约束 |
|------|----------|--------|
| 解读信号 | 将结构化信号翻译为自然语言 | 不允许修改方向/仓位数值 |
| 用户问答 | 基于已有数据和信号回答 | 不允许"编造"未经验证的观点 |
| 市场综述 | 聚合多源信息生成摘要 | 必须标注信息来源与时效性 |

**核心可下单信号若与 LLM 输出耦合，必须有硬约束与二次校验**：

```python
# 伪代码：二次校验流程
raw_signal = llm_generate_signal(user_context, market_data)

# 第一层：Shield 合规检查
if shield.check(raw_signal).violates_policy:
    return REJECTED("合规拦截")

# 第二层：策略约束校验（产品+风控定义）
validated = strategy_constraint.validate(
    raw_signal,
    rules={
        "max_position_pct": config.max_position,     # 所内闸门同步值
        "max_leverage": config.leverage_cap,
        "min_confidence": 0.6,                        # 置信度下限
        "blacklist": get_symbol_blacklist(),          # 动态黑名单
        "cooldown": check_symbol_cooldown(symbol),    # 冷却期检查
    }
)

# 第三层：与独立信号源交叉验证（可选，P2）
if config.cross_validation_enabled:
    independent = foundation_model.predict(market_features)
    if direction_mismatch(raw_signal, independent):
        return FLAGGED_FOR_REVIEW("FM 交叉验证不一致")

return validated_signal
```

### 4.3 跟单与执行（所内为主，本仓对接）

#### 跟单模式

行业实践中 **比例跟单（Smart Ratio 类）** 可降低跟单资金体量的错配。具体是否 **Smart Ratio 全等** 以 **跟单与清算系统** 实现为准。

本服务向所内系统传递的标准契约：

```json
{
  "trader_id": "ai_lead_trader_001",
  "strategy_instance": "momentum_v2.1",
  "risk_tier": "moderate",
  "signal": {
    "symbol": "BTC-USDT",
    "direction": "long",
    "confidence": 0.78,
    "suggested_position_pct": 5.0,
    "stop_loss_pct": 3.0,
    "take_profit_pct": 8.0,
    "timestamp": "2026-05-14T15:30:00Z",
    "version": "strat-v2.1.3-backtest-v20260514"
  }
}
```

> ⚠️ **会前对齐事项**：Smart Ratio 是否等价比例跟单，需提前与交易线确认并在首次评审前达成一致，不要在会上首次暴露分歧。

#### 风控参数

| 参数 | 生效位置 | 本服务职责 |
|------|---------|-----------|
| 最大仓位 % | **交易所侧闸门** | 预计算提示 + 展示文案 |
| 杠杆上限 | **交易所侧闸门** | 传递 risk_tier 映射值 |
| 单日最大亏损停手 | **交易所侧闸门** | 策略层面预检提示 |
| 止盈止损 | **交易所侧闸门** | 信号附带建议值 |

**最终以交易引擎为准**。本服务提供的所有数值均为"建议"，不得绕过所内闸门。

### 4.4 触达与转化

#### 统一落地页契约

Feed/PUSH/活动页 **承接的统一落地页** 应对齐同一套 **带单员 ID 与风险说明**：

```
Deeplink URL 规范:
kucoin://ai-leader/{trader_id}?source={campaign}&risk_tier={tier}

落地页必需元素:
├── 带单员身份卡 (名称 / 类型-AI or Human / 当前排名)
├── 风险声明区 (固定文案 + tier 对应的具体风险提示)
│   └── "AI 信号仅供参考，不构成投资建议"
│   └── "过往业绩不代表未来表现"
├── 跟单入口按钮 → 跳转至所内跟单页面 (携带 trader_id + strategy_instance)
└── 数据一致性: 所有渠道引用同一 trader_id, 杜绝运营链接与交易系统脱节
```

#### 推荐 × 机器人意图路由

在 **Gateway 工具策略** (`ToolPolicy`) 与 **运营配置** 上预留「跟单意图」路由扩展：

| 意图类型 | 当前处理 | P2 扩展 |
|---------|---------|---------|
| 纯客服意图 | Router → FAQ/客服技能 | 不变 |
| 行情查询意图 | Quick → 行情工具 | 不变 |
| **跟单意图（新增）** | — | Router 检测 → 带单员信号展示 → deeplink 至跟单页 |
| 诊币/分析意图 | DAG → 分析链路 | 可附加「该币是否有 AI 带单信号」标签 |

**Foundation Model 信号集成位置**（补强说明）：

图中量化策略模块的 `foundation_model.py`（深度学习/大模型范式信号）采用 **双通道接入** 设计：

```
通道 A → Ensemble 策略池候选
    foundation_model 输出的 alpha signal
    → 进入 ensemble.py 的策略候选集
    → 经 weight_optimizer 与传统因子信号共同加权
    → 最终作为结构化信号的一部分输出

通道 B → LLM 上下文增强
    foundation_model 的中间表征（attention map / 关键特征）
    → 注入 LLM system prompt 作为辅助上下文
    → 提升 LLM 解读质量（不直接参与交易决策）
    → 用于对话中的「为什么推荐这个」解释生成

选择依据:
    - 通道 A: FM 信号经过完整回测门禁后可作为独立策略源
    - 通道 B: 利用 FM 表征能力增强可解释性，无需额外门禁
    - 两通道解耦: 即使 FM 服务降级，不影响核心信号流水线
```

---

## 5. 技术实施要点

### 5.1 已有组件映射

| 模块 | 路径/组件 | 与 AI 带单员的用途 |
|------|-----------|-------------------|
| 编排与路由 | `agent/plan/gateway.py`、`router`、`fast_filter` | 意图分流、带单/行情/客服隔离；灰度与实验挂载路由/header |
| 多步推理 | `agent/dag_reasoning.py`、`dag_execution.py` | 复杂分析链、工具组合、可保存步骤用于审计 |
| 低延迟路径 | `agent/quick_reasoning.py` | 行情快问、轻量诊币 |
| 多智能体 | `agent/trading_agents/*`、`vendor/TradingAgents` | 深度投研叙事；注意 **意图白名单与开关** |
| 工具 | `agent/tools/*`、`libs/valuescan` | 行情、链上、情报；封装「带单员专用工具包」 |
| 回测与信号 | `backtest/*`、`signal_analysis/*` | **上线前门禁**、竞技榜单的数据同源 |
| 组合优化 | `ensemble`、`metrics`、`walk_forward` | **多策略/多带单员** 权重与风险预算 |
| 内容风控 | `llm/shield`、`is_risk_control_enabled` | 宣传话术、承诺收益类表述拦截 |
| 会话 | `memory/mem0`、`web/api/chat` | 用户偏好、复访承接 |

### 5.2 建议增量（按优先级）

| # | 增量项 | 优先级 | 依赖 | 说明 |
|---|-------|:-----:|------|------|
| **1** | **带单员元数据与版本服务** | P0-MVP | 配置中心 + DB | 策略 ID、版本、生效区间、适用市场；支持审计查询 |
| **2** | **竞技榜单服务** | P0-MVP | signal_analysis 指标 | §4.1 定义的数据流节点；API + Dashboard + Feed 卡片 |
| **3** | **信号/回测结果只写存储** | P0-MVP | 时序 DB | 榜单与 Agent 同源；对外 API 与内部 dashboard 对齐 |
| **4** | **TraceId 全链路追踪** | P0-MVP | OTel SDK / 自研中间件 | HTTP 入口注入 → Gateway → Agent → 工具 → 埋点；详见 §3.2 |
| **5** | **跟单 Deeplink 契约** | P1 | 交易线约定 query 参数 | 风格化 URL + 风控预检接口 |
| **6** | **观测与归因埋点** | P1 | 埋点 SDK | 关键事件对接 **量价与跟单** 埋点系统；详见 §7 |
| **7** | **组合优化服务** | P2 | μ/Σ 版本化 | 引入均值–方差/风险预算等求解器；与 QSDoc 对齐 |
| **8** | **FM 双通道接入** | P2 | foundation_model 就绪 | §4.4 描述的 Ensemble + LLM Context 双通道 |

---

## 6. 分阶段路线

| 阶段 | 产品目标 | 工程重点（本仓 + 所内） | 外部依赖 | 交付物 |
|------|---------|------------------------|---------|--------|
| **P1** | AI 快讯/榜单/对话建立信任；带单员 IP 预埋 | 强化对话与工具稳定性；**埋点与内容风控**；**回测管线可用**；**榜单 MVP 上线** | 数据线提供指标口径定义 | 可用的榜单 + 对话 + Shield + TraceId 基础设施 |
| **P2** | AI 带单员上线，与人类带单员 **同场**；基础活动 | **跟单与风控 API 联调**；**信号版本化**；**榜单数据同源**；**实验桶分流** | 交易线提供跟单接口规格 + Mock；合规审核话术模板 | 可跟单 AI 带单员 + 实验归因闭环 |
| **P3** | 游戏化与 Copilot 式 **情境化协作** | 上下文注入 Gateway；推荐与机器人配置打通；FM 双通道接入 | 反欺诈标准上线 | Copilot 模式 + FM 增强 |

详见 [附录 B - P1 详细关键路径](#附录-bp1-关键路径与依赖)。

---

## 7. 指标与实验

### 7.1 经营指标

| 指标 | 定义 | 数据源 |
|------|------|--------|
| Feed CTR | 点击 AI 带单卡片的 UV / 曝光 UV | 埋点 SDK |
| 带单渗透率 | 跟单用户数 / 暴露于 AI 带单内容的活跃用户数 | 埋点 + 账户系统 |
| 机器人转化率 | 通过带单入口开通机器人的用户 / 跟单用户 | 埋点 + 机器人服务 |
| 现货+合约交易量环比 | AI 暴露组 vs 对照组 GMV 变化 | 交易数据仓库 |
| 手续费收入贡献 | AI 跟单产生的手续费 / 总手续费 | 财务数据 |
| 日均活跃资金 | 跟单用户持仓总资产均值 | 账户系统 |

### 7.2 技术门禁

| 门禁 | 标准 | 触发动作 |
|------|------|---------|
| 灰度发布 | 按 uid hash 分桶，初始 5% → 25% → 100% | Gateway Header 注入 |
| 故障熔断 | 连续 5 次错误或 P99 延迟 > 3s | circuit breaker 自动降级到兜底响应 |
| 策略版本回归 | 全部回归 case 通过 | CI/CD 门禁，阻断发布 |
| 榜单数据一致性 | 线上展示值 = signal_analysis 最新计算值 ± 容差 | 定时巡检 + 告警 |

### 7.3 实验归因设计

```
实验桶划分:
┌─────────────────────────────────────────────┐
│  用户进入 AI 带单触达场景 (Feed / 活动页)      │
│       │                                      │
│       ▼  [hash(uid) % 100]                    │
│  ┌─────────┬─────────┬─────────┐            │
│  │ Control │Treatment│ Treatment│            │
│  │   40%   │  A组 30% │  B组 30% │            │
│  │ (无暴露)│(榜单+对话)│(全功能)  │            │
│  └────┬────┴────┬────┴────┬────┘            │
│       │         │         │                   │
│       ▼         ▼         ▼                  │
│   无操作    查看榜单   查看榜单                │
│             + 对话     + 对话                  │
│                       + 跟单                  │
│                                               │
│  埋点事件链:                                  │
│  exposure → view_leaderboard → click_signal   │
│  → click_copy_trade → order_placed → fee_paid │
│                                               │
│  每个 event 携带:                              │
│  { uid, experiment_group, trace_id,            │
│    trader_id, timestamp, page_source }         │
└─────────────────────────────────────────────┘

归因计算 (T+1 日批处理):
  ATT = E[fee | Treatment] - E[fee | Control]
  渗透率提升 = (copy_rate_T - copy_rate_C) / copy_rate_C
  置信度: bootstrap 1000 次, p < 0.05 为显著
```

---

## 8. 风险与合规清单

| 风险类别 | 具体风险 | 缓解措施 | 责任方 |
|---------|---------|---------|--------|
| **承诺收益/代客理财** | LLM 生成"保证盈利"类表述 | Shield 规则库拦截 + 法务话术模板 + 人工抽查 | Agent + 法务 |
| **异常交易/刷单** | 恶意利用跟单进行洗钱或刷量 | 所内交易风控为主；Agent 侧日志配合调查；榜单 gaming 检测 | 所内风控 + Agent |
| **合约 API 自动化** | 未授权自动化策略执行 | KYB / 授权范围与合规对齐；展示入口可通过配置关闭 | 合规 + 产品 |
| **LLM 幻觉误导** | 产生错误但看似可信的交易建议 | 三层防御（Shield + 硬约束 + 二次校验）+ 异常熔断 | Agent |
| **回测过拟合** | 历史表现好但上线衰减 | walk-forward + 滚动窗口 + 上线 A/B 对照组 | Agent |
| **跨系统联调阻塞** | 所内接口延期导致 P2 顺延 | P2 前置 Mock 联调；接口契约提前冻结 | PM + 交易线 |
| **榜单被 Gaming** | 策略针对排名规则刷榜 | 多维排名 + 相关性聚类检测 + 分段暴露 + 收益突变告警 | Agent |
| **合规话术违规** | 不同地区监管要求差异 | Shield 多地区规则集 + 法务审核模板 | Agent + 法务 + 合规 |

---

## 附录 A：CTO FAQ（必读）

> 以下问题基于 CTO 视角预演整理，建议汇报前逐一准备答案。

### Q1：「多源特征融合」具体指哪些？各源的 SLA 怎么保证？

**回答准备**：

| 特征源 | 内容 | 延迟要求 | Fallback 策略 |
|--------|------|---------|-------------|
| 行情数据 | K线/OBV/资金流向 | < 500ms | 降级为 1min 级缓存 |
| 链上数据 | 大户动向/交易所净流入 | < 5min | 标注"链上数据延迟"，不阻塞信号生成 |
| 资讯/舆情 | 爬虫新闻 + 情感评分 | < 15min | 使用上一窗口情感得分 |
| 用户画像 | 站内行为/偏好/风险等级 | 实时（Redis） | 默认 moderate profile |

> 当任意源降级时，信号置信度自动下调（如从 0.8 → 0.6），并在输出中标注 `data_quality: "degraded"`。

### Q2：竞技榜单公式谁定？给我一个能用的版本

**回答**：已在 §4.1 给出 v1 候选公式（Sharpe + MDD + Stability + Volume 四维加权）。具体权重由数据团队基于历史回测校准，风控团队审批 gaming 防护机制。P1 上线后根据实际数据迭代。

### Q3：实验归因链路怎么闭环？

**回答**：§7.3 已给出完整的实验桶设计和埋点事件链。核心是每个事件携带 `{uid, group, trace_id}` 三元组，T+1 批处理计算 ATT（平均处理效应）。P1 阶段先跑通 exposure → view → click 的上层漏斗，P2 加入 copy_trade → order → fee 的全链路。

### Q4：P1→P2 跨系统联调依赖哪些团队？排期已知吗？

**回答**：详见 [附录 B 关键路径表](#附录-bp1-关键路径与依赖)。关键依赖：
- **数据线**：指标口径定义（P1 Week 1-2 前需完成）
- **交易线**：跟单接口 Mock + 规格（P2 前 2 周需冻结契约）
- **合规**：话术模板审核（P2 前需一次过审）

### Q5：LLM 幻觉导致错误信号的最大风险场景是什么？三层防御够不够？

**回答**：

| 失效模式 | 描述 | 三层防御覆盖？ | 额外措施 |
|---------|------|:------------:|---------|
| 方向完全反转 | LLM 说涨但应该跌 | ✅ 硬约束的方向白名单 | 交叉验证（P2） |
| 数值夸大 | 建议 10% 仓位但合理值是 2% | ✅ max_position_pct 硬上限 | — |
| 编造不存在的利好 | 引用假新闻 | ⚠️ Shield 部分覆盖 | 信息源溯源标注 |
| 隐蔽式误导 | 表述合规但暗示性引导 | ⚠️ 最难防御 | 人工抽样审核 + 用户反馈闭环 |

> 第三种和第四种无法完全自动化防御，需要 **人工抽样（每日 50 条）+ 用户举报通道** 作为安全网。

---

## 附录 B：P1 关键路径与依赖

### 时间线概览（8 周）

```
Week:   1   2   3   4   5   6   7   8
        │   │   │   │   │   │   │   │
本仓:   [===回测管线封装===][=信号版本化=][=榜单MVP==][=埋点+TraceId]
        [=====对话稳定性+Shield====]              │
                                                    │
外部:  [数据线:指标口径定义↑]                       │
        [交易线:跟单接口规格初稿(参考)]             │
        [合规:Shield规则库审核↑]                    │
                                                    │
交付:                                          ★P1上线
```

### 详细任务与依赖

| 周 | 任务 | 所属 | 依赖 | 产出 | 风险 |
|:--:|------|------|------|------|------|------|
| 1-2 | **回测管线封装与门禁** | 本仓 | 现有 backtest/ | CI/CD 集成回归集 + walk-forward 模板 | 低 |
| 1-2 | **指标口径定义** | **外部-数据线** | — | 渗透率/转化率/GMV 的 SQL 定义 | **中**：可能拉扯 |
| 1-2 | **Shield 规则库审核** | **外部-合规** | 法务话术模板 | 合规审核通过的风险话术规则 | **中**：合规周期不确定 |
| 2-3 | **对话稳定性加固** | 本仓 | Week 1 | 错误率 < 1%，P99 < 2s | 低 |
| 3-4 | **信号版本化 + 配置中心** | 本仓 | Week 2 | 策略版本管理 API + 审计日志 | 低 |
| 4-5 | **榜单 MVP** | 本仓 | Week 3-4 + 数据口径 | 榜单 API + Dashboard 页面 | 中：指标计算逻辑复杂度 |
| 5-6 | **埋点 + TraceId 基础设施** | 本仓 | Week 4 | 全链路追踪 + 埋点事件规范 | 低 |
| 5-6 | **跟单接口规格冻结（Mock）** | **外部-交易线** | — | API 契约文档 + Mock Server | **高**：交易线排期未知 |
| 6-8 | **集成测试 + 灰度准备** | 本仓 | 以上全部 | 灰度配置 + rollback SOP | 中 |
| 7-8 | **P1 上线 + 监控** | 本仓 | Week 7 | P1 产线运行 | 低 |

### 关键里程碑

| 里程碑 | 时间 | 准入条件 | Sign-off |
|--------|:----:|---------|----------|
| **M1: 回测门禁就绪** | Week 2 末 | 回归集全部通过 | Tech Lead |
| **M2: 榜单可演示** | Week 5 末 | 数据口径已定义 + 榜单 API 可用 | Product + Data |
| **M3: P1 Ready** | Week 7 末 | 全部任务完成 + 集成测试通过 | Tech Lead + QA |
| **M4: P1 上线** | Week 8 | M3 + 灰度计划审批 | CTO |

---

## 附录 C：风险—应对矩阵

| # | 风险 | 概率 | 影响 | 风险等级 | 应对措施 | 触发条件 |
|:-:|------|:----:|:----:|:-------:|---------|---------|
| R1 | LLM 幻觉导致误导信号 | 中 | 高 | 🔴 高 | 三层防御 + 异常自动熔断 + 人工抽样 50条/日 | Shield 拦截率突降 或 用户投诉 > 5/日 |
| R2 | 回测过拟合上线衰减 | 高 | 中 | 🟡 中 | walk-forward + 滚动窗口 + A/B 对照组 | 样本外 Sharpe < 样本内 Sharpe × 0.5 |
| R3 | 跨系统联调阻塞 P2 | 中 | 高 | 🔴 高 | P2 前置 Mock 联调；接口契约提前冻结 | 交易线 Mock 不可用 超过 1 周 |
| R4 | 竞技榜单被 Gaming | 低 | 高 | 🟡 中 | 多维排名 + 相关性聚类 + 分段暴露 + 收益突变检测 | 同源信号相关 > 0.9 或 单日收益 > 3σ |
| R5 | 合规话术违规 | 低 | 极高 | 🔴 高 | Shield 多地区规则集 + 法务模板 + 人工抽查 | 合规审核不通过 或 监管问询 |
| R6 | 数据源降级影响信号质量 | 中 | 中 | 🟡 中 | 多源降级策略 + 置信度动态下调 + 质量标注 | 任一数据源 SLA 突破 > 10% 请求 |
| R7 | TraceId 链路断裂导致排查困难 | 低 | 中 | 🟢 低 | OTel SDK 集成 + health check + 告警 | 链路完整率 < 95%（采样检测） |
| R8 | 榜单排名引发用户过度追高 | 中 | 中 | 🟡 中 | 风险提示强化 + 分散化建议 + 冷静期提示 | 跟单集中度 > 70% 单一带单员 |

---

## 附录 D：QSDoc 量化理论引用索引

> 本方案中所有量化公式、方法论和 API 设计均引用自 [QuantStudio (QSDoc)](https://qsdoc.readthedocs.io/zh-cn/latest/index.html) 官方文档。
> **详细技术内容（含完整数学推导、API 代码和参数说明）见独立文件**：`qsdoc-reference-for-ai-leader-trader.md`。

### 引用对照表

| 方案章节 | QSDoc 章节 | 核心引用内容 |
|---------|-----------|-------------|
| §3.3 组合构建与优化 | **第 8 章** | 6 种目标函数（MV+TC / BL / BS / MaxSharpe / RiskBudget / MaxDiv）的精确公式 + 10 类约束条件 + MV 六大已知问题及改进 |
| §3.2 TraceId 风险模型联动 | **第 7 章** | Barra CNE5 十大风格因子定义、协方差三步估计法（EWMA→结构化→Bayesian收缩）、Bias Test 模型检验框架 |
| §4.1 竞技榜单公式 | **第 8.1.7 节 + 第 10 章** | 分散度指标体系（DR/CR/HHI/香农熵/泰尔熵）、IC/IR 信息系数框架、因子有效性五条判断标准 |
| §4.2 信号—回测流水线 | **第 9 章 + 第 13 章** | BackTestModel 模块化架构、4 种策略类型（Base/Portfolio/HierarchicalFiltration/Optimizer/Timing）、账户配置 API |
| §4.4 Foundation Model 接入 | **第 13.1.2 节** | OptimizerStrategy 与 PortfolioConstructor 的集成模式 |
| §5 技术实施 | **第 8.4 节** | PortfolioConstructor 完整 API（MatlabPC/CVXPY）、7 类约束组件、优化目标类清单 |
| §7.3 实验归因 | **第 10 章 + 第 14 章** | Fama-MacBeth 截面回归、Risk-Adjusted IC、Brinson 多期归因链接法、FMP 因子模拟组合归因 |
| 附录 C 风险矩阵 | **第 8.1.2 节 + 第 7.5 节** | 均值方差六大实证问题、协方差 Eigenfactor Adjustment、Volatility Regime Adjustment |

### 加密市场因子适配说明

传统 Barra 因子面向股票市场设计，加密市场落地需做以下适配：

| 传统 Barra 因子 | 加密市场代理变量 | 可行性 | 优先级 |
|---------------|---------------|:-----:|:-----:|
| Size（规模） | TVL / 市值对数 | ✅ 直接可用 | P1 |
| Beta（相对 BTC 的 CAPM β） | 日收益率回归斜率（252日窗口） | ✅ 直接可用 | P1 |
| Momentum（动量） | RSTR（跳过21日，回溯504日） | ⚠️ 需适配无停牌特性 | P1 |
| Liquidity（流动性） | DEX 交易深度 / 链上活跃地址数 | ✅ 可构造 | P1 |
| B/P（账面市值比） | 无直接对应 | ❌ 不适用 | — |
| Earnings Yield | Staking APR / 协议费用率倒数 | ⚠️ 部分适用 | P2 |
| Growth（成长性） | 生态增长率 / 开发活跃度 | ⚠️ 需自定义数据源 | P2 |
| Leverage（杠杆率） | 协议借贷总余额 / TVL | ⚠️ 仅 DeFi 适用 | P2 |

> **建议**：P1 使用 Size/Beta/Momentum/Liquidity 四因子简化模型；P2 逐步引入链上代理变量。

### 策略演进路径（基于 QSDoc 策略类型库）

```
P1: HierarchicalFiltrationStrategy (纯配置, 无需代码)
├── Layer 1: 市场筛选 (BTC dominance / 总市值门槛)
├── Layer 2: 动量/流动性筛选 (Top N)
├── 权重: 等权 or 流动性加权
└── 再平衡: 周
│
P2: OptimizerStrategy (组合优化, 对接 PortfolioConstructor)
├── 目标: MeanVariance 或 RiskBudget
├── μ 来源: AI signal score = f(LLM_view, FM_alpha, traditional_factors)
├── Σ 来源: Barra 适配版四因子
├── 约束: 所内同步 (max_position / leverage / drawdown)
└── 再平衡: 日 or 触发式
│
P3: TimingStrategy + OptimizerStrategy + FM Channel-B
```

---

## 文档与图形索引

| 文档/图形 | 路径/链接 | 说明 |
|----------|----------|------|
| 产品全景图 | `docs/kucoin-ai-trading-overview.drawio` | 业务赋能视图（输入-中枢-输出-指标） |
| 运行时架构图 | `docs/kucoin-ai-technical-architecture.drawio` | 本仓部署拓扑（含 TraceId 贯穿标注） |
| 行业综述 PDF | `docs/AI Trading Bot Strategy and Implementati(1).pdf` | 行业实践参照 |
| 组合优化理论 | [QSDoc · 组合优化](https://qsdoc.readthedocs.io/zh-cn/latest/%E7%BB%84%E5%90%88%E4%BC%98%E5%8C%96.html) | 理论框架参考 |
| QSDoc 完整引用 | `qsdoc-reference-for-ai-leader-trader.md` | 6 章技术内容完整提取（含公式/API/代码） |

---

*本文档为 CTO 汇报版技术方案草案（v1.0-cto-review）。实施前需与交易、风控、合规、数据、运营联合评审并冻结接口与指标口径。*
