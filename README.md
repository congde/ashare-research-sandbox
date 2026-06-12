# ashare-research-sandbox

**Codex 创意交付实战课 · Web3 研究与模拟策略验证台**

本仓库是 Codex 交付与验收课程的配套工作区：可运行产品在根目录 `src/`，上游对照在 `vendor/`，固定样本在 `data/`，20 讲正文在 `docs/v2/`。

> **课堂契约**：课程训练的是 Codex 交付与验收，不是 Web3 交易入门。案例资产 `示例协议（WEB3-DEMO/USDT）` 完全虚构；运行时只读取固定离线样本，不连接真实交易所账户或钱包，也不能执行真实交易。

## 你能做什么

浏览器打开本地页面后，可以完成一条完整的教学闭环：

1. **阅读研究摘要**：事实、解释、未知项与来源卡（`data/company.json`）。
2. **运行双均线回测**：在 35 日固定样本上对比策略与买入持有（`data/prices.csv`）。
3. **查看风险检查**：基于回测结果的模拟风控提示（来自 ai-trading 适配）。
4. **校验策略 DSL**：提交受限 Python 策略代码，检查 import 安全与前视偏差。

命令行也可直接生成同一份 JSON 报告：

```powershell
python report_cli.py --format summary
python report_cli.py --format json --short 3 --long 7
```

## 快速开始

**Windows PowerShell**

```powershell
git clone https://github.com/congde/ashare-research-sandbox.git
cd ashare-research-sandbox
py scripts/course.py setup    # 首次克隆后执行一次
py app.py
```

**macOS / Linux**

```bash
make setup                    # 首次克隆后执行一次
python app.py
```

浏览器访问 <http://127.0.0.1:8765>。

`setup` 会创建 `.venv`、安装 Python 依赖，并在 `src/web/` 构建 React 前端。若 `py` 不可用，把 `py` 换成 `python` 或 `python3`。构建前端需要 Node.js 18+。

若浏览器显示「Connection Failed」，通常是 **8765 端口被多个 `app.py` 占用**。先停止所有旧进程，再只启动一次：

```powershell
Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
py app.py
```

### 与 web3-trading 联调（完整行情服务）

**web3-trading** 是完整产品（FastAPI + Jinja 机会雷达），用 `python main.py` 启动；本仓库是**课程教学沙箱**（React + 固定回测样本），两者分工不同。

```powershell
# 终端 1 — 完整 web3-trading（读取其 .env + conf/default.yaml）
cd D:\work\gitee\web3-trading
python main.py
# 浏览器：http://127.0.0.1:1024/dashboard
# 端口以 web3-trading/.env 中 SERVER_PORT 为准（常见 1024 或 10240）

# 终端 2 — 课程沙箱
cd D:\work\gitee\ashare-research-sandbox
py app.py
# 浏览器：http://127.0.0.1:8765/trading
```

沙箱启动时会自动：

1. 读取 sibling 目录 `../web3-trading/.env` 与 `conf/default.yaml`
2. 若 web3-trading 已在运行，**优先代理**其 `/api/dashboard/*`、`/api/market/*`（与机会雷达同源）
3. 否则用 `.env` 里的密钥直连 ValueScan / DexScan / KuCoin
4. 再不行则回退 **`data/dashboard/snapshots/`** 已保存快照
5. 最后回退 `data/dashboard/*.json` 内置教学样本

**保存离线快照**（联网时执行一次，便于断网演示）：

```powershell
py scripts/course.py snapshot
# 或
py dashboard_snapshot.py
```

快照写入 `data/dashboard/snapshots/*.json`；`py app.py` 离线启动时会自动读取。

可选环境变量见 `.env.example`（`WEB3_TRADING_BASE_URL`、`WEB3_TRADING_UPSTREAM`）。

教学回测仍只用 `data/prices.csv` 固定样本，不构成投资建议。

无 web3-trading 时也可单独运行沙箱；`make verify` 不依赖上游服务。

## 仓库结构

```text
ashare-research-sandbox/
├── src/                      # 可运行产品
│   ├── backtest/             # 指标、样本加载、回测入口
│   ├── research/             # 研究摘要与统一报告
│   ├── risk/                 # 回测后模拟风控检查
│   ├── strategy_engine/      # 事件驱动引擎 + 受限 DSL
│   └── web/                  # React 前端（Vite）→ 构建到 web/static/
├── vendor/                   # 只读上游：web3-trading、ai-trading
├── data/                     # 固定离线教学样本
├── docs/v2/                  # 20 讲正文
├── docs/samples/             # 非代码练习用的小样本
├── skills/                   # 课程示范 Skill（repo-readiness、weekly-brief）
├── tests/                    # 项目验收测试
├── app.py                    # HTTP 入口（8765）
├── report_cli.py             # 命令行报告
├── verify.py                 # 产品 + 上游 baseline + pytest
├── scripts/course.py         # setup / verify / check
└── product-brief.md …        # 交付物（见下文）
```

## 产品模块

| 模块 | 路径 | 作用 |
|------|------|------|
| 研究报告 | `src/research/` | 从 `data/` 组装可追溯研究摘要，并合并回测与风控 |
| 回测 | `src/backtest/` | 双均线策略、Calmar / Sharpe 等指标 |
| 策略引擎 | `src/strategy_engine/backtest/` | ai-trading 风格事件驱动回测循环 |
| 受限 DSL | `src/strategy_engine/dsl/` | AST 白名单、校验器、前视偏差检查 |
| 模拟风控 | `src/risk/` | 回测后的规则化风险提示 |
| Dashboard 数据层 | `src/dashboard/` | 有限复刻 web3-trading：ValueScan / DexScan / KuCoin / 机会雷达 + 快照离线 |
| Web UI | `src/web/` → `src/web/static/` | ai-trading React 壳：Ant Design 侧栏 + Quant Atelier + TradingPageShell |

### 前端开发

源码在 `src/web/`，直接复用 `vendor/ai-trading/web` 的设计系统：

- `index.css` — WorkDAO 星空 / 玻璃态 / Ant Design 覆盖
- `quant-atelier/` — MonoNumber、QuantGlowCard、设计 token
- `pages/trading/TradingPageShell.tsx` + `trading.css` — 12 列量化面板布局
- `layouts/MainLayout.tsx` — Ant Design 可折叠侧栏（无登录 / 钱包 / Johnny）

页面路由对齐 ai-trading：`/trading` 总览、`/backtests` 回测、`/risk` 风控、`/research` 情报、`/strategy` DSL。数据仍来自 `app.py` 的 `/api/report` 与 `/api/validate-strategy`。

`setup` / `verify` 会自动 `npm ci && npm run build`。开发时：

```powershell
py app.py
cd src/web
npm run dev
```

融合决策与已迁移模块清单见 [`vendor/FUSION.md`](vendor/FUSION.md)；ai-trading 待迁移项见 [`vendor/AI_TRADING_MIGRATION.md`](vendor/AI_TRADING_MIGRATION.md)。

## HTTP API

`app.py` 提供以下端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 教学页面 |
| GET | `/api/report?short=3&long=7` | 统一 JSON 报告 |
| POST | `/api/validate-strategy` | 请求体 `{"code": "..."}`，返回 DSL 与前视偏差结果 |

## 验收

```powershell
py scripts/course.py verify              # 交付物检查 + 上游 baseline + pytest
py scripts/course.py check               # verify + 章节稿链接检查
py scripts/course.py courseware-check
```

macOS / Linux 等价命令：`make verify`、`make check`、`make courseware-check`。

`verify` 会确认交付物齐全、报告包含必要边界文案与指标字段，并运行 `vendor/web3-trading` 与 `vendor/ai-trading` 的 baseline 脚本及 `tests/`。

## 课程文档

- [20 讲正文目录](docs/v2/README.md)
- [项目说明（原 lab README）](PROJECT.md)
- [Agent / 贡献约定](AGENTS.md)

## 交付物

课程贯穿案例的完整交付链：

| 文档 | 用途 |
|------|------|
| [product-brief.md](product-brief.md) | 产品边界与完成标准 |
| [research-report.md](research-report.md) | 调研证据包 |
| [prd.md](prd.md) | 产品需求 |
| [plan.md](plan.md) | 实施计划 |
| [user-test.md](user-test.md) | 用户测试记录 |
| [eval-rubric.md](eval-rubric.md) | 评测量表 |
| [playbook.md](playbook.md) | 可复用 Codex 工作手册 |

## 上游与边界

- `vendor/web3-trading/`：产品形态、回测指标、Jinja 前端 baseline（只读对照）。
- `vendor/ai-trading/`：受限 DSL、事件驱动引擎、风控、React 前端 baseline（只读对照）。
- **`src/` 不得 import `vendor/`**；教学应用只使用根目录产品与 `data/` 样本。

更多细节见 [PROJECT.md](PROJECT.md)。
