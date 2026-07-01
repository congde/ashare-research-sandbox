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
  /** Unix seconds — preferred for lightweight-charts markers alignment */
  ts?: number;
  equity: number;
  close: number;
  open?: number;
  high?: number;
  low?: number;
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
  compilable?: boolean;
  compile_error?: string | null;
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

export interface RollingChartCandle {
  ts: number;
  date?: string;
  open: number;
  high: number;
  low: number;
  close: number;
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
  avg_win_pct?: number;
  avg_loss_pct?: number;
  payoff_ratio?: number;
  expectancy_pct?: number;
  exposure_pct?: number;
  benchmark_return_pct?: number;
  alpha_pct?: number;
  recovery_factor?: number;
  tail_ratio?: number;
  omega_ratio?: number;
  max_consecutive_wins?: number;
  max_consecutive_losses?: number;
  monte_carlo_95?: number | null;
  stop_loss_pct?: number;
  take_profit_pct?: number;
  trailing_stop_pct?: number;
  max_hold_bars?: number;
  cost_preset?: string;
  slippage_pct?: number;
  dynamic_slippage?: boolean;
  funding_rate_pct?: number;
  commission_pct?: number;
  equity_curve: RollingEquityPoint[];
  chart_candles?: RollingChartCandle[];
  warmup_bars?: number;
  data_source?: string;
  data_from?: string;
  data_through?: string;
  data_saved_at?: string;
  data_note?: string;
  trades: RollingTrade[];
  assumptions?: string[];
  message?: string;
  error?: string;
}

export interface BacktestCompareRow {
  strategy_key: string;
  strategy: string;
  total_return_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  win_rate: number;
  total_trades: number;
  calmar_ratio: number;
  profit_factor: number;
}

export interface BacktestComparePayload {
  ok: boolean;
  engine?: string;
  symbol: string;
  kline_type: string;
  total_candles: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  strategies: BacktestCompareRow[];
  leader?: string;
  laggard?: string;
  assumptions?: string[];
  message?: string;
}

export interface BacktestWindowRow {
  window: number;
  bars?: number;
  candles?: number;
  start_idx?: number;
  end_idx?: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  total_trades: number;
  win_rate?: number;
}

export interface BacktestWindowsPayload {
  ok: boolean;
  engine?: string;
  strategy_key: string;
  strategy?: string;
  symbol: string;
  kline_type: string;
  num_windows: number;
  windows: BacktestWindowRow[];
  positive_windows: number;
  stable: boolean;
  assumptions?: string[];
  message?: string;
}

export interface BacktestWalkForwardWindowRow {
  window: number;
  trainSize: number;
  testSize: number;
  inSampleSharpe: number;
  outOfSampleSharpe: number;
  outOfSampleReturn: number;
  bestParams: Record<string, unknown>;
}

export interface BacktestWalkForwardPayload {
  ok: boolean;
  strategy_key: string;
  symbol: string;
  kline_type: string;
  best_params: Record<string, unknown>;
  in_sample_sharpe: number;
  out_of_sample_sharpe: number;
  out_of_sample_return_pct: number;
  is_oos_sharpe_gap: number;
  overfit_warning: boolean;
  num_windows: number;
  num_trials?: number;
  dsr?: number;
  psr?: number;
  dsr_significant?: boolean;
  expected_max_sharpe?: number;
  cost_preset?: string;
  windows: BacktestWalkForwardWindowRow[];
  assumptions?: string[];
  message?: string;
}

export interface BacktestTrialAuditPayload {
  ok: boolean;
  num_trials: number;
  best_sharpe: number;
  sharpe_variance: number;
  sources: Record<string, number>;
}

export interface BacktestRobustnessPayload {
  ok: boolean;
  strategy_key: string;
  strategy: string;
  symbol: string;
  kline_type: string;
  cost_preset?: string;
  verdict: string;
  parameter_sensitivity: {
    baseline_return_pct: number;
    baseline_sharpe: number;
    stability_score: number;
    stable: boolean;
    tested: number;
    perturbations: Array<{
      param: string;
      direction: string;
      value: number | string;
      total_return_pct: number;
      return_drift_pct: number;
      stable: boolean;
    }>;
  };
  pbo: {
    pbo: number;
    num_splits: number;
    failures: number;
    verdict: string;
    overfit_risk: boolean;
  };
  assumptions?: string[];
  message?: string;
}

export interface BacktestCpcvPayload {
  ok: boolean;
  strategy_key: string;
  strategy: string;
  symbol: string;
  kline_type: string;
  cost_preset?: string;
  cpcv: {
    num_paths: number;
    profitable_paths_pct: number;
    return_p5: number;
    return_p50: number;
    return_p95: number;
    sharpe_p5: number;
    sharpe_p50: number;
    sharpe_p95: number;
    verdict: string;
    paths?: Array<{ return_pct: number; sharpe: number }>;
  };
  assumptions?: string[];
  message?: string;
}

export interface BacktestPortfolioLegRow {
  symbol: string;
  weight: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  total_trades: number;
}

export interface BacktestPortfolioCorrelation {
  a: string;
  b: string;
  correlation: number;
}

export interface BacktestPortfolioPayload {
  ok: boolean;
  strategy_key: string;
  legs: BacktestPortfolioLegRow[];
  pair_correlations: BacktestPortfolioCorrelation[];
  equal_weight_daily_return_sum_pct: number;
  equal_weight_leg_avg_return_pct: number;
  diversification_hint?: string;
  assumptions?: string[];
  message?: string;
}

export interface FactorMetricsView {
  ic_mean: number;
  ic_std: number;
  ir: number;
  hit_rate: number;
  sample_count: number;
  quintile_spread?: number;
  turnover_rate?: number;
  top_quintile_return?: number;
  bottom_quintile_return?: number;
  t_stat?: number;
  p_value?: number;
  rank_autocorr?: number;
  quantile_returns?: number[];
}

export interface FactorValidationView {
  quintile_spread: number;
  turnover_rate: number;
  ic_decay: number;
}

export interface FactorBacktestSpec {
  factor_source: "gp" | "ml";
  expr?: Record<string, unknown>;
  weights?: Record<string, number>;
  label?: string;
  horizon?: number;
  mining_target?: "return" | "risk";
  application?: string;
}

export interface FactorRiskSpec extends FactorBacktestSpec {
  application?: "position_scale";
}

export interface RiskApplicationPreview {
  method?: string;
  base_size?: number;
  sample_tail?: Array<{ idx: number; risk_z: number; position_scale: number }>;
  mean_position_scale?: number;
  note?: string;
}

export interface FactorMiningLeader {
  method: "gp" | "ml";
  label?: string;
  train_ic?: number;
  test_ic?: number;
  backtest_spec?: FactorBacktestSpec;
  risk_spec?: FactorRiskSpec;
  validation?: FactorValidationView;
}

export interface FactorMiningBranch {
  method: "gp" | "ml";
  expression?: string;
  formula?: string;
  fitness?: number;
  complexity?: number;
  selected_features?: string[];
  weights?: Record<string, number>;
  train?: FactorMetricsView;
  test?: FactorMetricsView;
  overfit_gap?: number;
  backtest_spec?: FactorBacktestSpec;
  univariate_screen?: Array<{ feature: string; ic_mean: number; abs_ic?: number }>;
}

export interface FactorMiningPayload {
  ok: boolean;
  engine?: string;
  mining_target?: "return" | "risk";
  risk_kind?: "abs_ret" | "realized_vol";
  metric_name?: string;
  label_description?: string;
  application?: string;
  mode: "gp" | "ml" | "both";
  symbol: string;
  kline_type: string;
  horizon_bars: number;
  sample_bars: number;
  train_bars: number;
  test_bars: number;
  feature_count: number;
  features: string[];
  baseline_univariate?: Array<{ feature: string; ic_mean: number; ir: number; hit_rate: number }>;
  gp?: FactorMiningBranch;
  ml?: FactorMiningBranch;
  leader?: FactorMiningLeader | null;
  warnings?: string[];
  what_it_proves?: string[];
  risk_application?: RiskApplicationPreview;
  message?: string;
}

export interface MinedFactorBacktestPayload extends RollingBacktestPayload {
  factor_source?: string;
  factor_label?: string;
  backtest_spec?: FactorBacktestSpec;
}
