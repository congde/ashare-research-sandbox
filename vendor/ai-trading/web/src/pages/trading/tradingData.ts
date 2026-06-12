export interface StrategyRow {
  id: string;
  name: string;
  market: string;
  agent: string;
  horizon: string;
  status: "draft" | "backtesting" | "paper" | "live";
  risk: "low" | "medium" | "high";
  sharpe: number;
  maxDrawdown: number;
  pnl30d: number;
  evidence: string[];
}

export interface BacktestRow {
  id: string;
  strategy: string;
  market: string;
  window: string;
  status: "ready" | "running" | "review";
  pnl: number;
  sharpe: number;
  maxDrawdown: number;
  trades: number;
  equity: number[];
}

export interface RuntimeEvent {
  time: string;
  title: string;
  meta: string;
  tone: "profit" | "loss" | "neutral" | "ai";
}

export interface RiskRule {
  name: string;
  level: "profit" | "loss" | "neutral" | "ai";
  threshold: string;
  state: string;
  coverage: number;
}

export const strategyRows: StrategyRow[] = [
  {
    id: "str-momo-btc-4h",
    name: "BTC 4H Momentum Rotation",
    market: "Binance BTC/USDT",
    agent: "Strategy Agent",
    horizon: "4H",
    status: "paper",
    risk: "medium",
    sharpe: 1.82,
    maxDrawdown: -8.4,
    pnl30d: 12.7,
    evidence: ["ValueScan trend pulse", "Funding rate filter", "ATR stop"],
  },
  {
    id: "str-eth-vol-break",
    name: "ETH Volatility Breakout",
    market: "Binance ETH/USDT",
    agent: "Research Agent",
    horizon: "1H",
    status: "backtesting",
    risk: "high",
    sharpe: 1.16,
    maxDrawdown: -14.2,
    pnl30d: 5.4,
    evidence: ["Volatility expansion", "Liquidity guard", "Session filter"],
  },
  {
    id: "str-market-neutral",
    name: "Alt Basket Market Neutral",
    market: "Top 20 perp basket",
    agent: "Portfolio Agent",
    horizon: "1D",
    status: "draft",
    risk: "low",
    sharpe: 2.08,
    maxDrawdown: -5.6,
    pnl30d: 8.9,
    evidence: ["Cross-sectional rank", "Beta hedge", "Turnover cap"],
  },
  {
    id: "str-sol-rsi",
    name: "SOL RSI Mean Reversion",
    market: "OKX SOL/USDT",
    agent: "Risk Agent",
    horizon: "30M",
    status: "live",
    risk: "medium",
    sharpe: 1.43,
    maxDrawdown: -7.1,
    pnl30d: 3.2,
    evidence: ["Range detector", "Position throttle", "Kill switch"],
  },
];

export const backtestRows: BacktestRow[] = [
  {
    id: "bt-20260509-001",
    strategy: "BTC 4H Momentum Rotation",
    market: "BTC/USDT perp",
    window: "2024-01-01 至 2026-05-08",
    status: "ready",
    pnl: 42.8,
    sharpe: 1.82,
    maxDrawdown: -8.4,
    trades: 186,
    equity: [100, 104, 101, 110, 118, 116, 124, 132, 129, 143],
  },
  {
    id: "bt-20260509-002",
    strategy: "ETH Volatility Breakout",
    market: "ETH/USDT spot",
    window: "2024-06-01 至 2026-05-08",
    status: "running",
    pnl: 18.6,
    sharpe: 1.16,
    maxDrawdown: -14.2,
    trades: 241,
    equity: [100, 98, 106, 109, 103, 112, 118, 115, 123, 119],
  },
  {
    id: "bt-20260509-003",
    strategy: "Alt Basket Market Neutral",
    market: "Top 20 basket",
    window: "2023-01-01 至 2026-05-08",
    status: "review",
    pnl: 36.4,
    sharpe: 2.08,
    maxDrawdown: -5.6,
    trades: 912,
    equity: [100, 102, 105, 107, 111, 114, 116, 120, 122, 126],
  },
];

export const runtimeEvents: RuntimeEvent[] = [
  {
    time: "09:40",
    title: "SOL RSI Mean Reversion 降低仓位",
    meta: "Risk Agent 将单标的风险从 8.0% 下调至 5.5%",
    tone: "loss",
  },
  {
    time: "09:18",
    title: "ValueScan MCP 返回资金费率异常",
    meta: "BTC/USDT funding z-score 进入 95 分位",
    tone: "ai",
  },
  {
    time: "08:57",
    title: "Paper run 完成 3 笔模拟成交",
    meta: "平均滑点 1.8 bps，未触发熔断",
    tone: "profit",
  },
  {
    time: "08:30",
    title: "每日风险快照归档",
    meta: "账户、策略、交易所权限均通过巡检",
    tone: "neutral",
  },
];

export const riskRules: RiskRule[] = [
  {
    name: "组合最大回撤",
    level: "neutral",
    threshold: "12%",
    state: "当前 4.8%",
    coverage: 40,
  },
  {
    name: "单策略资金占用",
    level: "profit",
    threshold: "25%",
    state: "当前 17%",
    coverage: 68,
  },
  {
    name: "交易所只读/交易权限",
    level: "ai",
    threshold: "禁止提现",
    state: "5 个账户覆盖",
    coverage: 92,
  },
  {
    name: "异常行情熔断",
    level: "loss",
    threshold: "滑点 35 bps",
    state: "待接实盘网关",
    coverage: 24,
  },
];

export const accountPlaceholders = [
  {
    exchange: "binance",
    label: "testnet-main",
    fingerprint: "**** 7A9C",
    permissions: "spot / futures",
    state: "Paper trading",
  },
  {
    exchange: "okx",
    label: "research-readonly",
    fingerprint: "**** C219",
    permissions: "readonly",
    state: "Market data",
  },
];
