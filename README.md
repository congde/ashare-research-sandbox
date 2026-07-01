# web3-quant-sandbox

`web3-quant-sandbox` 是一个面向 Web3 量化研究、教学演示和本地模拟交易的开源沙箱项目。项目默认使用仓库内置的离线样本和本地快照运行，不连接真实交易账户，不管理钱包，也不会执行真实下单。

本仓库同时也是 Codex 交付课程的配套工作区。课程文档、示例命令和可运行代码需要保持一致：文档中提到的文件、命令和路径，都应当能在当前仓库中找到并运行。

## 开源协议

本项目遵循 MIT License 开源协议。

作者：袁从德

联系方式：congdeyuan@gmail.com

## 界面预览

![首页概览](image/首页概览.png)

![回测详情](image/回测详情.png)

## 主要能力

| 能力 | Web 路由 | 主要代码路径 | 说明 |
| --- | --- | --- | --- |
| 市场总览 | `/trading` | `src/dashboard/`, `src/web/src/pages/trading/DashboardPage.tsx` | 多资产行情、K 线、交易信号、风险摘要和执行入口 |
| 机会雷达 | `/radar` | `src/dashboard/opportunity.py` | 基于资金、趋势、链上和风险信号扫描机会 |
| 数据源监控 | `/data-sources` | `src/dashboard/snapshot.py`, `src/dashboard/catalog.py` | 查看样本、快照和在线 API 的状态 |
| 策略回测 | `/backtests` | `src/backtest/`, `src/backtest/rolling/` | 单策略、窗口对比、walk-forward、组合和稳健性检查 |
| 模拟交易 | `/live-trading` | `src/strategy_engine/`, `src/risk/` | 基于样本行情的模拟执行，不触达实盘 |
| 风控中心 | `/risk` | `src/risk/`, `src/backtest/audit/` | 回撤、止损、CPCV、PBO、DSR 等风险视角 |
| 策略 DSL | `/strategy` | `src/strategy_engine/dsl/` | AST 白名单、import 限制、前视偏差检查和编译验证 |
| 市场情报 | `/research` | `src/research/`, `src/dashboard/llm_signal.py` | 研究摘要、来源卡片和可选 LLM 信号分析 |
| CLI 报告 | 无 | `report_cli.py`, `src/research/report.py` | 输出 summary 或 JSON 研究报告 |

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- npm

### Windows PowerShell

```powershell
py scripts/course.py setup
py app.py
```

如果本机没有可用的 `py` 启动器，可以改用：

```powershell
python scripts/course.py setup
python app.py
```

启动后打开：

```text
http://127.0.0.1:8765
```

根路径会进入前端应用，主要页面包括 `/trading`、`/radar`、`/backtests`、`/risk`、`/strategy` 和 `/research`。

### macOS / Linux

```bash
make setup
python app.py
```

## 前端开发

生产模式由 `app.py` 直接服务 `src/web/static/`。开发前端时可以同时启动 Vite：

```powershell
py app.py
cd src/web
npm run dev
```

单独构建前端：

```powershell
cd src/web
npm run build
```

## 数据模式

Dashboard 数据主要来自三类来源：

1. `data/dashboard/snapshots/`：在线抓取后落盘的快照。
2. `data/dashboard/*.json`：仓库内置离线样本，断网也能运行。
3. 在线 API：仅在配置密钥并启用 `DASHBOARD_DATA_MODE=auto` 或 `DASHBOARD_DATA_MODE=live` 时使用。

常用数据命令：

| 命令 | 作用 |
| --- | --- |
| `py scripts/course.py snapshot` | 联网抓取 dashboard 数据并写入快照 |
| `py scripts/course.py sync-fixtures` | 将完整快照同步为内置样本 |
| `py scripts/course.py save-offline-data` | 抓取快照并同步离线样本 |
| `py scripts/course.py build-fixtures` | 用快照或种子数据补齐样本 |

可以复制 `.env.example` 为 `.env` 后按需配置。未配置 API 密钥时，应用仍会使用离线样本正常启动。

## 命令行报告

```powershell
python report_cli.py --format summary
python report_cli.py --format json --short 3 --long 7
```

报告内容来自 `src/research/report.py`，会合并样本数据、回测指标、风险检查和执行边界说明。

## 项目结构

```text
.
├── app.py                     # 本地 HTTP 服务，默认 127.0.0.1:8765
├── report_cli.py              # 命令行研究报告
├── verify.py                  # 产品验证入口
├── scripts/
│   └── course.py              # setup / verify / check / snapshot 等任务
├── src/
│   ├── backtest/              # 回测、滚动窗口、审计指标
│   ├── config/                # 环境变量和上游配置
│   ├── dashboard/             # 行情、快照、机会扫描、API 适配
│   ├── data/                  # point-in-time 数据工具
│   ├── factor_mining/         # 因子挖掘与因子回测
│   ├── research/              # 研究报告组装
│   ├── risk/                  # 风控规则和模拟边界
│   ├── strategy_engine/       # 事件驱动策略引擎与 DSL
│   ├── ta/                    # 技术指标工具
│   └── web/                   # React + Ant Design 前端
├── data/                      # 离线样本和 dashboard 快照
├── skills/                    # 课程中沉淀的 Codex 技能
├── tests/                     # pytest 测试
├── outputs/                   # 生成产物
└── reports/                   # 报告产物
```


## 验证

编辑期间建议运行：

```powershell
py scripts/course.py verify
```

仓库级变更完成前运行：

```powershell
py scripts/course.py check
```

`check` 会额外执行实现矩阵、vendor 漂移检查、资产审计和课程文档检查。编辑绘图脚本后，重新生成教学图：

```powershell
py scripts/course.py teaching-plots
```

## 安全边界

- 默认不连接真实交易所账户或钱包。
- `/live-trading` 是模拟交易界面，不是实盘交易终端。
- 策略 DSL 会做 AST 白名单、import 限制和前视偏差检查。
- 在线数据仅用于研究展示和回测输入，不构成投资建议。
- API 密钥只应通过本地 `.env` 读取，不应提交到仓库。

## 开发约定

- 产品代码放在 `src/`。
- 前端代码放在 `src/web/`。
- 测试放在 `tests/`。
- 离线样本放在 `data/`。
- 生成型文件优先放入 `outputs/` 或 `reports/`。
- 不要恢复已经删除的旧目录，例如 `app/`、`challenges/`、`harness-kit/` 或 `labs/`。
