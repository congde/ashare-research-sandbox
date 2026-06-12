# 架构与实施计划

## 产品形状（借鉴 web3-trading，压缩为教学 MVP）

参考 [web3-trading](https://github.com/congde/web3-trading) 的 `example/04_backtest_demo.py`，生产级项目通常分为：

```text
外部数据 → 研究/因子层 → 回测引擎 → 报告聚合 → API/界面
```

课程第一版保留这条**逻辑分层**，但去掉 API Key、MongoDB 与 Agent 编排：

```text
data/company.json + data/prices.csv
        │
        ├─► a_share/research.py   带来源研究摘要
        ├─► a_share/backtest.py   双均线回测引擎
        └─► a_share/report.py     合并研究、回测与 warnings
                │
                ├─► app.py + static/     浏览器界面与 /api/report
                ├─► report_cli.py        终端复现（可选）
                └─► verify.py + tests/   自动验收与 Eval 输入
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

- 实现依赖证券账户、实时行情密钥或自动下单；
- 删除/弱化「不构成投资建议」「不能执行交易」等边界文案；
- 用未审查的爬虫数据替换固定样本且无法复现验收结果。

恢复方法：检出最后一次 `lab-10` 通过的提交，阅读 [playbook.md](playbook.md) 中的停止线。

## 技术选型记录

| 选项 | 优点 | 为何未选为第一版 |
|---|---|---|
| Python 标准库 + 固定文件 | 零依赖、可离线、全班同结果 | **选用** |
| FastAPI + MongoDB（类 web3-trading） | 可扩展、接近生产 | 需要密钥与运维，偏离课程目标 |
| 纯 Excel / Notebook | 上手快 | 难以做浏览器用户测试与 API 验收 |
