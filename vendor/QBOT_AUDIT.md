# Qbot 对照审计表

`vendor/Qbot/` 是只读上游基线，供课程补量化概念、对照经典策略规则使用。
可运行产品代码只进入仓库根目录 `src/`；**禁止** `from qbot…` 或 `import vendor.Qbot`。

上游记录见 [`Qbot/UPSTREAM.md`](Qbot/UPSTREAM.md)（当前 pin：`f0425ae`，2026-03-11）。

## 产品边界对照

| 维度 | Qbot | 本仓库 `src/` | 审计结论 |
|---|---|---|---|
| 课程目标 | 个人/机构量化机器人，偏 A 股实盘 | Codex 交付 + Web3 教学沙盒 | **概念参考，不替换产品** |
| 资产类别 | 股票、基金、期货、加密货币 | 虚构 Web3 样本 + dashboard K 线 | 迁移策略规则时需改数据源 |
| 实盘 / 下单 | `qbot/engine/trade/`、vnpy、easytrader | 明确禁止真实账户与下单 | **整包排除** |
| 数据获取 | tushare、akshare、efinance、Binance | `data/` 固定样本 + dashboard 快照 | **不迁入** |
| Python | 文档声明 3.8 / 3.9 | 课程 venv 现代 Python | 不引入 Qbot 全量依赖 |
| 许可证 | MIT | MIT + 课程契约 | 可借鉴逻辑；保留版权声明 |

## 模块级对照

| Qbot 路径 | 职责 | 本仓库对应 | 状态 | 说明 |
|---|---|---|---|---|
| `qbot/strategies/*_bt.py` | backtrader 经典策略脚本 | `src/backtest/rolling/strategies/` | **只读对照** | 借买卖规则，不借 backtrader 框架 |
| `qbot/strategies/sma_cross_strategy_bt.py` | 双均线金叉/死叉 | `MACrossoverStrategy` | **已 port** | Qbot：`CrossOver(SMA10,SMA30)`；本地：`ma_crossover.py` |
| `qbot/strategies/boll_strategy_bt.py` | 布林带均值回归 | `BollMeanReversionStrategy` | **已 port** | Qbot：跌破下轨买、突破上轨卖；本地：`boll_mean_reversion.py` |
| `qbot/strategies/adx_strategy.py` 等 | ADX/ARBR/KDJ 等 | `ADXMacdTrendStrategy` | **已 port** | 本地：`adx_macd_trend.py`（EMA13/55/89 + ADX + MACD柱） |
| `qbot/engine/backtest/backtest_base.py` | 向量化信号 × 收益 | — | **不迁入** | 无真实成交/手续费；前视风险高 |
| `qbot/engine/backtest/*_bt.py` | backtrader 示例 | `src/backtest/rolling/engine.py` | **不替换** | 本地为事件驱动 + walk-forward + trace |
| `qbot/engine/backtest/bitcoin_bt_example.py` | BTC + MACD + 止损 | dashboard K 线 + rolling 回测 | **概念参考** | 最接近 Web3 场景的 Qbot 示例 |
| `qbot/engine/backtest/live_trade_binance.py` | Binance 实盘 | — | **排除** | 违反课堂契约 |
| `pytrader/strategies/` | qlib / 深度学习 workflow | `src/factor_mining/` | 轻量替代 | 本地 GP/ML 因子挖掘更可控 |
| `qbot/gui/`、`main.py` | wxPython GUI | `src/web/` React | **不迁入** | 栈不同 |
| `docs/01-新手指引/` | 量化策略分类与原理 | `docs/v2/` 第 1–4 讲 | **延伸阅读** | 补「选股/择时/风控」全景 |
| `docs/02-经典策略/` | 策略说明文档 | `docs/v2/` 第 9、16–17 讲 | **延伸阅读** | 不复制 prose，只映射章节 |
| `requirements.txt` | backtrader、akshare、wxPython… | 根目录课程依赖 | **不合并** | 依赖过重且与 Python 版本冲突 |

## 回测引擎差异（关键）

| 检查项 | Qbot（典型 `*_bt.py`） | 本仓库 |
|---|---|---|
| 引擎 | backtrader `Cerebro.next()` | 自研 async 事件循环 |
| 成交模型 | broker 默认撮合 | 滑点、手续费、funding、动态滑点 |
| 指标计算 | backtrader indicators | 预计算 `compute_all_indicators()` |
| 样本外 / 滚动 | 多数脚本单窗口 | walk-forward、多策略比较 |
| 前视 / 污染 | 无系统检查 | `pollution.py`、DSL lookahead |
| 进度 / 可观测 | 脚本 print / plot | `EngineEvent`、trace、Web UI |

**结论**：Qbot 示例适合理解「策略长什么样」；本仓库引擎适合教「如何严谨验证」。

## 因子与 AI 对照

| 能力 | Qbot | 本仓库 | 建议 |
|---|---|---|---|
| 因子库 | alpha-101/191、deap 自动生成（文档宣称） | `src/factor_mining/` GP + ML | 继续以本地 pipeline 为准 |
| 模型 zoo | qlib、LSTM、RL、300+ 模型（`pytrader/`） | 教学级 ML + 表达式树 | **不迁入** qlib 全栈 |
| 因子评价 | alphalens（文档提及） | IC/RIC + train/test 切分 | 本地已满足第 21 讲实验 |
| LLM | FinGPT / ChatGPT（文档） | LLM 信号 + 边界卡（第 1 讲） | 保持「LLM 不替代数据」契约 |

## 策略规则 port 清单（若下一批迁入）

只 port **规则**，改写成 `backtest.rolling.strategies.base.Strategy` 子类：

| 优先级 | Qbot 参考文件 | 建议本地模块 | 价值 |
|---|---|---|---|
| P1 | `sma_cross_strategy_bt.py` | `ma_crossover.py` | **已完成** |
| P1 | `boll_strategy_bt.py` | `boll_mean_reversion.py` | **已完成** |
| P2 | `qbot/engine/backtest/macd_bt.py` / `bitcoin_bt_example.py` | `macd.py` + `macd_crossover.py` | **已完成** |
| P2 | `adx_strategy.py` | `adx_macd_trend.py` | **已完成** |
| P2 | `arbr_strategy.py` | — | 待定 | 可后续扩 `technical_signal` |
| P3 | `bitcoin_bt_example.py` | 文档样本 + 固定 BTC 快照 | Web3 叙事 |
| — | `lstm_strategy_bt.py` / `rl_strategy_bt.py` | — | **暂不迁入**（依赖与解释成本高） |

Port 时必须：

- 使用 `data/` 或 dashboard 快照，不用 tushare/akshare 在线拉数
- 加 `tests/` 覆盖确定性信号
- 在策略 metadata 中注明 Qbot 来源文件（MIT）

## 建议阅读路径（补基础知识）

| 顺序 | Qbot 资料 | 本仓库章节 | 目的 |
|---|---|---|---|
| 1 | `docs/01-新手指引/量化策略的分类和原理.md` | 第 1、2 讲 | 建立选股/择时/风控词汇 |
| 2 | `qbot/strategies/sma_cross_strategy_bt.py` | 第 4、17 讲 | 看懂双均线逻辑 |
| 3 | `docs/02-经典策略/` | 第 9、16 讲 | 指标 → 规则 |
| 4 | `qbot/engine/backtest/bitcoin_bt_example.py` | 第 18–21 讲 | 加密货币回测语境 |
| 5 | Qbot README 策略池表格 | 第 21 讲 factor mining | 理解「策略 vs 因子」 |

## Notebook 与书籍配图对照

Qbot 在 `vendor/Qbot/docs/notebook/` 下有 **15+ 个 Jupyter 笔记本**，以及
`pytrader/strategies/notebook/`、`pyfunds/backtest/doc/samples/` 中的同类示例。
它们的价值主要在 **matplotlib / backtrader / quantstats 的出图模式**，而不是
在线拉数或实盘依赖。

**2026-06 状态**：MVP 高价值 notebook 出图已全部落地到 `docs/v2/assets/generated/`
并在 `docs/v2/` 第 4、9、16–19、21 讲正文引用。一键重生成：

```powershell
py scripts/course.py teaching-plots
# 或：py scripts/generate_qbot_teaching_plots.py
```

扫描 notebook 出图密度（维护者用）：`py scripts/scan_qbot_notebooks.py`

### 本仓库配图路径

| 类型 | 工具 | 示例 | 适合 |
|---|---|---|---|
| 概念流程图 | PIL 脚本 | `scripts/generate_chapter01_figures.py`、`scripts/generate_chapter18_backtrader_flow.py` | 证据链、Cerebro 对照 |
| 量化教学曲线 | matplotlib 脚本 | `scripts/generate_qbot_teaching_plots.py` | 价格 / 信号 / 权益 / IC / 多窗口 |
| 产品界面实拍 | 浏览器截图 | `docs/v2/assets/回测详情.png` | Web UI、Dashboard |

Qbot notebook 最适合补第三类：**用固定样本画出「价格 → 信号 → 收益/权益」**，
对应第 4、9、16–19、21 讲正文里文字难以替代的层次。

### 已落地 notebook → 课程章节映射

| Qbot 参考 | 本地 PNG | 讲次 / 图号 | 状态 |
|---|---|---|---|
| `01-strategy.ipynb` 双均线三面板 | `chapter-04-price-signal-equity.png` | 第 4 讲 图 4-3 | **已插入正文** |
| `01-strategy.ipynb` 通道突破三面板 | `chapter-16-breakout-signal-equity.png` | 第 16 讲 图 16-3 | **已插入正文** |
| `average.ipynb` 买卖标记 | `chapter-17-ma-crossover-trades.png` | 第 17 讲 图 17-1 | **已插入正文** |
| `average.ipynb` + 事件引擎 | `chapter-18-event-backtest-combo.png` | 第 18 讲 图 18-2 | **已插入正文** |
| `bitcoin_bt_example.py` | `chapter-18-macd-trailing-backtest.png` | 第 18 讲 图 18-3 | **已插入正文** |
| `03-backtrader.ipynb` cerebro 装配 | `chapter-18-backtrader-vs-local.png` | 第 18 讲 图 18-1 | **已插入正文** |
| 指标同屏（本地 indicators） | `chapter-09-indicators-panel.png` | 第 9 讲 图 9-1 | **已插入正文** |
| `quantstats-rolling.ipynb` 多策略柱 | `chapter-19-metrics-comparison.png` | 第 19 讲 图 19-1 | **已插入正文** |
| `pandas.ipynb` equity/max_equity | `chapter-19-equity-drawdown.png` | 第 19 讲 图 19-2 | **已插入正文** |
| `02-alphalens.ipynb` IC 精简 | `chapter-21-factor-ic-panel.png` | 第 21 讲 图 21-5 | **已插入正文** |
| `quantstats-rolling.ipynb` rolling Sharpe | `chapter-21-rolling-sharpe.png` | 第 21 讲 图 21-6 | **已插入正文** |
| `compare_windows` CLI | `chapter-21-compare-windows.png` | 第 21 讲 图 21-1 | **已插入正文** |

图号登记：`scripts/asset_chapter_map.py`（`ASSET_USAGE`）。

### 待办 / 不纳入 MVP

| Qbot notebook | 主要出图 | 建议对应讲次 | 状态 |
|---|---|---|---|
| `docs/notebook/average.ipynb` / `choose_stock.ipynb` | `cerebro.plot()` 交互图 | — | 已由 matplotlib 静态图替代 |
| `docs/notebook/Pairs_Trading.ipynb` | 配对价差、协整检验图 | 进阶延伸阅读 | **暂不纳入** |
| `docs/notebook/Kurtosis Portfolio.ipynb` | 组合有效前沿 | 组合章节（若有） | **超出范围** |
| `docs/notebook/tushare.ipynb` | 数据获取示例 | 第 3 讲（反面教材） | 正文仍用 `data/` 固定样本 |
| `pytrader/strategies/workflow_by_code.ipynb` | qlib workflow | 第 21 讲 | 对照 `backtest_lab.py mine`，**不迁入 qlib** |

### 最值得借用的出图模式（`01-strategy.ipynb`）

该 notebook 用 pandas 在 **同一张图里分开三层**（与本仓库第 4 讲五对象高度一致）：

```text
面板 1：close + fast_sma + slow_sma     → 价格与指标
面板 2：signal（-1 / 0 / 1）            → 规则输出（还不是成交）
面板 3：returns vs strategy 累计和       → 仓位作用后的路径
```

关键教学点：`df["strategy"] = df["signal"].shift(1) * df["returns"]` ——
用 **shift(1)** 避免把当日信号用到当日收益，适合写进第 4 讲「信号 ≠ 即时成交」。

落地时应：

- 数据源改为 `data/prices.csv` 或 dashboard 离线 K 线，**禁止** notebook 里的 tushare / `000300.SH.csv`
- 输出 PNG 到 `docs/v2/assets/generated/`，在 `scripts/asset_chapter_map.py` 登记图号
- 图注写明：图示为教学样本、非投资建议；向量化简化 **不等于** 事件驱动引擎的成交明细
- 保留 MIT 出处注释（参考 `vendor/Qbot/docs/notebook/01-strategy.ipynb`）

### 不建议直接复用的 notebook 内容

| 内容 | 原因 |
|---|---|
| `%matplotlib widget` / 交互后端 | 书籍需静态 PNG |
| tushare / akshare 在线拉数 | 违反离线样本契约 |
| `cerebro.plot()` 全量依赖 backtrader | 与自研引擎双轨；可只借布局 |
| alphalens / quantstats 全量 tear sheet | 依赖重；摘 1–2 张核心图即可 |
| Dagster / Arctic / Mongo 段落 | 超出课程 MVP |

### 建议的配图工作流（Qbot 参考 + 本书规范）

```text
1. 在 vendor/Qbot/docs/notebook/ 找到目标 notebook（只读）
2. 提取「画什么」而非「import 什么」
3. 在 scripts/generate_qbot_teaching_plots.py（或 generate_chapter18_backtrader_flow.py）复刻
4. 在 scripts/asset_chapter_map.py 登记图号；正文写「能/不能证明什么」
5. py scripts/course.py teaching-plots 重生成 PNG
6. py scripts/course.py courseware-check 确认章节链接有效
```

### Notebook 目录索引（vendor 内）

```text
vendor/Qbot/docs/notebook/
├── 01-strategy.ipynb          # 双均线 + 三层教学图（首选）
├── 02-alphalens.ipynb         # 因子评价 tear sheet
├── 03-backtrader.ipynb        # backtrader 入门
├── average.ipynb              # backtrader 均线策略 + plot
├── choose_stock.ipynb         # 选股 + backtrader plot
├── quantstats-rolling.ipynb   # 滚动绩效报告
├── Pairs_Trading.ipynb        # 配对交易
├── tushare.ipynb              # 数据 API（仅作边界对照）
└── workflow_by_code.ipynb     # qlib workflow
```

## 暂留 `vendor/Qbot/`，不进入 `src/`

| Qbot 模块 | 原因 |
|---|---|
| `qbot/engine/trade/`、`easytrader`、`vnpy` | 实盘与券商接口 |
| `qbot/gui/`、`web/`（Qbot 原生） | wxPython / 独立 Web，与 `src/web` 重复 |
| `pytrader/` qlib workflows | 依赖重、难在教学 venv 复现 |
| `backtrader` 全系列 `*_bt.py` 作为引擎 | 与自研回测双轨维护 |
| `requirements.txt` 全量依赖 | akshare/wxPython/TA-Lib 等与课程环境冲突 |
| `monitoring.py`、AutoTrade CI | 自动化实盘，超出 PRD |

## 已完成 / 无需从 Qbot 再拿

| 本仓库模块 | 说明 |
|---|---|
| `src/strategy_engine/backtest/` | 事件驱动引擎（融合 ai-trading，优于 Qbot 向量化模板） |
| `src/backtest/rolling/` | 滚动回测、多策略、动态滑点 |
| `src/factor_mining/` | GP/ML 因子挖掘（Qbot 文档同级概念，实现更轻） |
| `src/strategy_engine/dsl/` | 受限策略 + 前视检查（Qbot 无对等物） |
| `src/risk/` | 回测后模拟风控门 |
| `src/web/` Backtests 页 | 可视化闭环 |
| `docs/v2/assets/generated/chapter-*.png` | Qbot notebook 模式教学图（12 张，见 `py scripts/course.py teaching-plots`） |

## 验收（维护者刷新 Qbot 后执行）

- [ ] `vendor/Qbot/UPSTREAM.md` 的 commit pin 已更新
- [ ] 未出现 `src/` → `vendor/Qbot` 的 import
- [ ] 课程正文若引用 Qbot 路径，文件在 pin 版本下仍存在
- [ ] 新 port 的策略有测试且只用离线样本
- [ ] `py scripts/course.py teaching-plots` 可重生成 12 张 `docs/v2/assets/generated/chapter-*.png`
- [ ] `py scripts/course.py verify` 仍通过

## 相关文档

- [`FUSION.md`](FUSION.md) — web3-trading / ai-trading 融合计划
- [`AI_TRADING_MIGRATION.md`](AI_TRADING_MIGRATION.md) — ai-trading 迁移清单
- [`../AGENTS.md`](../AGENTS.md) — `vendor/` 只读规则
