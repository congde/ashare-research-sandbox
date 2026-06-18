# ashare-research-sandbox

**《Codex 与 LLM 量化交易实战》配套研究与模拟策略验证台**

本仓库是《Codex 与 LLM 量化交易实战》的配套工作区：可运行产品在根目录 `src/`，上游对照在 `vendor/`，固定样本在 `data/`，35 讲正文在 `docs/v2/`。

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

### Dashboard / 机会雷达（已内置）

交易总览、机会雷达、数据源面板均已集成在 `src/`，**只需启动本仓库**：

```powershell
py app.py
# 浏览器：http://127.0.0.1:8765/trading  或  /dashboard  或  /radar
```

左侧菜单「雷达」即机会雷达，无需单独启动 `vendor/web3-trading`。

数据加载顺序（`src/dashboard/snapshot.py`）：

1. **快照层** `data/dashboard/snapshots/*.json` — 最新落盘指针；完整历史在 `snapshots/history/<dataset>/`（优先）
2. **样本层** `data/dashboard/*.json` — 仓库内置教学样本（快照缺失或不完整时回退）
3. **实时层** — 仅在配置了 API 密钥且 `DASHBOARD_DATA_MODE=auto|live` 时尝试公网 API

数据源页或 API 在线拉取成功时会自动追加历史快照；API 失败时优先展示最新落盘数据。完整性由 `src/dashboard/catalog.py` 校验；不完整的快照会被跳过，自动回退到完整样本。

### 离线数据设计

```text
data/dashboard/
├── manifest.json              # 数据集索引：来源、完整性、最近更新时间
├── ai_picks.json              # 内置样本（git 跟踪，断网可演示）
├── market_candles.json
├── opportunity_scan.json
├── …
└── snapshots/                 # 运行时快照（联网后生成，优先于样本层）
    ├── ai_picks.json          # 各数据集最新指针
    ├── market_candles.json
    └── history/               # 可回溯历史（每次在线成功追加，不覆盖）
        ├── ai_picks/
        └── …
```

| 命令 | 作用 |
|------|------|
| `py scripts/course.py snapshot` | 联网抓取 8 类 dashboard 数据，写入 `snapshots/` 并更新 `manifest.json` |
| `py scripts/course.py sync-fixtures` | 将完整快照复制到 `data/dashboard/*.json` 内置样本（便于 git 提交、无 snapshots 也能演示） |
| `py scripts/course.py save-offline-data` | 一键：`snapshot` + `sync-fixtures` |
| `py scripts/course.py build-fixtures` | 用快照或种子数据补齐不完整的内置样本 |
| `py dashboard_snapshot.py --mode auto` | 同上，可 `--dry-run` 预览 |

推荐工作流：联网时执行一次 `snapshot` → 断网演示自动读快照；若快照也没有，读内置样本。

可选：从 sibling `../web3-trading/.env` 复用同名 API 密钥；`vendor/web3-trading` 仅作对照，默认不代理。

可选环境变量见 `.env.example`（`WEB3_TRADING_BASE_URL`、`WEB3_TRADING_UPSTREAM`）。

教学回测仍只用 `data/prices.csv` 固定样本，不构成投资建议。

### 课程教学图（Qbot notebook 模式）

第 4、9、16–19、21 讲正文引用的 matplotlib/PIL 教学图位于 `docs/v2/assets/generated/`。
数据源固定为 `data/prices.csv` 与 rolling 回测引擎输出，**不**调用 tushare / backtrader。

| 命令 | 作用 |
|------|------|
| `py scripts/course.py teaching-plots` | 重生成全部 12 张 Qbot 风格教学 PNG（200 DPI） |
| `py scripts/generate_chapter01_figures.py` | 重生成第 1 讲证据链 PIL 图 |
| `py scripts/scan_qbot_notebooks.py` | 扫描 `vendor/Qbot` notebook 出图模式（维护者） |

对照表与落地状态见 [`vendor/QBOT_AUDIT.md`](vendor/QBOT_AUDIT.md)「已落地 notebook → 课程章节映射」。

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
├── vendor/                   # 只读上游：web3-trading、ai-trading、Qbot
├── data/                     # 固定离线教学样本
├── docs/v2/                  # 35 讲正文
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
| Dashboard 数据层 | `src/dashboard/` | 有限复刻 web3-trading：ValueScan / DexScan / web3交易所 / 机会雷达 + 快照离线 |
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

融合决策与已迁移模块清单见 [`vendor/FUSION.md`](vendor/FUSION.md)；ai-trading 待迁移项见 [`vendor/AI_TRADING_MIGRATION.md`](vendor/AI_TRADING_MIGRATION.md)；Qbot 对照审计见 [`vendor/QBOT_AUDIT.md`](vendor/QBOT_AUDIT.md)。

## HTTP API

`app.py` 提供以下端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 教学页面 |
| GET | `/api/report?short=3&long=7` | 统一 JSON 报告 |
| POST | `/api/validate-strategy` | 请求体 `{"code": "..."}`，返回 DSL 与前视偏差结果 |

## 验收

```powershell
python scripts/course.py verify              # 交付物检查 + 上游 baseline + pytest
py scripts/course.py check               # verify + 章节稿链接检查
py scripts/course.py courseware-check
```

macOS / Linux 等价命令：`make verify`、`make check`、`make courseware-check`。

`verify` 会确认交付物齐全、报告包含必要边界文案与指标字段，并运行 `vendor/web3-trading` 与 `vendor/ai-trading` 的 baseline 脚本及 `tests/`。

## 课程文档

- [35 讲正文目录](docs/v2/README.md)
- [项目说明（原 lab README）](PROJECT.md)
- [Agent / 贡献约定](AGENTS.md)

## 交付物

课程贯穿案例的完整交付链：

| 文档 | 用途 |
|------|------|
| [product-brief.md](product-brief.md) | 产品边界、完成标准与待验证假设 |
| [research-brief.md](research-brief.md) | 调研目标、问题、证据边界与停止条件 |
| [research-acceptance.md](research-acceptance.md) | 调研证据规则与通过、拒绝、停止条件 |
| [context-pack.md](context-pack.md) | 验收条款到资料、权限、风险与缺口的映射 |
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
