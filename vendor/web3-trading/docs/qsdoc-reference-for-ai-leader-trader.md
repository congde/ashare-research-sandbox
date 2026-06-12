# QSDoc 量化参考摘要（AI 带单员技术方案引用版）

> **来源**：[QuantStudio 文档](https://qsdoc.readthedocs.io/zh-cn/latest/index.html) (Scorpi000)
> **用途**：本文件为 `kucoin-ai-lead-trader-proposal-cto-v1.md` 中所有量化公式、方法论和 API 引用提供**权威出处与精确对照**。
> **覆盖章节**：第 7（风险模型）、8（组合优化）、9（回测）、10（因子截面测试）、13（策略测试）、14（绩效归因）

---

## 一、组合优化（§3.3 对应 QSDoc 第 8 章）

### 1.1 目标函数精确公式

技术方案 §3.3 列出的目标模型在 QSDoc 中均有完整定义：

#### (A) 均值–方差 + 交易成本

$$\max_{\mathbf{w}\in\mathfrak{C}} \left\{ \gamma \cdot \boldsymbol{\mu}^T \mathbf{w} - \frac{\lambda}{2}\mathbf{w}^T\boldsymbol{\Sigma}\mathbf{w} - \text{TC}(\mathbf{w}) \right\}$$

其中交易成本惩罚：

$$\text{TC}(\mathbf{w}) = \lambda_1\sum_{i=1}^{n}|w_i - w_{0i}| + \lambda_2\sum_{i=1}^{n}(w_i - w_{0i})^+ + \lambda_3\sum_{i=1}^{n}(w_i - w_{0i})^-$$

| 参数 | 含义 | 建议值域 |
|------|------|---------|
| $\gamma$ | 收益项系数 | 0~1 |
| $\lambda$ | 风险厌恶系数 | 10~50（Chopra & Ziemba, 1993） |
| $\lambda_1$ | 对称交易费率 | 按实际手续费设定 |
| $\lambda_2, \lambda_3$ | 非对称买卖费率 | 可设为相同或按滑点差异调整 |

**已知六大问题**（QSDoc §8.1.2 归纳）：

| # | 问题 | 来源研究 | 工程应对 |
|---|------|---------|---------|
| 1 | 参数估计误差大 | Chopra & Ziemba (1993) | BS/BL 压缩估计 |
| 2 | 结果对参数敏感 | Michaud (1989) | 权重上下限约束（Behr et al., 2013）|
| 3 | 持仓过度集中 | Broadie (1993) | 非零持仓约束 nnz(w)≤N |
| 4 | 高换手率 | De Carvalho et al. (2012) | 换手惩罚 TC(w) |
| 5 | 极端分配结果 | Best & Grafer (1991) | 权重上下限 + 稀疏化 |
| 6 | 样本外表现差 | DeMiguel et al. (2009) | walk-forward 门禁 |

#### (B) Black–Litterman 模型

**步骤**：
1. 计算先验均衡收益：$\boldsymbol{\pi} = \delta \boldsymbol{\Sigma} \mathbf{w}_{mkt}$（$\delta$ 为风险厌恶系数，$\mathbf{w}_{mkt}$ 为市值权重）
2. 定义主观观点：$k$ 个证券的预测向量 $\mathbf{Q}$ 和置信度矩阵 $\boldsymbol{\Omega}$
3. 后验收益融合：

$$\boldsymbol{\mu}_{BL} = \left[(\tau\boldsymbol{\Sigma})^{-1} + \mathbf{P}^T\boldsymbol{\Omega}^{-1}\mathbf{P}\right]^{-1} \left[(\tau\boldsymbol{\Sigma})^{-1}\boldsymbol{\pi} + \mathbf{P}^T\boldsymbol{\Omega}^{-1}\mathbf{Q}\right]$$

其中 $\tau$ 为尺度参数（通常取 1），$\mathbf{P}$ 为观点映射矩阵（k×n）。

**与 AI 带单员的衔接**：LLM/策略生成的「观点」可直接映射为 $\mathbf{Q}$ 向量；观点置信度由信号模型的回测 Sharpe/IC 决定 $\boldsymbol{\Omega}$ 的对角元素。

#### (C) Bayes–Stein 压缩估计

$$\hat{\boldsymbol{\mu}}_{BS} = k \cdot \bar{R}\mathbf{1} + (1-k) \cdot \hat{\boldsymbol{\mu}}_{sample}$$

压缩强度 $k$ 由 Jorion 公式决定（样本量越小、资产越多→压缩越强）。当 $k=1$ 时退化为最小方差组合。

**BS vs BL 对照**：

| 维度 | Bayes-Stein | Black-Litterman |
|------|-------------|-----------------|
| 压缩方向 | 向共同常数压缩 | 向主观观点调整 |
| 收益排序 | 不改变原有排序 | 可能打乱原有排序 |
| 适用场景 | 无明确观点时降低噪声 | 有结构化主观观点时 |

#### (D) 最大夏普比率

$$\max_{\mathbf{w}} \frac{\boldsymbol{\mu}^T\mathbf{w}}{\sqrt{\mathbf{w}^T\boldsymbol{\Sigma}\mathbf{w}}} \quad \text{s.t. } \mathbf{w}\in\mathfrak{C}$$

求解：凸规划 + 一维搜索。对任意预期收益水平 $x$，固定 $\boldsymbol{\mu}^T\mathbf{w}=x$ 后化为标准二次规划。

#### (E) 风险预算 / 风险平价

边际风险贡献：

$$\frac{\partial \sigma}{\partial w_i} = \frac{(\boldsymbol{\Sigma}\mathbf{w})_i}{\sqrt{\mathbf{w}^T\boldsymbol{\Sigma}\mathbf{w}}}$$

第 $i$ 资产的风险贡献度：

$$\mathcal{RC}_i = w_i \cdot \frac{(\boldsymbol{\Sigma}\mathbf{w})_i}{\sigma(\mathbf{w})}$$

**风险平价条件**（$b_i = 1/n$）：

$$\min_{\mathbf{w}} \sum_{i,j} \left(\frac{\mathcal{RC}_i}{b_i} - \frac{\mathcal{RC}_j}{b_j}\right)^2 \quad \text{s.t. } \mathbf{1}^T\mathbf{w}=1,\ \mathbf{w} \ge \mathbf{0}$$

高维替代方案（凸规划）：

$$\min_{\mathbf{x}} \sigma(\mathbf{x}) = \sqrt{\mathbf{x}^T\boldsymbol{\Sigma}\mathbf{x}} \quad \text{s.t. } \sum b_i\ln x_i \ge c,\ \mathbf{0} \le \mathbf{x} \le \mathbf{1},\ \mathbf{w} = \frac{\mathbf{x}}{\mathbf{1}^T\mathbf{x}}$$

**性质要点**（Maillard et al., 2008）：
- 高波动/高相关资产受惩罚
- 风险平价介于等权和最小方差之间
- 当成分相关系数相同且夏普相等时 → 等价于 Markowitz 最优

#### (F) 最大分散度

$$\max_{\mathbf{w}} D(\mathbf{w}) = \frac{\sum_{i} w_i \sigma_i}{\sqrt{\mathbf{w}^T\boldsymbol{\Sigma}\mathbf{w}}}$$

**分散化指标体系**（可作为竞技榜单的补充维度）：

| 指标 | 公式 | 取值范围 | 含义 |
|------|------|:-------:|------|
| 分散度比率 DR | $\frac{\sum w_i\sigma_i}{\sigma_p}$ | [1, ∞] | 越大越分散 |
| 集中度 CR | $\frac{\sum w_i^2\sigma_i^2}{(\sum w_i\sigma_i)^2}$ | [1/n, 1] | 越大越集中 |
| 加权相关 WPC | 见 QSDoc 公式 | [0, 1] | 平均相关性 |
| HHI 指数 | $\sum w_i^2$ | [1/n, 1] | 权重集中度 |
| 香农熵 | $-\sum w_i\log w_i$ | [0, log n] | 权重不确定性 |

三者关系：$DR = \frac{1}{\sqrt{WPC \cdot (1-CR) + CR}}$

### 1.2 约束条件完整清单（QSDoc §8.1.1）

| 约束类型 | 数学表达 | 与带单员的关系 |
|----------|---------|--------------|
| **权重约束** | $\mathbf{l} \le \mathbf{w}-\mathbf{w}_b \le \mathbf{u}$ | 映射为策略元数据 / 所内风控上限 |
| **预算约束** | $\mathbf{1}^T\mathbf{w} = a$ | 全额配置(a=1) 或 现金保留 |
| **因子暴露** | $\mathbf{x}^T(\mathbf{w}-\mathbf{w}_b) = a$ | 风格中性 / 板块暴露限制 |
| **波动率/跟踪误差** | $(\mathbf{w}-\mathbf{w}_b)^T\boldsymbol{\Sigma}(\mathbf{w}-\mathbf{w}_b)\le\sigma^2$ | 风险预算上限 |
| **换手——总** | $\sum|w_i-w_{0i}| \le a$ | 组合调仓成本控制 |
| **换手——买入侧** | $\sum(w_i-w_{0i})^+ \le a$ | 买入成本单独控制 |
| **换手——卖出侧** | $\sum(w_i-w_{0i})^- \le a$ | 卖出成本单独控制 |
| **个券换手** | $A_i|w_i-w_{0i}| \le a_i$ | 大盘股与小盘股差异化换手 |
| **收益下限** | $\boldsymbol{\mu}^T\mathbf{w} \ge a$ | 绝对收益门槛 |
| **稀疏持仓** | $\text{nnz}(\mathbf{w}) \le N$ | 控制持仓数量，降低操作复杂度 |

### 1.3 QSDoc API 组件映射

| 方案中提到的能力 | QSDoc 对应类 | 说明 |
|-----------------|------------|------|
| 组合优化求解器 | `PortfolioConstructor.MatlabPC` / `.CVXPC` | 支持 MATLAB(yalmip) 或 Python(CVXPY+MOSEK/Gurobi) |
| 优化目标 | `MeanVarianceObjective`, `MaxSharpeObjective`, `RiskBudgetObjective`, `MaxDiversificationObjective` | 即插即用 |
| 约束组件 | `BudgetConstraint`, `WeightConstraint`, `FactorExposeConstraint`, `TurnoverConstraint`, `VolatilityConstraint`, `NonZeroNumConstraint` | 共 7 类约束可自由组合 |
| 风险数据输入 | `FactorCov` + `RiskFactors` + `SpecificRisk` | Barra 风险模型输出直接接入 |

---

## 二、Barra 风险模型（对应 QSDoc 第 7 章）

### 2.1 核心框架

多因子收益率分解：

$$\underbrace{r_i}_{\text{超额收益}} = f_m + \underbrace{\sum_j X_{ij}\cdot f_j}_{\text{行业暴露}} + \underbrace{\sum_s X_{is}\cdot f_s}_{\text{风格暴露}} + \underbrace{u_i}_{\text{特异性收益}}$$

协方差矩阵分解：

$$\mathbf{V} = \mathbf{X} \cdot \mathbf{F} \cdot \mathbf{X}^T + \boldsymbol{\Delta}$$

其中 $\boldsymbol{\Delta}$ 为对角阵（特异性风险互不相关假设）。

### 2.2 十大风格因子（Barra CNE5 风格）

| # | 因子 | 计算组成 | 在加密市场的潜在映射 |
|---|------|---------|-------------------|
| 1 | Size | LNCAP = ln(市值) | 项目市值 / 总锁仓量(TVL) |
| 2 | Beta | CAPM 回归斜率(252日窗口) | 相对于 BTC 的 Beta |
| 3 | Momentum | RSTR(跳过21日, 回溯504日) | 动量因子（需适配加密市场无"停牌"特性） |
| 4 | Residual Volatility | 0.74×DASTD + 0.16×CMRA + 0.10×HSIGMA | 波动率因子 |
| 5 | Non-linear Size | Size³ 正交化 | — |
| 6 | B/P | BTOP = B/P | N/A（加密资产无账面价值） |
| 7 | Liquidity | 0.35×STOM + 0.35×STOQ + 0.30×STOA | 链上流动性 / DEX 交易深度 |
| 8 | Earnings Yield | 0.68×EPFWD + 0.21×CETOP + 0.11×ETOP | Staking 收益率 / 费用率倒数 |
| 9 | Growth | 多子因子加权(EGRLF/EGRSF/EGRO/SGRO) | 生态增长率 / 开发活跃度 |
| 10 | Leverage | MLEV + DTOA + BLEV | 协议杠杆倍数 |

> **注意**：传统 Barra 因子需适配加密市场特征。建议 P1 先使用 Size/Beta/Momentum/Liquidity 四个可跨市场泛化的因子；B/P、Growth、Leverage 需要构建链上代理变量。

### 2.3 协方差矩阵估计流程（三步法）

```
Step 1: 因子协方差矩阵 F 的估计
├── EWMA 加权 (相关半衰期 480天, 波动率半衰期 90天)
├── Newey-West 自相关修正 (滞后 N+1=11 期)
└── Eigenfactor Risk Adjustment (Monte Carlo 修正特征值偏差)

Step 2: 特异性风险 Δ 的估计
├── Step 2a: 时序样本估计 σ_u^(TS) (EWMA + Newey-West)
├── Step 2b: 结构化模型 σ_u^(STR) (截面回归: 行业/Vol/Liquidity/Momentum)
├── Step 2c: Bayesian Shrinkage (按市值分10组收缩)
│   σ_u = γ·σ_u^(TS) + (1-γ)·σ_u^(STR)
└── Volatility Regime Adjustment: σ̃_i = λ_s · σ̂_i

Step 3: 合成完整协方差矩阵
    V = X · F̃ · X^T + Δ̃
```

### 2.4 风险模型检验框架

**Bias Test**（模型偏差检验）：

$$z_t^T = \frac{r_t}{\hat{\sigma}_t}, \quad b_t^T = \sqrt{\frac{1}{T-1}\sum(z_s - \bar{z}_t)^2}$$

95% 置信区间：$[1-\sqrt{2/T},\ 1+\sqrt{2/T}]$

**RAD（平均绝对偏离）**：正态假设下中心 ≈ 0.17，150 期 95% 上界 ≈ 0.22

**检验组合类型**：全体A股/各行业/Top-Bottom 五分位/大小市值半分位/随机抽取（20/50/100/200 只）

> **AI 带单员应用**：可将 Bias Test 作为信号质量监控的一部分——若某个策略的实际收益持续偏离风险模型预测（$b_t^T$ 超出置信区间），触发人工审核 flag。

---

## 三、回测引擎（对应 QSDoc 第 9 章）

### 3.1 架构设计

```
BackTestModel (主控器)
├── DateTimeSeries        → 时间序列遍历引擎
├── Modules[]             → 模块化插件列表
│   ├── Strategy          → 策略模块 (必须实现 trade())
│   │   ├── BaseStrategy           (基类)
│   │   ├── PortfolioStrategy      (组合策略, 实现 genSignal())
│   │   │   ├── HierarchicalFiltrationStrategy  (分层筛选, 纯配置)
│   │   │   └── OptimizerStrategy              (组合优化, 需 PC)
│   │   └── TimingStrategy       (择时策略)
│   ├── Account            → 证券账户 (资金/持仓/费用)
│   └── Analysis           → 分析模块 (绩效/归因/因子测试)
├── run(dts, subprocess_num) → 支持多进程并行
└── output() / genHTMLReport()
```

### 3.2 关键 API 设计

```python
# 账户配置 (DefaultAccount)
account["初始资金"]     = 1e8
account["负债上限"]     = 0
account["交易延迟"]      = True/False         # 是否 T+1
account["买入交易费率"]  = 0.003              # 0.3%
account["卖出交易费率"]  = 0.003
account["允许卖空"]      = False
account["成交价因子"]    = "收盘价"

# 分层筛选策略 (HierarchicalFiltrationStrategy) —— 最适合 P1 快速验证
strategy["层数"]         = 2                  # 如: 先选赛道, 再选币种
strategy["每层配置"]     = [
    {"信号": "momentum_score", "筛选方式": "定量", "比例": 0.2},
    {"信号": "liquidity_rank", "筛选方式": "定比", "数量": 10}
]
strategy["权重分配"]     = "等权" or "因子加权"
strategy["比较基准"]     = "BTC-USDT"

# 组合优化策略 (OptimizerStrategy) —— P2 使用
strategy["优化器"]       = PC                 # PortfolioConstructor 实例
strategy["预期收益因子"]  = "AI_signal_score"
strategy["基准权重"]      = benchmark_weights
```

### 3.3 与 AI 带单员仓库的对接路径

| 本仓库现有模块 | QSDoc 对应 | 对接方式 |
|---------------|-----------|---------|
| `backtest/engine.py` | BackTestModel.run() | 封装适配层，将 engine.py 的异步事件循环映射到 QSDoc 的步进模式 |
| `backtest/indicators.py` + `metrics.py` | FactorTable / 自定义因子 | 将 crypto_ta 技术指标注册为 CustomFT 的因子 |
| `backtest/hooks/risk_position.py` | Account 的买卖限制 | 将仓位/止损逻辑注入 account 配置 |
| `signal_analysis/*` | SectionFactor.IC / QuantilePortfolio | 因子截面测试直接复用 QS 模块 |
| `strategies/base.py` | Strategy 基类 | 统一 genSignal() 接口 |

---

## 四、因子评估体系（对应 QSDoc 第 10 章）

### 4.1 IC / IR 分析框架

**Rank IC（Spearman 秩相关）**：

$$\rho(Q_r^t, Q_j^{t-1}) = \frac{\sum(Q_{i,r}^t - \bar{Q}_r^t)(Q_{i,j}^{t-1} - \bar{Q}_j^{t-1})}{\sqrt{\sum(Q_{i,r}^t - \bar{Q}_r^t)^2 \cdot \sum(Q_{i,j}^{t-1} - \bar{Q}_j^{t-1})^2}}$$

**信息比率 IR**：$\text{IR} = \frac{\text{mean(IC)}}{\text{std(IC)}}$

**IC 衰减分析**：计算 Rank IC 随间隔 $k = 1, 2, ..., K$ 的变化趋势，判断因子持续性。

### 4.2 因子有效性判断标准

一个有效的 Alpha 因子应满足：

| 条件 | 标准 |
|------|------|
| IC 方向 | Rank IC 均值 > 0（多头因子）且 t-stat 显著 |
| 单调性 | 分位数组合各组收益单调递增/递减 |
| 稳定性 | IC 衰减慢（至少 k≥3 仍有显著 IC），换手率低 |
| 鲁棒性 | 行业调整后 IC 仍显著，Fama-MacBeth 回归后 alpha > 0 |

### 4.3 多因子方法

**Fama-MacBeth 截面回归**（剥离风险因子后的纯 alpha）：

$$r_i^t = f_j^t \cdot \beta_{i,j}^{t-1} + \sum_k \tilde{f}_k^t \cdot \tilde{\beta}_{i,k}^{t-1} + \varepsilon_i^t$$

**风险调整 IC**：在 IC 测试中加入风险因子控制变量。

**因子相关性矩阵**：检测多因子间的共线性（Spearman / Pearson / Kendall），用于 ensemble 前去冗余。

### 4.4 与 AI 带单员榜单的衔接

将 §4.1 竞技榜单公式中的各维度映射到因子评估体系：

| 榜单维度 | QSDoc 方法 | 数据来源 |
|---------|-----------|---------|
| Sharpe（收益风险比） | 回测绩效计算 | backtest/engine 输出 |
| MDD（最大回撤） | 账户价值序列极值 | getAccountValueSeries() |
| Stability（分段表现） | 按 Volatility Regime 切片计算 | 风险模型 §2.3 的 $\lambda_F$ 作为状态标识 |
| Volume（交易量） | 成交记录聚合 | TradingRecord |

---

## 五、策略类型库（对应 QSDoc 第 13 章）

### 5.1 四种内置策略类型

| 策略类 | 继承关系 | 信号格式 | 适用场景 | 与 AI 带单员的匹配度 |
|--------|---------|---------|---------|:------------------:|
| **BaseStrategy** | Strategy | order() 直接下单 | 简单规则策略 | ⭐⭐ 基础模板 |
| **PortfolioStrategy** | → BaseStrategy | Series(权重, index=[ID]) | 因子选股/组合构造 | ⭐⭐⭐⭐ 核心匹配 |
| &nbsp;├─ HierarchicalFiltration | → PortfolioStrategy | 纯参数配置 | 多层因子筛选 | ⭐⭐⭐⭐⭐ P1 MVP首选 |
| &nbsp;├─ OptimizerStrategy | → PortfolioStrategy | 依赖 PC | 数学优化组合 | ⭐⭐⭐⭐ P2 核心 |
| **TimingStrategy** | → BaseStrategy | Series(仓位, index=[ID]) | 择时/仓位管理 | ⭐⭐⭐ 辅助层 |

### 5.2 推荐 P1 → P2 策略演进路径

```
P1 (建立信任):
├── HierarchicalFiltrationStrategy
│   Layer 1: 市场筛选 (BTC dominance > 50%? 总市值 > $1B?)
│   Layer 2: 动量筛选 (20日 RSTR Top 20)
│   权重: 等权 / 流动性加权
│   再平衡: 周
│   ✅ 简单透明、可解释性强、适合榜单展示
│
P2 (上线跟单):
├── OptimizerStrategy (基于 Mean-Variance 或 Risk Budget)
│   预期收益来源: AI signal score (LLM + FM + 传统因子融合)
│   风险输入: Barra 风险模型 (Size/Beta/Momentum/Liquidity)
│   约束: 所内同步 (max_position / leverage / drawdown)
│   再平衡: 日/触发式
│   ✅ 数学严谨、支持多策略 ensemble、可与所内风控对齐
│
P3 (Copilot 协同):
├── TimingStrategy (辅助)
│   + OptimizerStrategy (主体)
│   + LLM Context 增强 (Foundation Model 通道 B)
│   ✅ 个性化、情境感知
```

---

## 六、绩效归因（对应 QSDoc 第 14 章）

### 6.1 Brinson 归因模型

四组合框架：

| 组合 | 定义 | 收益 |
|------|------|------|
| P1（基准） | $W^b, R^b$ | $R_{P1} = \sum W_i^b R_i^b$ |
| P2（主动配置） | $W^p, R^b$ | $R_{P2} = \sum W_i^p R_i^b$ |
| P3（主动选股） | $W^b, R^p$ | $R_{P3} = \sum W_i^b R_i^p$ |
| P4（实际） | $W^p, R^p$ | $R_{P4} = \sum W_i^p R_i^p$ |

**收益分解**：

$$R_{p-b} = \underbrace{R_{P2}-R_{P1}}_{\text{资产配置 AA}} + \underbrace{R_{P3}-R_{P1}}_{\text{个股选择 SS}} + \underbrace{R_{P4}-R_{P3}-R_{P2}+R_{P1}}_{\text{交互作用 IN}}$

**多期链接**（对数收益率法）：利用调整系数 $k_t/k$ 加权汇总各期归因结果。

### 6.2 FMP（因子模拟组合）归因

横截面回归：

$$\mathbf{w} = \mathbf{S} \cdot \boldsymbol{\beta} + \mathbf{u}$$

关键输出：
- **因子暴露** $\boldsymbol{\beta} = (\mathbf{S}'\mathbf{V}\mathbf{S})^{-1}\mathbf{S}'\mathbf{V}\mathbf{w}$
- **Alpha** = 残差项 $\mathbf{u}$（无法被因子解释的超额收益）
- **风险调整暴露**: $\text{diag}(\sqrt{\mathbf{S}'\mathbf{V}\mathbf{S}}) \cdot \boldsymbol{\beta}$
- **风险贡献**: $\frac{\sqrt{\mathbf{S}'\mathbf{V}\mathbf{w}} \cdot \boldsymbol{\beta}}{\sqrt{\mathbf{w}'\mathbf{V}\mathbf{w}}}$
- **收益贡献**: $\mathbf{r} \cdot \boldsymbol{\beta}$

> **应用场景**：AI 带单员的「为什么推荐这个」解释生成——通过 FMP 归因展示当前推荐的因子暴露结构和历史各因子的收益贡献。

---

## 七、方案引用索引表

| 技术方案章节 | 引用的 QSDoc 内容 | 具体位置 |
|-------------|------------------|---------|
| §1.1 产品目标 | 绩效指标定义 | §14 Brinson + §13 策略评估 |
| §3.3 组合优化 | 全部 6 种目标函数 + 约束集 | **§8 全章** |
| §4.1 榜单公式 | 分散度指标(DR/CR/HHI/熵) + IC/IR | §8.1.7 + §10 |
| §4.2 信号流水线 | 回测门禁 (walk-forward / 回归集) | §9 BackTest + §13 Strategy |
| §4.2 二次校验 | 风险模型约束输入 | **§7 Barra 全章** |
| §4.4 FM 双通道 | Ensemble = OptimizerStrategy | §13 OptimizerStrategy |
| §5 技术实施 | PortfolioConstructor API | §8.4 + §13.3 |
| §7 实验 | 因子有效性判断标准 | **§10 因子测试全章** |
| 附录 C 风险矩阵 | MV 六大问题 + Bias Test | §8.1.2 + §7.5 |

---

*本文档为 AI 带单员技术方案的量化理论支撑材料。所有公式、API 和方法论均引自 QSDoc (QuantStudio) 官方文档。加密市场落地时需对部分因子做适配性改造（见 §2.2 因子映射说明）。*
