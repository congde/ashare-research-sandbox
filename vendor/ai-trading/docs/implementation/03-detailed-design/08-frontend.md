# 03/08 · Frontend — Quant Atelier 设计与实现 ★

> 本章节由 **`frontend-design` skill** 协作产出。设计语言定名为 **"Quant Atelier"**——延伸 WorkDAO 赛博朋克 DNA,融合 Bloomberg Terminal 的数据密度与 Swiss 字体设计精度,服务 Alex / Bob / Charlie 三类用户 8h+/天的高强度使用场景。
>
> 本章节标注 **\[skill 输出\]** 的小节为 frontend-design skill 直接产出的设计方案,本仓库写作者将 skill 输出整合进 14 节工程实施模板。

---

## 1. 概述

实现 AI-Trading 平台的全部前端界面:Co-pilot 对话主页、策略库、回测可视化、实盘监控大屏、风控中心、账户管理、审计、设置共 8 大功能区。基于 React 19 + Vite + AntD 5 + Tailwind + 自研组件库,延伸 WorkDAO 设计系统。

## 2. 目标

- **8 大功能区** 全覆盖,公测 W22 上线
- **FCP < 1.5s / TTI < 3s / WS 实时刷新 < 200ms**
- **WCAG 2.1 AA** 全通过
- **中英双语** 默认 zh-CN / 切换 en-US
- **三屏适配**:Bridge ≥ 2560 / Desktop 1920 / iPad 监控只读 1024+
- **Density 三档**(Comfort/Compact/Dense)适配三类 Persona
- 直接复用 WorkDAO `web/` 设计系统底座(GlowCard / 主题变量)

## 3. 范围(v1.0 GA)

**做**:
- Co-pilot 三栏对话主页 + Monaco 代码编辑器
- 策略库 / 策略详情 5 Tab(Overview / Code / Backtest / Live / Risk)
- 回测可视化(K 线 + PNL + drawdown + 交易散点 + 月度热力)
- 实盘 Mission Bridge 大屏(positions / orderflow / risk events / heartbeat)
- 账户管理(API key 加密 + 多账号)
- 审计日志(timeline + 完整 snapshot 查看)
- 设置(profile / security / notifications / budget)
- Telegram 配置(连接 + 测试)

**不做**(v1.5+):
- 团队版协作 / 权限管理
- Mobile App(P1 仅做 mobile 告警 web 视图)
- 策略市集 fork / 公开策略浏览
- TradingView 信号 Webhook UI
- AI 优化器(Hyperopt) UI
- Research Agent 单独页面

## 4. 关联 ADR / US

- [ADR-0003](../../architecture/adrs/0003-react-vite-replace-nextjs.md) React + Vite
- [ADR-0001](../../architecture/adrs/0001-fork-workdao-baseline.md) Fork WorkDAO(继承 web/ 设计系统)
- US-AT-003, 010, 011-019, 021-029, 035, 036, 042, 047-052, 056

---

## 5. 设计要点 — Quant Atelier 设计语言

### 5.1 \[skill 输出\] 设计宣言

> **A quant trader's atelier at 3 AM.** Deep midnight base. Phosphor-green oscilloscope traces against void. Editorial serif headlines paired with ruthless monospace data. Cyberpunk's neon urgency, Swiss precision's restraint. The screen feels alive — a heartbeat of orderflow, a glow of conviction.

延伸 WorkDAO 赛博朋克 DNA,但用 **terminal-room sophistication** 替代夜店霓虹——更接近"瑞士字体工作室重设计的 Bloomberg Terminal"。专为日常 8 小时凝视设计。

**记忆点**:每个盈利数字都**真的发出磷光**,每个亏损数字流出洋红——你在阅读 P&L 之前先感受到它。

### 5.2 \[skill 输出\] 信息架构

```
/                               → /copilot
├── /copilot                    ★ 主入口(70% 流量)
│   ├── /copilot/c/:id          (会话)
│   └── /copilot/new
├── /strategies                 (库 + 网格视图)
│   └── /strategies/:id?tab=overview|code|backtest|live|risk
├── /backtests/:id              (深链可分享)
├── /live                       ★ Mission Bridge(Bob/Charlie 主战场)
│   └── ?view=positions|orderflow|events
├── /risk
│   ├── /risk/rules
│   └── /risk/events
├── /accounts
│   ├── /accounts/exchanges
│   └── /accounts/llm
├── /audit                      (只读 timeline)
└── /settings
    ├── /profile · /security · /notifications · /budget · /team[v1.5]
```

垂直左导航(60 / 220px),6 个一级图标。无深层 mega-menu。**Cmd+K** 打开 shadcn `Command` 命令面板——Bob/Charlie 80% 操作走这里。

---

## 6. \[skill 输出\] 设计 Token 体系

### 6.1 颜色

```css
:root {
  /* Surface */
  --bg-void:     #060A12;
  --bg-deep:     #0A0F1B;
  --bg-surface:  #0E1424;
  --bg-elevated: #161E33;

  /* Strokes */
  --line-faint:  #182142;
  --line-subtle: #21305A;
  --line-strong: #2E4378;
  --line-glow:   rgba(0,255,163,0.4);

  /* Text */
  --text-1: #ECF3FF;  --text-2: #93A4CC;
  --text-3: #5267A0;  --text-mute: #2E3B66;

  /* Semantic phosphors */
  --profit: #00FFA3;     --profit-glow: 0 0 14px rgba(0,255,163,.55);
  --loss:   #FF2D75;     --loss-glow:   0 0 14px rgba(255,45,117,.55);
  --warn:   #FFB627;
  --neutral: #00D4FF;    --neutral-glow: 0 0 14px rgba(0,212,255,.55);
  --ai:     #7B5BFF;     --ai-glow:     0 0 14px rgba(123,91,255,.55);

  --scanline: repeating-linear-gradient(0deg,
    transparent 0 2px, rgba(255,255,255,0.012) 2px 3px);
}

[data-density="compact"] { /* Bob */ --space-4: 12px; --space-6: 18px; }
[data-density="dense"]   { /* Charlie multi-monitor */ --space-4: 8px; --space-6: 14px; }
```

### 6.2 字体栈(刻意不用 Inter / Geist Mono)

```css
:root {
  --font-display: 'Reckless Neue', Georgia, serif;     /* italic, 戏剧性 */
  --font-body:    'Söhne', 'Helvetica Neue', sans-serif; /* Swiss 精度 */
  --font-mono:    'JetBrains Mono', 'SF Mono', monospace; /* 数据 */
}
```

| Token | 字体 | 大小 / LH | 用途 |
|---|---|---|---|
| display-xl | Reckless Italic 400 | 80 / 0.95 | 营销 hero / 大数字 |
| display-l | Reckless Italic 400 | 56 / 1 | 详情页大标题 |
| display-m | Reckless Italic 400 | 40 / 1.05 | Strategy card 标题 |
| h1 | Söhne 600 | 28 / 1.15 | 页头 |
| h2 | Söhne 600 | 22 / 1.2 | 子标题 |
| body-l | Söhne 400 | 16 / 1.55 | 长文(thesis) |
| body | Söhne 400 | 14 / 1.5 | 默认 |
| caption | Söhne 500 | 12 / uppercase | 标签 |
| mono-xl | JBM 500 | 32 / `tnum` | PNL hero |
| mono-l | JBM 500 | 18 / `tnum` | 持仓数值 |
| mono | JBM 400 | 13 / `tnum` | 表格 / 代码 |
| mono-xs | JBM 400 | 11 | 工具提示 / 指纹 |

`font-feature-settings: "tnum", "ss01"` 全局启用 — 表格数字 + 替代美元符。

### 6.3 间距 / 圆角 / 高度

- 4px 基线网格;`--radius: 4px / --radius-card: 8px`(刻意小圆角,技术感)
- 优先 **borders + glows** 替代阴影,卡片用 1px 细边 + 可选 inner-glow

---

## 7. \[skill 输出\] 关键页面线框

### 7.1 Co-pilot(主入口)

```
┌──────┬───────────────────────────────────┬─────────────────────────┐
│ rail │ ░░ AI ARCHITECT — phosphor frame  │ ░ CODE PREVIEW          │
│ AT◆  │                                   │                         │
│ □ □  │ ▸ user: BTC grid 18-25k           │ def on_tick(ctx,candle):│
│ ◇    │ ▸ agent: What grid count? 30…     │   df = fetch_ohlcv(...)│
│ ▷    │ ▸ user: 20                        │   sma_20 = ...          │
│ ⏵    │ ▸ agent: ▰▰▰▱ generating...       │ (Monaco editor)         │
│ ●    │   (SSE stream + typing cursor)    │                         │
│ ⚙    │                                   │ ── strategy_card ──     │
│      │ ┌─ STRATEGY CARD ── Reckless ─────│ thesis: ...             │
│  +   │ │ ▎ thesis  range trade via grid  │ valid_when: [...]       │
│ new  │ │ ▎ valid:  σ_30d > 30%, no FOMC  │                         │
│      │ │ ▎ invalid: breaks 25k +24h vol  │ ── backtest ──          │
│      │ └──────────────────────────────── │ PNL  +18.5% ↑glow       │
│      │                                   │ Sharpe 1.42             │
│      │ [ ▌ type message... ]      ↵      │ MDD  -12.3%             │
│      │                                   │ [ run dry-run → ]       │
└──────┴───────────────────────────────────┴─────────────────────────┘
  ░ density: compact  model: claude-opus-4.7  $0.034/msg  $4.20 today
```

### 7.2 Strategy Detail(5 Tab)

Tab 标签用 **Reckless Italic** 体——"Overview / Code / Backtest / Live / Risk",激活态加 phosphor 下划线。

Hero 区(Overview Tab):

```
"BTC Grid Captures Range" ── Reckless Italic 56px

+18.5%        $1,184.21 ↑       Sharpe 1.42
mono-xl glow  mono-l glow       mono-l

[1y PNL phosphor 折线 + drawdown 共享时间轴]

trades 1247 │ win 62% │ MDD -12.3% │ avg hold 16h
```

### 7.3 Live Mission Bridge

全屏 12 列 × 8 行 CSS Grid:

```
┌─────────────────────────────────────────────────────────────────┐
│ ■LIVE  ▍ all systems nominal │ PNL 24h +$842 +1.4% │ 3 events   │
├──────┬───────┬───────┬─────────┬──────────────────────────────┤
│ Pos. │ Order │ Strats│ Risk    │  Equity Curve (12×3)         │
│ Map  │ Flow  │ Live  │ Pulse   │   ─ phosphor line all stra   │
│      │       │       │         ├──────────────────────────────┤
│ 4×3  │ 4×4   │ 4×3   │ 4×2     │  Heartbeat ── tick latency   │
│      │       │       │         │  ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿       │
└──────┴───────┴───────┴─────────┴──────────────────────────────┘
```

- **Position Map**:热力图,cell size = 仓位占比,color lerp(loss → mute → profit)
- **Order Flow**:垂直滚动,新订单 200ms slide-down 动画
- **Strategies live**:240×100 GlowCard,迷你 phosphor sparkline
- **Risk Pulse**:事件时间轴,severity 色条;点击 → 抽屉展开 LLM 解释
- **Equity Curve**:全宽 phosphor 折线
- **Heartbeat**:1 行 SVG 正弦波,与 WS 心跳同步——**令人深感满足**

### 7.4 Backtest 可视化(垂直堆叠)

```
┌─ Equity ────────────────── phosphor line ──────────────┐
┌─ Drawdown ───────────── filled magenta ───────────────┐
┌─ Trades scatter ●●●●● ──────────────────────────────── ┐
┌─ Monthly heatmap (calendar, 5 颜色梯度) ──────────────┐
```

右边栏:可排序指标表。

### 7.5 Account / API Key Card

```
┌─────────────────────────────────────────────┐
│ ▘ BINANCE                          ✓ trade │
│                                    ✗ withdraw│
│ ╭─ key ╮                                   │
│ │ AKX_•••8f3a │ last verified 2h ago      │
│ ╰────────╯                                 │
│  3 strategies · 2 active                   │
│  [ test connection ]   [ rotate key ]      │
└─────────────────────────────────────────────┘
```

每家交易所自定义 monogram glyph(不用原始 logo,避免视觉噪音)。Permission badge 双色:`✓ spot trade` (cyan) / `✗ withdraw` (loss)。API key 仅显示指纹。

---

## 8. \[skill 输出\] 关键交互流程

| # | 流程 | 实现 |
|---|---|---|
| F1 | Strategy 流式生成 | SSE → 消息气泡 + typing cursor;代码到达 → 右栏滚顶,Monaco 渐进追加;backtest 触发 → summary 卡片从 skeleton morph 至真实数据 |
| F2 | Order 提交 | 点击 → cursor 涟漪 + 顶部飞起确认胶囊;失败 → 表单抖动 300ms + 内联 magenta 错误 |
| F3 | Risk halt 审批 | Critical → 全部策略卡片 magenta 脉冲边 1.2s + 顶部抽屉 modal,含解释 + 替代方案 + Approve/Reject;**15min 内不可关闭**,mono-xs 倒计时 |
| F4 | K 线 crosshair | 悬停 → 磷光 crosshair + mono tooltip(价 + 时);点击 → 标记;两标记 → 测量条(Δ 价 / Δ 时 / Δ %) |
| F5 | Density 切换 | `Cmd+\` 循环 Comfort → Compact → Dense,CSS var 即时切 |
| F6 | Cmd+K 命令面板 | shadcn `Command`,模糊匹配策略 / 账户 / 最近回测 / 设置 |
| F7 | 拖拽编辑风控阈值 | Risk 页:阈值是 inline mono number,**水平拖拽数字 scrub** 值(snap 0.5%) |
| F8 | 审计 timeline scrub | 顶部 scrubber + 下方按时间分组事件;点击 → modal 显示完整 snapshot JSON |
| F9 | "显示为表格"图表 a11y | 每个图表带按钮,切到 `<table>` 视图(屏读器) |
| F10 | Reduced motion | `prefers-reduced-motion: reduce` 关闭 breathe / scanline / aurora / ripple,glow 保留(静态 text-shadow) |

---

## 9. \[skill 输出\] 组件库取舍

| 组件 | 来源 | 备注 |
|---|---|---|
| Form / Table / Select / DatePicker / Drawer / Modal | **AntD 5** | 企业级数据控件,ConfigProvider override 主题 |
| Command palette | **shadcn `Command`** | AntD 无对应 |
| Toast | **Sonner** | 比 AntD message 精致 |
| Layout 原语 | **Tailwind** | 比 AntD Layout 更适合 mission bridge |
| K 线 | **lightweight-charts** | TradingView,金融原生 |
| PNL / drawdown | lightweight-charts (line + area) | 共享时间轴 |
| Trade scatter | **Recharts** | 灵活 |
| Heatmap | 自研 CSS Grid + d3-color | 简单胜过库 |
| Code editor | **Monaco** | Python tokenizer + 自定义 dark 主题 |
| 自研 | GlowCard / MonoNumber / EditorialHeading / ScannerBackground / PhosphorChart / AIAuroraInput / RiskPulseBadge / OrderRipple | 延伸 WorkDAO + 新建 |

### AntD 5 ConfigProvider Override(关键)

```tsx
<ConfigProvider theme={{
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: '#00FFA3', colorBgBase: '#060A12',
    colorBgContainer: '#0E1424', colorBgElevated: '#161E33',
    colorBorder: '#21305A', colorBorderSecondary: '#182142',
    colorText: '#ECF3FF', colorTextSecondary: '#93A4CC', colorTextTertiary: '#5267A0',
    colorSuccess: '#00FFA3', colorError: '#FF2D75',
    colorWarning: '#FFB627', colorInfo: '#00D4FF',
    fontFamily: '"Söhne", "Helvetica Neue", system-ui, sans-serif',
    fontFamilyCode: '"JetBrains Mono", monospace',
    borderRadius: 4, borderRadiusLG: 8, wireframe: false,
  },
  components: {
    Table:  { headerBg: '#0A0F1B', headerColor: '#5267A0',
              rowHoverBg: 'rgba(0,212,255,0.04)' },
    Button: { fontFamily: 'inherit', controlHeight: 36 },
    Input:  { paddingBlock: 9 },
  },
}}>
```

---

## 10. \[skill 输出\] 数据可视化方案

| 可视化 | 库 | 主题 |
|---|---|---|
| K 线 | lightweight-charts | 上 `--profit` / 下 `--loss`,vol 30% 透明,grid `--line-faint`,crosshair `--neutral` |
| PNL 折线 | lightweight-charts (line) | `--profit` 描边,下方梯度填充至 30% 透明 |
| Drawdown | lightweight-charts (area) | `--loss` 40% 填充,无描边 |
| Trade scatter | Recharts | x: 时间,y: pnl%,r: log(notional),色: win/loss |
| Order book depth | Recharts area | bid `--profit` / ask `--loss` 累积 |
| Position 热力 | 自研 CSS Grid | size = 仓位占比,color lerp |
| Risk events timeline | 自研 SVG | 横向滚动,severity 色条高度 [24, 16, 10, 4] |
| Monthly returns | CSS Grid 日历 | 5 stop 色梯度 |
| 策略 mini-spark | lightweight-charts mini | 60px,无轴,glow 关(性能) |
| Heartbeat | SVG + JS | 1Hz 正弦波,振幅随 tick 速率调制 |

性能预算:lightweight-charts 支持 > 100k candles;Recharts > 5k 点用 `largestTriangleThreeBuckets` 降采样。

---

## 11. \[skill 输出\] 响应式适配

| 模式 | 范围 | 行为 |
|---|---|---|
| **Bridge** | ≥ 2560(双 4K) | Mission Bridge 模式,最大密度 |
| **Desktop default** | 1920-2559 | 三栏 Co-pilot,两栏 Strategy Detail |
| **Compact desktop** | 1440-1919 | 右抽屉默认收起,rail 60px |
| **iPad 只读** | 1024-1439 | **Live 监控 + Audit 只读**;Co-pilot / Code / Order 提交 **禁用**,显示 "Use desktop" CTA |
| **Mobile 告警** [v1.5] | < 1024 | 仅 Risk events / Approval / Halt 按钮 |

编辑策略 / 跑回测 / 提交订单 = **桌面优先**,不为手机牺牲 Bob 的精度。

---

## 12. \[skill 输出\] 无障碍与 i18n

### a11y(WCAG 2.1 AA)

- 文本对比 ≥ 4.5:1,大字 ≥ 3:1,Stark + axe CI 验证
- 全键盘可达,焦点 `outline: 2px solid var(--neutral); outline-offset: 2px`
- 图表带 "Show as table" 切换(`<table>` 给屏读器);PNL ticker `aria-live="polite"`
- `prefers-reduced-motion: reduce` 关闭 breathe / scanline / aurora / ripple / number roll-up
- 颜色非唯一信息载体——状态总配图标 + 文字(▲ 盈 / ▼ 亏)
- 表单错误 `aria-describedby` + 提交时 focus-trap
- 风控 critical 事件 `aria-live="assertive"` 公告

### i18n(zh-CN / en-US)

- `i18next` namespace:`common / copilot / strategy / live / risk / audit / settings`
- 默认 zh-CN,设置页切换;数字千分位 / 小数点跟 locale
- `dayjs/locale/zh-cn` / `en` 时区
- mono 数字 `tnum` 保证多语言对齐
- Strategy Agent system prompt 跟随 UI 语言(卡片回复语言匹配)
- v2 RTL ready(Arabic):`dir` 属性切换已 mock 测试

---

## 13. 后端 API 契约

```typescript
// REST(axios + JWT)
GET  /api/v1/strategies                     → Strategy[]
GET  /api/v1/strategies/:id                 → StrategyDetail
POST /api/v1/strategies/:id/deploy          { mode: 'dry_run'|'live' }
POST /api/v1/agents/strategy_architect/runs body: AgentRunRequest
GET  /api/v1/agents/.../runs/:id/stream     SSE → tokens / tool_call / final
GET  /api/v1/backtests/:id                  → BacktestResult
GET  /api/v1/risk/events?since=...          → RiskEvent[]
POST /api/v1/approvals/:id/decide           { decision, reason }

// WebSocket(单连接 / 多 topic)
WSS  /api/v1/ws/realtime
  ⇒ subscribe { topics: ['market.binance.BTCUSDT.1m','order.user.<uuid>',
                         'position.user.<uuid>','risk.user.<uuid>'] }
  ⇐ events: market_candle | order_event | position_update | risk_event | approval_request
```

前端用 **TanStack Query** 管理 REST(缓存 + 重取),自研 WS hook(自动重连 + topic 订阅管理器)。

---

## 14. \[skill 输出\] 工程化与性能

```
vite                     build + HMR
react 19                 framework
typescript 5.5
tailwindcss 3.4          utility CSS
antd 5.x                 enterprise widgets
@tanstack/react-query 5  server state
zustand 4                client state(UI only)
react-router 7
i18next 23
framer-motion 11         number roll / 页面切换
lightweight-charts 4
recharts 2
@monaco-editor/react 4
sonner cmdk
clsx + tailwind-merge
zod                      运行时校验
playwright + vitest + @testing-library + storybook
```

**性能预算**:FCP < 1.5s / TTI < 3s / 初始 JS gzip < 300KB(分块 AntD + lazy charts) / WS UI 刷新感知 < 200ms。

### 测试金字塔

| 层 | 工具 | 覆盖 |
|---|---|---|
| Unit(hook / utils / formatter) | Vitest + RTL | ≥ 80% |
| Component | Storybook + Chromatic 视觉回归 | 全部 distinctive 组件 |
| Integration | Playwright + mock backend | 关键:copilot / deploy live / halt |
| E2E(全栈) | Playwright + docker-compose | login → create → dry-run → halt |
| a11y | axe-playwright CI | 关键页 0 violation |
| Bundle | bundlesize CI gate | PR 增 > 5% 阻塞 |

---

## 15. 实施路线(对齐 Sprint S0-S12)

| Sprint | 前端产出 |
|---|---|
| **S0** | Vite scaffold + AntD ConfigProvider + tokens + 字体(Reckless / Söhne / JBM)+ 6 原子组件 |
| **S5-S6** | **Co-pilot 主页**(最高视觉野心)+ Monaco + SSE hook |
| **S9** | 策略库 + 详情 5 Tab + 回测可视化栈 |
| **S10** | Live Mission Bridge + 账户卡片 + 设置 + 风控中心 |
| **S11** | a11y(axe)+ 响应式打磨 + bundle 优化 + i18n review |
| **S12** | ProductHunt 上线打磨:404 + 加载 splash + OG 图 + 营销落地页(独立 Astro) |

---

## 16. \[skill 输出\] "Hello World" — 验证审美

建议 S0 周末产出 `frontend-design-demo.html` 单页 demo,展示 token / 字体 / GlowCard / MonoNumber / EditorialHeading / phosphor PNL hero / scanline overlay。**60 秒内能感知整个审美方向**——动手前先打动团队。

骨架代码已由 frontend-design skill 提供(详见 skill 输出第 15 节)。

---

## 17. Open Questions

- v1.5 是否引入 `Reckless Neue` 商业字体许可($300 一次性)?或换 `Recoleta`(免费替代)?
- Mobile 告警 web 视图(< 1024)v1.0 GA 是否做最简版?(原计划推 v1.5)
- 营销落地页(`ai-trading.com`)单独建 Astro / Next.js?or 同 SPA?

---

## 18. 监控埋点

- `frontend_page_load_duration_ms{page}` Histogram
- `frontend_ws_reconnect_total` Counter
- `frontend_chart_render_duration_ms{chart_type}` Histogram
- `frontend_a11y_violation_total{rule}` Gauge(axe runtime + CI)

---

## 19. 安全与合规

- API key 输入框:`type="password"` + 不存浏览器(SubmitImmediately + KMS roundtrip)
- Cookie:`HttpOnly + Secure + SameSite=Strict`
- CSP 严格白名单:`default-src 'self'; connect-src 'self' wss://api.ai-trading.com`
- 不用第三方 analytics(用户行为数据隐私敏感)
- i18n 字符串避免硬编码用户数据(防 XSS)

---

## 20. 总结 — 差异化承诺

未来用户首次会话后会说的三句话:

1. *"等等,盈利数字真的会发光?"* —— 磷光 halo 让 P&L 可感
2. *"这玩意感觉是活的"* —— 心跳 + 呼吸 + 扫描线 + 极光让屏幕与市场同步律动
3. *"像 Bloomberg 终端被精心重设计过"* —— 编辑体斜体 + 严苛 mono + 高密度数据是不可被抄袭的

设计是 **opinionated 且 disciplined**。Alex 第一次会觉得 intimidating,但他用是因为 Bob 和 Charlie 用,而 Bob/Charlie 不愿放手。Alex 终会成长适配。Bob 的工具永远是 Bob 的。

**这是值得被记住的设计。**

---

## Changelog

| 版本 | 日期 | 变更 | 责任人 |
|------|------|------|--------|
| v1.0 | 2026-05-09 | 初版(frontend-design skill 协作产出) | 前端 + UI 设计 |
