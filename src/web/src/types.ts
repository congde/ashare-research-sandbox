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
}

export interface RiskCheck {
  rule_id: string;
  message: string;
  severity: string;
}

export interface FusionInfo {
  product_shape: string;
  dsl_and_risk: string;
  adapted_modules: string[];
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
}

export interface DashboardAiPicks {
  ok: boolean;
  source?: string;
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
    kucoin_public?: boolean;
    fear_greed_public?: boolean;
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
