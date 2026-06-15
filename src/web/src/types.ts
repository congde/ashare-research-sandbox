export interface ResearchFact {
  claim: string;
  source_id: string;
}

export interface ResearchSource {
  id: string;
  date: string;
  title: string;
  evidence: string;
}

export interface ResearchSummary {
  company: string;
  fictional: boolean;
  facts: ResearchFact[];
  interpretation: string;
  unknowns: string[];
  sources: ResearchSource[];
}

export interface BacktestMetrics {
  strategy_return_pct: number;
  buy_hold_return_pct: number;
  maximum_drawdown_pct: number;
  calmar_ratio: number;
  sharpe_ratio: number;
  trade_count: number;
  final_equity: number;
}

export interface CurvePoint {
  date: string;
  equity: number;
  close: number;
  short_ma?: number | null;
  long_ma?: number | null;
}

export interface Trade {
  date: string;
  action: string;
  price: number;
}

export interface BacktestResult {
  metrics: BacktestMetrics;
  curve: CurvePoint[];
  trades: Trade[];
  assumptions: string[];
  engine: string;
  risk_rejections?: RiskRejection[];
  risk_rules?: string[];
}

export interface RiskCheck {
  rule_id: string;
  message: string;
  severity: string;
  source?: string;
  phase?: "pre_trade" | "post_backtest";
  count?: number;
}

export interface RiskRejection {
  date: string;
  symbol: string;
  side: string;
  rule_id: string;
  reason: string;
}

export interface FusionInfo {
  product_shape: string;
  dsl_and_risk: string;
  adapted_modules: string[];
  risk_rules?: string[];
}

export interface ReportPayload {
  research: ResearchSummary;
  backtest: BacktestResult;
  risk_checks: RiskCheck[];
  fusion: FusionInfo;
  warnings: string[];
}

export interface ValidationIssue {
  line: number;
  col: number;
  rule: string;
  message: string;
  suggestion?: string;
  severity?: string;
}

export interface StrategyValidationResult {
  valid: boolean;
  validation: {
    valid: boolean;
    errors: ValidationIssue[];
  };
  lookahead: {
    clean: boolean;
    findings: ValidationIssue[];
  };
  source: string;
  error?: string;
}

export interface DashboardPickItem {
  symbol?: string;
  score?: number;
  title?: string;
  summary?: string;
  vsTokenId?: string;
}

export interface DashboardAiPicks {
  ok: boolean;
  source?: string;
  live_error?: boolean;
  cached_at?: string;
  chance?: DashboardPickItem[];
  risk?: DashboardPickItem[];
  funds?: DashboardPickItem[];
  message?: string;
}

export interface DashboardOnchain {
  ok: boolean;
  source?: string;
  symbol?: string;
  marketSentiment?: {
    fearGreed?: {
      value?: number;
      label?: string;
      change?: number;
    };
  };
}

export interface DashboardSectorFund {
  ok: boolean;
  source?: string;
  sectors?: Array<{
    tag?: string;
    tagsSimplified?: string;
    categoriesTradeDataList?: Array<{ timeRange?: string; tradeInflow?: number }>;
  }>;
}

export interface DashboardSourcesStatus {
  ok: boolean;
  env?: {
    valuescan?: boolean;
    dexscan?: boolean;
    web3_exchange_public?: boolean;
    fear_greed_public?: boolean;
    data_mode?: string;
    upstream?: {
      base_url?: string | null;
      dashboard_url?: string | null;
      available?: boolean;
    };
  };
  dashboard_url?: string | null;
  probes?: Array<{ id: string; name: string; ok: boolean; source?: string; error?: string }>;
}

export interface RuntimeConfig {
  ok: boolean;
  upstream?: {
    base_url?: string | null;
    dashboard_url?: string | null;
    available?: boolean;
    mode?: string;
  };
  symbols?: {
    watch?: string[];
    primary_pair?: string;
  };
}

export interface MarketCandlesPayload {
  ok: boolean;
  source?: string;
  symbol?: string;
  curve?: CurvePoint[];
}

export interface OpportunityItem {
  symbol: string;
  pair?: string;
  signal?: string;
  label?: string;
  score?: number;
  confidence?: number;
  change24h?: number;
  volume24h?: number;
  keyReasons?: string[];
  rank?: number;
  summary?: string;
}

export interface OpportunityScanPayload {
  ok: boolean;
  source?: string;
  scanTime?: string;
  totalScanned?: number;
  topK?: number;
  opportunities?: OpportunityItem[];
  marketOverview?: string;
  scanDurationMs?: number;
  engine?: string;
  message?: string;
}

export interface KlineCandle {
  tsSec: number;
  date?: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
}

export interface KlineVerdict {
  action?: string;
  actionLabel?: string;
  direction?: string;
  score?: number;
  confidence?: number;
  reasons?: string[];
}

export interface KlineMetrics {
  latestClose?: number;
  latestOpen?: number;
  latestHigh?: number;
  latestLow?: number;
  latestVolume?: number;
  candleChangeRatePct?: number;
  sma20?: number | null;
  sma60?: number | null;
  support20?: number;
  resistance20?: number;
  volatilityPct?: number;
  rangePositionPct?: number;
  rsi?: number | null;
  bbUpper?: number | null;
  bbLower?: number | null;
  bbWidth?: number | null;
  bbPctB?: number | null;
  atr?: number | null;
  atrPct?: number | null;
  regime?: string;
  breakout?: string;
}

export interface KlineAnalysisPayload {
  ok: boolean;
  source?: string;
  symbol?: string;
  type?: string;
  trend?: string;
  trendKey?: string;
  verdict?: KlineVerdict;
  metrics?: KlineMetrics;
  candles?: KlineCandle[];
  message?: string;
  error?: string;
}

export interface TradePlan {
  symbol?: string;
  direction?: string;
  entryLow?: number;
  entryHigh?: number;
  stopLoss?: number;
  target1?: number;
  target2?: number;
  rr1?: number;
  rr2?: number;
}

export interface SignalKlineFrame {
  trend?: string;
  trendKey?: string;
  score?: number;
  rsi?: number | null;
}

export interface SignalLogicStep {
  step: number;
  title: string;
  status?: string;
  detail?: string;
  note?: string;
  summary?: string;
  badges?: string[];
  dimensions?: Array<{ name: string; bias: string; score: number }>;
  rr1?: number;
  rr2?: number;
}

export interface SignalAnalysisPayload {
  ok: boolean;
  engine?: string;
  engineMeta?: { provider?: string; model?: string; displayModel?: string; note?: string };
  symbol?: string;
  pair?: string;
  signal?: string;
  signalLabel?: string;
  confidence?: number;
  score?: number;
  summary?: string;
  reasons?: string[];
  tradePlan?: TradePlan;
  market?: {
    symbol?: string;
    pair?: string;
    price?: number;
    changeRate24h?: number;
    high24h?: number;
    low24h?: number;
    volValue24h?: number;
  };
  kline?: Record<string, SignalKlineFrame>;
  analysis?: {
    marketState?: string;
    executionReadiness?: string;
    marketStateDetail?: string;
    coverage?: string;
  };
  onchainMetrics?: { fearGreed?: number | null };
  logicFlow?: SignalLogicStep[];
  message?: string;
  error?: string;
}

export interface RollingBacktestStrategy {
  name: string;
  displayName: string;
}

export interface RollingEquityPoint {
  idx: number;
  ts: number;
  close: number;
  equity: number;
  drawdown: number;
  inPosition?: boolean;
}

export interface RollingTrade {
  entryIdx: number;
  entryTs: number;
  entryPrice: number;
  direction: string;
  exitIdx: number;
  exitTs: number;
  exitPrice: number;
  pnlPct: number;
  exitReason: string;
  barsHeld: number;
}

export interface RollingBacktestPayload {
  ok: boolean;
  engine?: string;
  symbol: string;
  kline_type: string;
  strategy: string;
  strategy_key?: string;
  total_candles: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  avg_trade_pct: number;
  best_trade_pct: number;
  worst_trade_pct: number;
  profit_factor: number;
  avg_bars_held: number;
  stop_loss_pct?: number;
  take_profit_pct?: number;
  trailing_stop_pct?: number;
  max_hold_bars?: number;
  equity_curve: RollingEquityPoint[];
  trades: RollingTrade[];
  assumptions?: string[];
  message?: string;
  error?: string;
}
