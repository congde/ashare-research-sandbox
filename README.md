# web3-quant-sandbox

**《Codex 与 LLM 量化交易实战》配套研究与模拟策略验证台**

可运行的 Web3 市场研究沙箱：固定离线样本、浏览器 UI 与命令行报告，贯穿 35 讲课程正文。产品代码在 `src/`，上游对照在 `vendor/`，教学样本在 `data/`，章节稿在 `docs/v2/`。

> **课堂契约**  
> 本仓库训练的是 Codex 交付与验收，不是 Web3 交易入门。案例资产 `示例协议（WEB3-DEMO/USDT）` 完全虚构；默认只读固定离线样本，不连接真实交易所账户或钱包，也不能执行真实交易。**不进入实盘执行。**

---

## 研究路径一览

从「看见市场」到「可验收交付」，浏览器侧栏与 CLI 覆盖同一条链路：

```text
市场总览 /trading  →  深度分析 /radar  →  策略回测 /backtests
        ↓                                      ↓
    数据源 /data-sources              策略 DSL /strategy
        ↓                                      ↓
    市场情报 /research  ← LLM 信号（可选）   风控中心 /risk
```

| 能力 | 入口 | 说明 |
|------|------|------|
| 市场总览 | `/trading` | 行情、资金、链上、AI 精选等面板 |
| 深度分析 | `/radar` | 结构化机会扫描与排序 |
| 策略回测 | `/backtests` | 双均线、滚动窗口、Walk-forward、组合与因子挖掘 |
| 模拟交易 | `/live-trading` | 基于样本的模拟执行界面（非真实下单） |
| 数据源 | `/data-sources` | 快照状态、来源配置与完整性 |
| 市场情报 | `/research` | 研究摘要、来源卡；可选 LLM 信号分析 |
| 策略 DSL | `/strategy` | AST 白名单、import 安全与前视偏差检查 |
| 风控中心 | `/risk` | 基于回测结果的规则化风险提示 |
| CLI 报告 | `report_cli.py` | 与 Web 同源 JSON / 摘要输出 |

命令行示例：

```powershell
python report_cli.py --format summary
python report_cli.py --format json --short 3 --long 7
```

---

## 快速开始

### 环境要求

- **Python 3.10+**（推荐用 `py` / `python3`）
- **Node.js 18+**（仅 `setup` 构建前端时需要）

### 1. 克隆与初始化

**Windows PowerShell**

```powershell
git clone https://github.com/congde/web3-quant-sandbox.git
cd web3-quant-sandbox
py scripts/course.py setup    # 首次克隆后执行一次
py app.py
```

**macOS / Linux**

```bash
git clone https://github.com/congde/web3-quant-sandbox.git
cd web3-quant-sandbox
make setup
python app.py
```

浏览器打开 **http://127.0.0.1:8765**（默认跳转到 `/trading`）。

`setup` 会创建 `.venv`、安装 `requirements.txt` 依赖，并在 `src/web/` 执行 `npm ci && npm run build`，产物写入 `src/web/static/`。

### 2. 端口冲突

若浏览器显示「Connection Failed」，通常是 **8765 端口被多个 `app.py` 占用**。先停止旧进程，再只启动一次：

```powershell
Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
py app.py
```

### 3. 前端热更新（开发）

```powershell
py app.py          # 终端 1：API 与静态资源
cd src/web
npm run dev        # 终端 2：Vite 开发服务器
```

---

## Dashboard 与离线数据

Dashboard、机会雷达、数据源面板均已内置在 `src/`，**只需启动本仓库**，无需单独运行 `vendor/web3-trading`。

### 三层数据加载

`src/dashboard/snapshot.py` 按以下顺序解析数据：

1. **快照层** — `data/dashboard/snapshots/*.json`（各数据集最新指针）；完整历史在 `snapshots/history/<dataset>/`
2. **样本层** — `data/dashboard/*.json`（仓库内置教学样本；快照缺失或不完整时回退）
3. **实时层** — 仅在配置了 API 密钥且 `DASHBOARD_DATA_MODE=auto|live` 时尝试公网 API

在线拉取成功时会自动追加历史快照；API 失败时优先展示最新落盘数据。完整性由 `src/dashboard/catalog.py` 校验——不完整的快照会被跳过并回退到完整样本。

### 目录结构

```text
data/dashboard/
├── manifest.json              # 数据集索引：来源、完整性、最近更新时间
├── ai_picks.json              # 内置样本（git 跟踪，断网可演示）
├── market_candles.json
├── opportunity_scan.json
├── …
└── snapshots/
    ├── ai_picks.json          # 各数据集最新指针
    ├── market_candles.json
    └── history/               # 每次在线成功追加，不覆盖
        ├── ai_picks/
        └── …
```

教学回测仍只用 `data/prices.csv` 与 `data/company.json` 等固定样本。

### 数据维护命令

| 命令 | 作用 |
|------|------|
| `py scripts/course.py snapshot` | 联网抓取 dashboard 数据，写入 `snapshots/` 并更新 `manifest.json` |
| `py scripts/course.py sync-fixtures` | 将完整快照复制到 `data/dashboard/*.json` 内置样本 |
| `py scripts/course.py save-offline-data` | 一键：`snapshot` + `sync-fixtures` |
| `py scripts/course.py build-fixtures` | 用快照或种子数据补齐不完整的内置样本 |
| `py dashboard_snapshot.py --mode auto` | 同上，可加 `--dry-run` 预览 |

推荐工作流：联网时执行一次 `snapshot` → 断网演示自动读快照 → 若快照也没有，读内置样本。

### 可选配置

复制 `.env.example` 为 `.env`，按需填写 API 密钥：

| 变量 | 默认 | 说明 |
|------|------|------|
| `DASHBOARD_DATA_MODE` | `offline` | `offline` / `auto` / `live` |
| `WEB3_TRADING_UPSTREAM` | `never` | 是否代理外部 web3-trading 实例 |
| `VS_OPEN_API_KEY` | — | ValueScan Open API |
| `DEX_API_KEY` | — | DexScan DEX 数据 |
| `OPENAI_API_KEY` | — | LLM 信号分析（DeepSeek / OpenAI 兼容） |

可选从 sibling `../web3-trading/.env` 复用同名密钥；`vendor/web3-trading` 仅作对照，默认不代理。

---

## 仓库结构

```text
web3-quant-sandbox/
├── src/                      # 可运行产品
│   ├── backtest/             # 指标、样本加载、滚动回测
│   ├── factor_mining/        # 因子挖掘（GP / ML）
│   ├── research/             # 研究摘要与统一报告
│   ├── risk/                 # 回测后模拟风控
│   ├── strategy_engine/      # 事件驱动引擎 + 受限 DSL
│   ├── dashboard/            # 行情、雷达、快照与 API 适配
│   └── web/                  # React 前端（Vite）→ 构建到 web/static/
├── vendor/                   # 只读上游：web3-trading、ai-trading、Qbot
├── data/                     # 固定离线教学样本
├── docs/v2/                  # 35 讲正文
├── docs/samples/             # 非代码练习用小样本
├── skills/                   # 课程示范 Skill
├── tests/                    # 项目验收测试
├── app.py                    # HTTP 入口（8765）
├── report_cli.py             # 命令行报告
├── verify.py                 # 产品 + 上游 baseline + pytest
└── scripts/course.py         # setup / verify / check / snapshot …
```

### 产品模块

| 模块 | 路径 | 作用 |
|------|------|------|
| 研究报告 | `src/research/` | 从 `data/` 组装可追溯研究摘要，合并回测与风控 |
| 回测 | `src/backtest/` | 双均线策略、Calmar / Sharpe 等指标、滚动窗口 |
| 因子挖掘 | `src/factor_mining/` | 表达式搜索、ML 特征与 mined factor 回测 |
| 策略引擎 | `src/strategy_engine/backtest/` | ai-trading 风格事件驱动回测循环 |
| 受限 DSL | `src/strategy_engine/dsl/` | AST 白名单、校验器、前视偏差检查 |
| 模拟风控 | `src/risk/` | 回测后的规则化风险提示 |
| Dashboard | `src/dashboard/` | ValueScan / DexScan / 交易所行情 / 机会雷达 + 快照离线 |
| Web UI | `src/web/` | Ant Design 侧栏 + Quant Atelier 设计系统 |

前端设计系统复用 `vendor/ai-trading/web`（WorkDAO 星空 / 玻璃态、`quant-atelier/` token、`TradingPageShell` 12 列布局）。融合决策与迁移清单见 [`vendor/FUSION.md`](vendor/FUSION.md)、[`vendor/AI_TRADING_MIGRATION.md`](vendor/AI_TRADING_MIGRATION.md)、[`vendor/QBOT_AUDIT.md`](vendor/QBOT_AUDIT.md)。

**`src/` 不得 import `vendor/`**；教学应用只使用根目录产品与 `data/` 样本。

---

## HTTP API（摘要）

`app.py` 在 **8765** 端口提供 REST 接口，完整路由见 `app.py` 与 `src/dashboard/api.py`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | SPA 入口 |
| GET | `/api/report?short=3&long=7` | 统一 JSON 报告 |
| POST | `/api/validate-strategy` | 请求体 `{"code": "..."}`，DSL 与前视偏差结果 |
| GET | `/api/dashboard/*` | AI 精选、资金、链上、DEX、机会扫描等 |
| GET | `/api/market/*` | K 线、Ticker、K 线分析 |
| GET/POST | `/api/dashboard/backtest/*` | 单次 / 对比 / 窗口 / Walk-forward / 组合回测 |
| GET/POST | `/api/dashboard/factor-mine*` | 因子挖掘与回测 |
| GET/POST | `/api/dashboard/llm-signal-analysis*` | LLM 结构化信号（异步 poll） |

---

## 开发与验收

| 命令 | 作用 |
|------|------|
| `py scripts/course.py setup` | 创建 venv、安装依赖、构建前端 |
| `py scripts/course.py verify` | 交付物检查 + 上游 baseline + pytest |
| `py scripts/course.py check` | verify + 资源审计 + 章节稿链接检查 |
| `py scripts/course.py courseware-check` | 章节稿与仓库一致性 |
| `py scripts/course.py teaching-plots` | 重生成全部课程教学图（Qbot 风格 + 各讲 PIL/流程图） |
| `py scripts/course.py print-figures` | 同上（`teaching-plots` 别名） |
| `py scripts/course.py snapshot` | 联网抓取 dashboard 快照 |
| `py scripts/course.py save-offline-data` | 快照 + 同步内置样本 |

macOS / Linux 等价：`make setup`、`make verify`、`make check`、`make teaching-plots`。

`verify` 确认交付物齐全、报告含必要边界文案与指标字段，并运行 `vendor/web3-trading`、`vendor/ai-trading` baseline 脚本及 `tests/`。无 web3-trading 时也可单独运行沙箱。

### 教学图

课程配图位于 `docs/v2/assets/` 与 `docs/v2/assets/generated/`。回测类 matplotlib 图固定使用 `data/prices.csv` 与 rolling 回测引擎，**不**调用 tushare / backtrader；流程图与证据链图由各讲专用脚本生成。

| 命令 | 作用 |
|------|------|
| `py scripts/course.py teaching-plots` | 一键重生成全部教学图（等同 `print-figures`） |
| `py scripts/generate_qbot_teaching_plots.py` | 第 4、9、16–19、21 讲 Qbot 风格 matplotlib 图（200 DPI） |
| `py scripts/generate_supplementary_diagrams.py` | 补充流程图与 draw.io 源文件 |
| `py scripts/scan_qbot_notebooks.py` | 扫描 `vendor/Qbot` notebook 出图模式（维护者） |

按讲次单独重生成：

| 脚本 | 覆盖讲次 |
|------|----------|
| `scripts/generate_chapter01_figures.py` | 第 1 讲 |
| `scripts/generate_chapter03_figures.py` | 第 3 讲 |
| `scripts/generate_chapter05_curve.py` | 第 5 讲（证据曲线） |
| `scripts/generate_chapter05_10_figures.py` | 第 5、7、8、10 讲 |
| `scripts/generate_chapter06_figures.py` / `generate_chapter06_curve.py` | 第 6 讲 |
| `scripts/generate_chapter07_snapshot_curve.py` | 第 7 讲（快照历史曲线） |
| `scripts/generate_chapter08_figures.py` … `generate_chapter12_figures.py` | 第 8–12 讲 |
| `scripts/generate_chapter13_figures.py` … `generate_chapter21_figures.py` | 第 13–21 讲 |
| `scripts/generate_chapter21_25_figures.py` | 第 22–25 讲 |
| `scripts/generate_chapter26_32_figures.py` | 第 26–32 讲 |
| `scripts/generate_chapter33_35_figures.py` | 第 33–35 讲 |

配图与章节映射见 `scripts/asset_chapter_map.py`；Qbot notebook 对照见 [`vendor/QBOT_AUDIT.md`](vendor/QBOT_AUDIT.md)。

---

## 课程文档

**正文**

- [35 讲目录](docs/v2/README.md)
- [Agent / 贡献约定](AGENTS.md)
- [产品边界与完成标准](product-brief.md)

**Codex 交付链**

| 文档 | 用途 |
|------|------|
| [product-brief.md](product-brief.md) | 产品边界、完成标准与待验证假设 |
| [research-brief.md](research-brief.md) | 调研目标、问题、证据边界与停止条件 |
| [research-acceptance.md](research-acceptance.md) | 调研证据规则与通过 / 拒绝 / 停止条件 |
| [context-pack.md](context-pack.md) | 验收条款到资料、权限、风险与缺口的映射 |
| [research-report.md](research-report.md) | 调研证据包 |
| [prd.md](prd.md) | 产品需求 |
| [plan.md](plan.md) | 实施计划 |
| [user-test.md](user-test.md) | 用户测试记录 |
| [eval-rubric.md](eval-rubric.md) | 评测量表 |
| [playbook.md](playbook.md) | 可复用 Codex 工作手册 |

---

## 上游与边界

| 目录 | 角色 |
|------|------|
| `vendor/web3-trading/` | 产品形态、回测指标、Dashboard baseline（只读对照） |
| `vendor/ai-trading/` | 受限 DSL、事件驱动引擎、风控、React 前端 baseline（只读对照） |
| `vendor/Qbot/` | Notebook 出图模式对照与教学图来源 |

更多工作约定见 [AGENTS.md](AGENTS.md)。
