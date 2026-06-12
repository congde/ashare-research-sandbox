# 量化选币系统 — 实现方案

## 一、策略范式：横截面初筛 → 时间序列确认

两阶段漏斗：

```
全市场 500+ 永续合约
      │
      ▼ Stage 1 ─────────────────────────────────────
      │  过滤链: 流动性 → 点差 → 市值 → 龄期
      │  500+ → ~30
      │  因子排名: ~30 → Top 10~15
      ▼
      ▼ Stage 2 ─────────────────────────────────────
      │  逐币时间序列确认
      │  Top 10~15 → 最终 5~8
      ▼
最终持仓
```

### Stage 1 过滤链

| 顺序 | 过滤器 | 公式 | 阈值 |
|------|--------|------|------|
| 1 | 流动性 | `V_24h = Σ volume_i × close_i` (过去 24h 所有 1h K 线) | `V_24h > $10M` |
| 2 | 点差 | `S = (ask - bid) / mid` × 100%，mid = (ask + bid) / 2 | `S < 0.05%` |
| 3 | 市值 | `MC = circulating_supply × last_price` | `MC > $50M` |
| 4 | 龄期 | `age = now - listing_timestamp` | `age > 30 days` |
| 5 | 排除稳定币 | 符号白名单匹配 | — |

### Stage 2 确认检查

逐币评估，产出**确认乘数** `M ∈ [0.5, 1.5]`：

**趋势对齐**

```
EMA(N) = α·P_t + (1-α)·EMA_{t-1}   其中 α = 2/(N+1)

Score_trend = { +15, if EMA50 > EMA200
              { -15, if EMA50 < EMA200
              {   0, if within 2% (无明确趋势)
```

**RSI 语境（门禁）**

```
RS = avg_gain_14 / avg_loss_14
RSI = 100 - 100/(1 + RS)

Gate: 做多时 RSI > 80 → Score_rsi = -30（过热门禁，不计入总分直接剔除）
      做多时 RSI < 30 → Score_rsi = +15（超卖反弹加分）
```

**量能确认**

```
V_ma_24 = (1/24) Σ_{i=t-23}^{t} V_i
VR = V_t / V_ma_24

Score_vol = { +10, if VR > 1.2
            {   0, otherwise
```

**突破检测**

```
HH_20 = max(high_{t-19}, ..., high_t)
VR = V_t / V_ma_24

Score_breakout = { +20, if P_t > HH_20 AND VR > 1.5 (放量突破)
                 { +10, if P_t > HH_20 AND VR ≤ 1.5 (无量突破，弱信号)
                 {   0, otherwise
```

**支撑临近**

```
sup = max( recent swing lows, VS dense-area support )

proximity = (P_t - sup) / P_t

Score_support = { +10, if proximity ∈ [0, 0.03]
                {   0, otherwise
```

**资金费率门禁**

```
FR = funding_rate（每 8 小时结算一次）

Gate: FR < -0.1% → 空头拥挤，做多风险高，降权或剔除
      FR > +0.05% → 多头拥挤，做空机会（暂不处理，纯多头策略跳过）
```

**确认乘数合成**

```
M_base = 1.0
M_base += 0.10 if Score_trend == +15
M_base -= 0.10 if Score_trend == -15
M_base += 0.05 if Score_vol == +10
M_base += 0.15 if Score_breakout == +20
M_base += 0.05 if Score_support == +10
M_base -= 0.20 if FR < -0.1%

M = clamp(M_base, 0.5, 1.5)
```

**最终得分**

```
S_final(i) = S_cs(i) × M(i)
```

其中 `S_cs(i)` 是横截面因子综合得分（见第三节），`M(i)` 是时间序列确认乘数。

---

## 二、主战场：KuCoin 永续合约

| 数据 | 来源 | 现有模块 |
|------|------|----------|
| 全市场 K 线 | KuCoin Futures `/api/v1/kline/query` | `kucoin_openapi_public.py` |
| 实时 ticker | KuCoin Futures `/api/v1/allTickers` | `dashboard_service.py` |
| 资金费率 | KuCoin 统一 API `/api/ua/v1/market/funding-rate` | `dashboard_service.py` |
| 链上数据、舆情 | ValueScan | `valuescan_open_api.py` |
| DEX 数据 | DexScan | `dexscan_open_api.py` |

---

## 三、特征权重：市场状态自适应

### 3.1 HMM 四状态识别

基于 BTC/USDT 1h K 线，滚动窗口 `T = 168`（一周）。

**特征向量（5 维）**

```
x_t = [r_t, σ_t, RSI_t, VP_t, skew_t]ᵀ

r_t    = ln(P_t / P_{t-1})                                  — 对数收益率
σ_t    = std(r_{t-23}, ..., r_t) × √168                     — 24h 滚动波动率（年化）
RSI_t  = 100 - 100/(1 + avg_gain_14 / avg_loss_14)          — 相对强弱
VP_t   = Σ(r_i⁺ × V_i) / Σ(|r_i| × V_i)                    — 量压比
         其中 r_i⁺ = max(r_i, 0)，求和窗口 i ∈ [t-23, t]
skew_t = (1/24) Σ [(r_i - μ̄)/σ̄]³                           — 24h 滚动偏度
```

**高斯 HMM**

状态数量 `K = 4`，协方差类型 `diag`：

```
A = [a_{ij}]  — K×K 状态转移矩阵，a_{ij} = P(S_{t+1}=j | S_t=i)
π = [π_i]     — 初始状态概率
μ_k           — 状态 k 的 5 维均值向量
Σ_k           — 状态 k 的 5 维对角协方差矩阵

P(x_t | S_t=k) = N(x_t; μ_k, Σ_k)
```

**训练**：Baum-Welch (EM) 算法，迭代至收敛或 max_iter=1000

```
E-step:  γ_t(k) = P(S_t=k | x_1,...,x_T, θ^{old})     (前向-后向)
          ξ_t(i,j) = P(S_t=i, S_{t+1}=j | x_1,...,x_T, θ^{old})

M-step:  μ_k^{new} = Σ_t γ_t(k)·x_t / Σ_t γ_t(k)
          Σ_k^{new} = Σ_t γ_t(k)·(x_t-μ_k)(x_t-μ_k)ᵀ / Σ_t γ_t(k)
          a_{ij}^{new} = Σ_t ξ_t(i,j) / Σ_t γ_t(i)
```

**状态后验标注**：无监督学习后，按每个状态的平均收益率和波动率排序标注：

| 条件 | 标签 |
|------|------|
| `mean(r) > 0` 且 `vol < median` | **牛市** Bull |
| `mean(r) < 0` 且 `vol > median` | **熊市** Bear |
| `|mean(r)| < ε` 且 `vol < median` | **震荡** Ranging |
| 其他 | **过渡** Transitional |

**实时推断**

新特征 `x_t` 到达时：

```
P(S_t = k | x_t) ∝ [Σ_i γ_{t-1}(i) · a_{ik}] · N(x_t; μ_k, Σ_k)

当前状态 = argmax_k P(S_t = k | x_t)
置信度  = max_k P(S_t = k | x_t)
```

每周用最新的 720 条 1h K 线重训练一次。

---

### 3.2 六因子计算

**标记**：
- `P_t`：当前价格
- `r_i = ln(P_i / P_{i-1})`：对数收益率
- `V_i`：成交量
- `N`：回看窗口

#### 动量因子

```
MOM = ((P_t / P_{t-21}) - 1) / σ_21

其中 σ_21 = std(r_{t-20}, ..., r_t) × √21  — 21 周期波动率标准化
```

除以波动率使不同波动率币种的动量可比。

```
Z_MOM = (MOM - μ_MOM) / σ_MOM             — 横截面 Z-score
```

#### 价值因子（NVT 倒数）

```
NVT = MarketCap / TransactionVolume_24h

VAL = 1 / NVT = TransactionVolume_24h / MarketCap

Z_VAL = (VAL - μ_VAL) / σ_VAL              — 横截面 Z-score，越高越低估
```

NVT 高 = 价格泡沫（市值远高于链上使用量），因此取倒数，越高越好。

#### 利差因子（Carry）

```
FR = funding_rate_current                    — 当前资金费率（每 8h 结算）
FR_annualized = FR × 3 × 365               — 年化（每天 3 次结算）
StakingYield = 0（永续合约无质押收益）

CARRY = FR_annualized                       — 正值 = 多头收钱

Z_CARRY = (CARRY - μ_CARRY) / σ_CARRY       — 横截面 Z-score
```

#### 增长因子

```
ΔADDR = (ActiveAddresses_t / ActiveAddresses_{t-720}) - 1    — 30 天活跃地址变化
ΔVOL  = (V_ma_168_t / V_ma_168_{t-168}) - 1                  — 7 天均量变化（30 天前 vs 现在）

GROWTH = 0.5 × ΔADDR + 0.5 × ΔVOL

Z_GROWTH = (GROWTH - μ_GROWTH) / σ_GROWTH
```

#### 流动性因子（Amihud 倒数）

```
ILLIQ_i = |r_i| / (V_i × P_i)               — Amihud 非流动性，i ∈ [t-335, t]（14 天 × 24h）

ILLIQ = mean(ILLIQ_{t-335}, ..., ILLIQ_t)

LIQ = -log(ILLIQ)                            — 取负对数使方向统一（越高流动性越好）

Z_LIQ = (LIQ - μ_LIQ) / σ_LIQ
```

#### 波动率因子

```
σ_20 = std(r_{t-19}, ..., r_t) × √168       — 20 周期年化波动率

VOL = -σ_20                                   — 负向：高波动是风险惩罚

Z_VOL = (VOL - μ_VOL) / σ_VOL
```

---

### 3.3 综合得分

**截面 Z-score → 百分位映射**

```
pct(factor_i) = Φ(Z_factor_i)                — 标准正态 CDF，输出 ∈ (0, 1)
```

**状态自适应权重混合**

4 状态 × 6 因子的权重矩阵 `W ∈ R^{4×6}`：

```
w_k ∈ R^6 = W 的第 k 行（状态 k 的权重）

如果置信度 c ≥ 0.8:
    w_active = w_k                           — 硬切换
否则:
    w_active = Σ_k p(k) × w_k                — 软混合（概率加权）
    其中 p(k) = P(S_t=k | x_t)
```

**综合得分**

```
S_cs(i) = 100 × ( Σ_f w_active[f] × pct(factor_f(i)) - 0.5 ) × 2
```

`pct ∈ (0,1)`，减 0.5 中心化，乘 200 映射到 `[-100, 100]`。

| 因子 | 牛市 | 熊市 | 震荡 | 过渡 |
|------|------|------|------|------|
| 动量 MOM | **0.30** | 0.10 | 0.15 | 0.15 |
| 价值 VAL | 0.10 | **0.25** | 0.10 | 0.10 |
| 利差 CARRY | 0.15 | **0.20** | 0.10 | 0.10 |
| 增长 GROWTH | **0.20** | 0.10 | 0.10 | 0.10 |
| 流动性 LIQ | 0.10 | **0.20** | 0.10 | 0.10 |
| 波动率 VOL | 0.15 | 0.15 | **0.45** | **0.45** |

---

## 四、调仓频率：每小时管线

```
T+0  min  并行拉取:
               BTC/USDT 168 条 1h K线（用于状态检测）
               全市场 Futures ticker（price, volume_24h, bid, ask）
               全市场 Funding Rate
T+2  min  增量 HMM 推断（用缓存的前向概率续算，不重训练）
T+3  min  过滤链执行:
               500 → 流动性 → 点差 → 市值 → 龄期 → ~30
T+4  min  因子计算: 30 个候选 × 6 因子 = 180 次计算
               每批 5 个并行（asyncio.Semaphore(5)），~4s 完成
T+8  min  时间序列确认: Top 15 逐币拉 4h/1h K线，计算 M(i)
               asyncio.gather 并行，~3s 完成
T+11 min  横截面排序 + TS 过滤 → 最终 5~8 个
T+12 min  拉取最终候选的 168 条 1h K线 → 协方差矩阵
T+14 min  风险平价优化 → 最终权重
T+15 min  产出 QuantSignal 并写入 Redis 缓存
```

**缓存策略**

| 数据 | TTL | Key 模式 |
|------|-----|----------|
| 全市场 ticker | 60s | `quant:tickers` |
| 资金费率 | 300s | `quant:funding:{symbol}` |
| HMM 前向概率 | 3600s | `quant:hmm:forward` |
| 因子计算结果 | 3600s | `quant:factor:{symbol}` |
| 最终信号 | 3600s | `quant:signal:latest` |

---

## 五、资金分配：风险平价（ERC）

### 5.1 收益序列

从最终选定的 `n` 个币种（`n ∈ [5, 8]`），各拉取 168 条 1h K 线：

```
r_i[t] = ln(close_i[t] / close_i[t-1])    t = 1..167

R ∈ R^{167 × n} = [r_1 | r_2 | ... | r_n]
```

### 5.2 Ledoit-Wolf 收缩协方差

```
S = (1/T) Rᵀ R                              — 样本协方差（T = 167）

F = (tr(S)/n) × I                           — 收缩目标（常相关模型去掉，用单位阵简化）

β = Σ_i Σ_j Var(s_ij) / Σ_i Σ_j (s_ij - f_ij)²

Σ_LW = (1 - β)·S + β·F                      — 收缩后的协方差
```

### 5.3 风险贡献

```
σ(w) = √(wᵀ Σ_LW w)                          — 组合波动率

∂σ/∂w_i = (Σ_LW w)_i / σ(w)                  — 边际风险贡献

RC_i = w_i × ∂σ/∂w_i = w_i × (Σ_LW w)_i / σ(w)  — 第 i 个资产的风险贡献

总风险: Σ_i RC_i = σ(w)                       — 风险贡献加总等于组合波动率
```

### 5.4 等风险贡献优化

目标使每个资产的风险贡献相等：

```
RC_i = RC_j  ∀i,j

即 w_i × (Σ_LW w)_i = w_j × (Σ_LW w)_j  ∀i,j
```

**循环坐标下降**（Spinu 2013）：

```
初始化: w = 1/n（等权）

迭代直到收敛:
  for i = 1..n:
    固定 w_j (j ≠ i)，求解 w_i 使得 RC_i = (1/n) × σ(w)

具体更新:
  RC_i(w) = w_i × (Σ_LW w)_i / σ(w)

  w_i^{new} = w_i × (target / RC_i(w))
  其中 target = σ(w) / n

收敛条件: max_i |RC_i - target| / σ(w) < 1e-6
```

**约束处理**：

```
每次坐标更新后：
  w_i = clamp(w_i, w_min, w_max)     其中 w_min = 0.02, w_max = 0.25

重新归一化：
  w = w / Σ w_i                       确保满仓
```

### 5.5 降级方案：逆波动率加权

当 `n < 3` 或协方差矩阵奇异（`cond(Σ_LW) > 1e10`）时：

```
σ_i = std(r_i) × √168                   — 年化波动率

w_i = (1/σ_i) / Σ_j (1/σ_j)

此即为 ERC 在"各资产不相关"假设下的特例。
```

### 5.6 输出示例

| 币种 | σ_annual | ERC 权重 | RC_i | $10,000 名义 |
|------|----------|----------|------|-------------|
| BTC | 45% | 22% | 20% | $2,200 |
| ETH | 60% | 16% | 20% | $1,600 |
| SOL | 80% | 12% | 20% | $1,200 |
| LINK | 95% | 10% | 20% | $1,000 |
| ARB | 110% | 7% | 20% | $700 |

---

## 六、回测策略适配

将上述管线包装为 `src/backtest/strategies/` 下的标准策略：

```python
@register
class QuantSelectionStrategy(Strategy):
    """
    两阶段选币策略：

    prepare():
      - 训练 HMM（用 BTC 历史数据）
      - 逐窗口预计算六因子
      - 逐窗口预计算协方差矩阵

    generate_signal(candles, idx, params, indicators):
      - 从预计算缓存读当前窗口因子
      - 用 HMM 推断当前状态 → 自适应权重混合
      - 横截面排序 → Top 10
      - 时间序列确认 → Top 5~8
      - 风险平价求解 → 最终权重
      - 返回 Signal(action=LONG, score=..., metadata={allocations: ...})
    """
```

对比基准：`TechnicalSignalStrategy`、`EnsembleStrategy`。

---

## 七、模块结构

```
src/quant/
├── models.py              # Pydantic: FactorScore, CoinCandidate, RegimeState,
│                          #   AdaptiveWeight, Allocation, QuantSignal
├── universe.py            # UniverseScreener: 过滤链 + 横截面排名
├── factors.py             # FactorEngine: 六因子计算 + Z-score + 百分位
├── regime_detector.py     # RegimeDetector: HMM 训练 + 推断 + 状态标注
├── adaptive_weights.py    # AdaptiveWeightEngine: 权重矩阵 + 软/硬混合
├── signal_scorer.py       # TimeSeriesConfirmer: 趋势/RSI/量/突破/支撑/资费
├── data_pipeline.py       # HourlyPipeline: 编排 + 缓存
├── risk_parity.py         # RiskParityOptimizer: Ledoit-Wolf + 坐标下降 + 降级
└── strategies/
    └── quant_selection.py # QuantSelectionStrategy: 回测适配器
```

复用现有：
- `src/web/api/dashboard_service.py` — 数据拉取
- `src/agent/tools/kucoin_openapi_public.py` — KuCoin API
- `src/backtest/indicators.py` — 技术指标预计算
- `src/backtest/registry.py` — 策略注册
- `src/dao/cache/redis.py` — Redis 缓存
- `src/signal_analysis/weight_optimizer.py` — 参考 EMA 平滑模式

新增依赖：`hmmlearn`（HMM 模型）、`numpy`（已有）。
