# 架构与实施计划

## 产品形状（选择性复用 web3-trading，压缩为教学 MVP）

参考 [web3-trading](https://github.com/congde/web3-trading) 的 `src/backtest/` 与
`example/04_backtest_demo.py`，生产级项目通常分为：

```text
外部数据 → 研究/因子层 → 回测引擎 → 报告聚合 → API/界面
```

课程第一版先记录来源提交并确认代码授权，再选择性复用数据模型、纯指标函数、
策略接口、确定性回测循环与报告结构；去掉 API Key、MongoDB、实时接口、做空、
交易推荐与 Agent 编排：

```text
data/company.json + data/prices.csv
        │
        ├─► src/research/summary.py   带来源研究摘要
        ├─► src/backtest/runner.py    双均线回测（事件驱动引擎）
        └─► src/research/report.py      合并研究、回测与 warnings
                │
                ├─► app.py + src/web/static/   浏览器界面与 /api/report
                ├─► report_cli.py              终端复现（可选）
                └─► verify.py + tests/         自动验收与 Eval 输入
```

## Milestone 1：固定研究包（证据门）

- 交付 `data/company.json`（虚构公司、财报快照、三条来源卡）。
- 交付 `data/prices.csv`（35 个交易日收盘价，确定性样本）。
- 交付 [research-report.md](research-report.md)（用户与竞品调研，Go 决定）。
- **Gate**：每条事实可映射到 `source_id`；调研报告含 F/I/R/U 与竞品对照。

## Milestone 2：回测引擎

- 实现 `moving_average`、`run_backtest`、最大回撤与买卖信号。
- 默认参数 short=3、long=7；非法窗口抛出 `ValueError`。
- **Gate**：`tests/test_project.py` 覆盖确定性、指标字段与异常参数。

## Milestone 3：可用第一版

- `app.py` 提供 `/api/report?short=&long=` 与静态页面。
- 页面展示 warnings、来源卡、指标、权益曲线、交易记录与假设。
- **Gate**：`py scripts/course.py lab-10` 通过；用户能完成 [user-test.md](user-test.md)。

## Stop and rollback

在以下情况**立即停止**并回滚到上一个通过 milestone 的状态：

- 实现依赖交易所账户、钱包、实时行情密钥或自动下单；
- 删除/弱化「不进入实盘执行」「不能执行交易」等边界文案；
- 用未审查的爬虫数据替换固定样本且无法复现验收结果。

恢复方法：检出最后一次 `lab-10` 通过的提交，阅读 [playbook.md](playbook.md) 中的停止线。

## 技术选型记录

| 选项 | 优点 | 为何未选为第一版 |
|---|---|---|
| Python 标准库 + 固定文件 + 审查后复用 web3-trading 纯 Python 模块 | 可离线、全班同结果、减少重复实现 | **选用** |
| FastAPI + MongoDB（类 web3-trading） | 可扩展、接近生产 | 需要密钥与运维，偏离课程目标 |
| 纯 Excel / Notebook | 上手快 | 难以做浏览器用户测试与 API 验收 |

## 复用审计

本轮审查基于 `congde/web3-trading` 提交
`beea0d223f77a177c8a818ada432e3bd27d84367`。真正复制代码前，必须确认该提交的
授权条件并记录复制文件、适配修改与对应测试。

该提交的回测核心与示例已经先保存到
[`vendor/web3-trading/`](vendor/web3-trading/UPSTREAM.md)，作为后续改造的只读基线；
适配后的课程代码进入 `src/`，与 web3-trading 的 `src/` 布局对齐；`vendor/` 只保留只读对照。

完整 `vendor_runtime_sdk` 也已迁入基线目录。它为后续 Agent 会话、权限、工作区、
检查点与工作流改造提供起点，但当前 Web3 离线教学沙盒不直接启用其中需要 LLM、MCP、
Redis、MongoDB、GitLab 或生产凭证的集成。

前端基线 `src/web/templates/`、`src/web/static/` 与 `shared/` 也已迁入。后续先改造
研究看板与回测页的数据接口，再替换当前教学页；实时交易、实盘执行和下单页面不得
直接进入 Web3 离线教学沙盒第一版。

第二个上游 [ai-trading](https://github.com/johnnywuj81/ai-trading) 的 Apache-2.0
产品核心也已迁入 `vendor/ai-trading/`。融合时以其受限 DSL、事件驱动回测契约、
风险控制和 React Quant Atelier 前端为主要来源，以 web3-trading 的轻量指标、
报告和运行时模式为补充。具体取舍与顺序见
[`vendor/FUSION.md`](vendor/FUSION.md)。

融合代码已进入 `src/strategy_engine/dsl/`：策略代码在进入回测
前，可先执行 AST 安全校验与前视偏差检查；文件系统、进程、网络与动态执行能力
默认禁止。

第二轮融合已完成（详见 [`vendor/FUSION.md`](vendor/FUSION.md)）：

- `src/strategy_engine/backtest/`：来自 ai-trading 的事件驱动回测引擎；
- `src/backtest/runner.py`：教学回测入口，输出格式保持不变；
- `src/backtest/metrics.py`：来自 web3-trading 的 Sharpe 年化指标；
- `src/risk/simulation.py`：来自 ai-trading 的模拟风险门；
- `src/research/report.py`：统一输出 `fusion` 与 `risk_checks`；
- `app.py`：`POST /api/validate-strategy` 暴露受限 DSL 校验；
- `src/web/static/`：浏览器教学页。

| 候选代码 | 决定 | 进入课程项目前的适配 |
|---|---|---|
| `src/backtest/models.py`、`metrics.py` | 优先复用 | 收窄模型字段；补固定日线样本指标测试 |
| `src/backtest/strategies/base.py`、`ma_crossover.py` | 选择性复用 | 只保留多头模拟；统一 short/long 参数 |
| `src/backtest/engine.py` | 提取确定性核心循环 | 去掉做空、资金费率、实时数据和交易执行语义 |
| `example/04_backtest_demo.py` | 复用报告编排思路 | 适配为研究摘要 + 回测 + warnings |
| KuCoin/ValueScan、Mongo、交易推荐与下单代码 | 不复用 | 保持在课程安全边界之外 |

首个已完成适配：参考上游 `metrics.py::compute_calmar`，在
`src/backtest/runner.py` 中加入符合当前负回撤口径的 `calmar_ratio`，并用测试固定
口径差异。后续适配继续遵循“一次迁移一个行为、先测试再切换调用路径”。
