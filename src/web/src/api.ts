import type {
  DashboardAiPicks,
  DashboardOnchain,
  DashboardSectorFund,
  DashboardSourcesStatus,
  KlineAnalysisPayload,
  MarketCandlesPayload,
  OpportunityScanPayload,
  ReportPayload,
  RuntimeConfig,
  SignalAnalysisPayload,
  StrategyValidationResult,
  Web3NewsPayload,
  RollingBacktestPayload,
  RollingBacktestStrategy,
  BacktestComparePayload,
  BacktestCpcvPayload,
  BacktestPortfolioPayload,
  BacktestRobustnessPayload,
  BacktestTrialAuditPayload,
  BacktestWalkForwardPayload,
  BacktestWindowsPayload,
  FactorBacktestSpec,
  FactorMiningPayload,
  MinedFactorBacktestPayload,
} from "./types";

export async function fetchReport(short = 3, long = 7): Promise<ReportPayload> {
  const response = await fetch(`/api/report?short=${short}&long=${long}`);
  const payload = (await response.json()) as ReportPayload & { error?: string };
  if (!response.ok) {
    throw new Error(payload.error ?? "加载报告失败");
  }
  return payload;
}

async function fetchDashboard<T>(path: string): Promise<T> {
  const response = await fetch(path);
  const payload = (await response.json()) as T & { message?: string };
  if (!response.ok) {
    throw new Error(payload.message ?? "加载失败");
  }
  return payload;
}

function withRefresh(path: string, refresh?: boolean) {
  if (!refresh) {
    return path;
  }
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}refresh=true`;
}

export function fetchDashboardSources(): Promise<DashboardSourcesStatus> {
  return fetchDashboard("/api/dashboard/sources/status");
}

export function fetchAiPicks(options?: { refresh?: boolean }) {
  return fetchDashboard<DashboardAiPicks>(withRefresh("/api/dashboard/vs/ai-picks", options?.refresh));
}

export function fetchOnchain(symbol = "BTC", options?: { refresh?: boolean }) {
  return fetchDashboard<DashboardOnchain>(
    withRefresh(`/api/dashboard/onchain?symbol=${encodeURIComponent(symbol)}&limit=1`, options?.refresh),
  );
}

export function fetchSectorFund(tradeType = 1, options?: { refresh?: boolean }) {
  return fetchDashboard<DashboardSectorFund>(
    withRefresh(`/api/dashboard/vs/sector-fund?trade_type=${tradeType}`, options?.refresh),
  );
}

export function fetchDexTrending(chain = "solana", limit = 5) {
  return fetchDashboard<{ ok: boolean; tokens?: Array<{ symbol?: string; value?: number; priceChange?: number }> }>(
    `/api/dashboard/dex/trending?chain=${encodeURIComponent(chain)}&limit=${limit}`,
  );
}

export function fetchMarketTickers(limit = 300, options?: { refresh?: boolean }) {
  return fetchDashboard<{ ok: boolean; count?: number; tickers?: unknown[] }>(
    withRefresh(`/api/market/tickers?quote=USDT&limit=${limit}`, options?.refresh),
  );
}

export function fetchWeb3News(limit = 50, options?: { refresh?: boolean }) {
  return fetchDashboard<Web3NewsPayload>(
    withRefresh(`/api/dashboard/web3-news?limit=${limit}`, options?.refresh),
  );
}

export function fetchTickerStats(symbol: string, options?: { refresh?: boolean }) {
  return fetchDashboard<{ ok: boolean; ticker?: { symbol?: string; last?: number; changeRate?: number } }>(
    withRefresh(`/api/market/ticker?symbol=${encodeURIComponent(symbol)}`, options?.refresh),
  );
}

export function fetchTokenFund(symbol: string) {
  return fetchDashboard(`/api/dashboard/vs/token-fund?symbol=${encodeURIComponent(symbol)}`);
}

export function fetchRuntimeConfig() {
  return fetchDashboard<RuntimeConfig>("/api/dashboard/config");
}

export function fetchOpportunityScan(options?: {
  topK?: number;
  maxSymbols?: number;
  minVolume24h?: number;
  refresh?: boolean;
}) {
  const params = new URLSearchParams({
    topK: String(options?.topK ?? 30),
    maxSymbols: String(options?.maxSymbols ?? 300),
    minVolume24h: String(options?.minVolume24h ?? 200_000),
  });
  if (options?.refresh) {
    params.set("refresh", "true");
  }
  return fetchDashboard<OpportunityScanPayload>(`/api/dashboard/opportunity-scan?${params}`);
}

export function fetchKlineAnalysis(symbol = "BTC-USDT", klineType = "1hour", limit = 120) {
  const params = new URLSearchParams({
    symbol,
    type: klineType,
    limit: String(limit),
    realtime: "1",
  });
  return fetchDashboard<KlineAnalysisPayload>(`/api/market/kline-analysis?${params}`);
}

export function fetchSignalAnalysis(symbol = "BTC") {
  return fetchDashboard<SignalAnalysisPayload>(
    `/api/dashboard/signal-analysis?symbol=${encodeURIComponent(symbol)}`,
  );
}

export interface LlmSignalTaskPayload {
  ok: boolean;
  taskId?: string;
  status?: string;
  message?: string;
}

export interface LlmSignalPollPayload {
  ok: boolean;
  status?: string;
  data?: SignalAnalysisPayload;
  message?: string;
}

export async function submitLlmSignalAnalysis(symbol = "BTC", model = "deepseek/deepseek-v4-pro") {
  const params = new URLSearchParams({ symbol, model });
  const response = await fetch(`/api/dashboard/llm-signal-analysis?${params}`);
  const payload = (await response.json()) as LlmSignalTaskPayload & SignalAnalysisPayload;
  if (!response.ok) {
    throw new Error(payload.message ?? "提交 LLM 信号失败");
  }
  return payload;
}

export async function pollLlmSignalAnalysis(taskId: string) {
  const response = await fetch(`/api/dashboard/llm-signal-analysis/poll?taskId=${encodeURIComponent(taskId)}`);
  const payload = (await response.json()) as LlmSignalPollPayload;
  if (!response.ok && payload.status !== "failed") {
    throw new Error(payload.message ?? "轮询 LLM 信号失败");
  }
  return payload;
}

export function fetchLlmSignalAnalysis(symbol = "BTC", model = "deepseek/deepseek-v4-pro") {
  return submitLlmSignalAnalysis(symbol, model);
}

export function fetchMarketCandles(short = 3, long = 7, symbol?: string, options?: { refresh?: boolean }) {
  const params = new URLSearchParams({
    short: String(short),
    long: String(long),
    type: "1day",
    limit: "120",
  });
  if (symbol) {
    params.set("symbol", symbol);
  }
  if (options?.refresh) {
    params.set("refresh", "true");
  }
  return fetchDashboard<MarketCandlesPayload>(`/api/market/candles?${params.toString()}`);
}

export async function validateStrategy(code: string): Promise<StrategyValidationResult> {
  const response = await fetch("/api/validate-strategy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  const payload = (await response.json()) as StrategyValidationResult;
  if (!response.ok) {
    throw new Error(payload.error ?? "策略校验失败");
  }
  return payload;
}

export async function fetchBacktestStrategies(): Promise<RollingBacktestStrategy[]> {
  const response = await fetch("/api/dashboard/backtest/strategies");
  const payload = (await response.json()) as { ok?: boolean; strategies?: RollingBacktestStrategy[]; message?: string };
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message ?? "加载策略列表失败");
  }
  return payload.strategies ?? [];
}

export interface RunRollingBacktestOptions {
  strategy?: string;
  symbol?: string;
  type?: string;
  limit?: number;
  stopLoss?: number;
  takeProfit?: number;
  trailingStop?: number;
  maxHoldBars?: number;
  refresh?: boolean;
  costPreset?: "teaching" | "realistic" | "perp";
  slippageBps?: number;
  dynamicSlippage?: boolean;
  fundingRatePct?: number;
}

function appendCostParams(params: URLSearchParams, options: RunRollingBacktestOptions): void {
  if (options.costPreset) {
    params.set("costPreset", options.costPreset);
  }
  if (options.slippageBps != null) {
    params.set("slippageBps", String(options.slippageBps));
  }
  if (options.dynamicSlippage != null) {
    params.set("dynamicSlippage", options.dynamicSlippage ? "1" : "0");
  }
  if (options.fundingRatePct != null) {
    params.set("fundingRatePct", String(options.fundingRatePct));
  }
}

export async function runRollingBacktest(
  options: RunRollingBacktestOptions = {},
): Promise<RollingBacktestPayload> {
  const params = new URLSearchParams({
    strategy: options.strategy ?? "technical_signal",
    limit: String(options.limit ?? 120),
    stopLoss: String(options.stopLoss ?? 3),
    takeProfit: String(options.takeProfit ?? 5),
    trailingStop: String(options.trailingStop ?? 0),
    maxHoldBars: String(options.maxHoldBars ?? 0),
  });
  if (options.symbol) {
    params.set("symbol", options.symbol);
  }
  if (options.type) {
    params.set("type", options.type);
  }
  if (options.refresh) {
    params.set("refresh", "1");
  }
  appendCostParams(params, options);
  const response = await fetch(`/api/dashboard/backtest?${params}`);
  const payload = (await response.json()) as RollingBacktestPayload;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message ?? "回测失败");
  }
  return payload;
}

export async function fetchBacktestCompare(
  options: RunRollingBacktestOptions = {},
): Promise<BacktestComparePayload> {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 120),
    stopLoss: String(options.stopLoss ?? 3),
    takeProfit: String(options.takeProfit ?? 5),
    trailingStop: String(options.trailingStop ?? 0),
    maxHoldBars: String(options.maxHoldBars ?? 0),
  });
  if (options.symbol) {
    params.set("symbol", options.symbol);
  }
  if (options.type) {
    params.set("type", options.type);
  }
  appendCostParams(params, options);
  const response = await fetch(`/api/dashboard/backtest/compare?${params}`);
  const payload = (await response.json()) as BacktestComparePayload;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message ?? "策略比较失败");
  }
  return payload;
}

export async function fetchBacktestWindows(
  options: RunRollingBacktestOptions & { windows?: number } = {},
): Promise<BacktestWindowsPayload> {
  const params = new URLSearchParams({
    strategy: options.strategy ?? "ma_crossover",
    windows: String(options.windows ?? 3),
    limit: String(options.limit ?? 120),
    stopLoss: String(options.stopLoss ?? 3),
    takeProfit: String(options.takeProfit ?? 5),
  });
  if (options.symbol) {
    params.set("symbol", options.symbol);
  }
  appendCostParams(params, options);
  const response = await fetch(`/api/dashboard/backtest/windows?${params}`);
  const payload = (await response.json()) as BacktestWindowsPayload;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message ?? "窗口比较失败");
  }
  return payload;
}

export async function fetchBacktestWalkForward(
  options: RunRollingBacktestOptions & { windows?: number } = {},
): Promise<BacktestWalkForwardPayload> {
  const params = new URLSearchParams({
    strategy: options.strategy ?? "ma_crossover",
    windows: String(options.windows ?? 3),
    limit: String(options.limit ?? 120),
    stopLoss: String(options.stopLoss ?? 3),
    takeProfit: String(options.takeProfit ?? 5),
  });
  if (options.symbol) {
    params.set("symbol", options.symbol);
  }
  appendCostParams(params, options);
  const response = await fetch(`/api/dashboard/backtest/walk-forward?${params}`);
  const payload = (await response.json()) as BacktestWalkForwardPayload;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message ?? "Walk-forward 优化失败");
  }
  return payload;
}

export async function fetchBacktestPortfolio(
  options: RunRollingBacktestOptions = {},
): Promise<BacktestPortfolioPayload> {
  const params = new URLSearchParams({
    strategy: options.strategy ?? "ma_crossover",
    limit: String(options.limit ?? 120),
    stopLoss: String(options.stopLoss ?? 3),
    takeProfit: String(options.takeProfit ?? 5),
  });
  const response = await fetch(`/api/dashboard/backtest/portfolio?${params}`);
  const payload = (await response.json()) as BacktestPortfolioPayload;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message ?? "组合回测失败");
  }
  return payload;
}

export async function fetchBacktestRobustness(
  options: RunRollingBacktestOptions = {},
): Promise<BacktestRobustnessPayload> {
  const params = new URLSearchParams({
    strategy: options.strategy ?? "ma_crossover",
    limit: String(options.limit ?? 120),
    stopLoss: String(options.stopLoss ?? 3),
    takeProfit: String(options.takeProfit ?? 5),
  });
  if (options.symbol) {
    params.set("symbol", options.symbol);
  }
  appendCostParams(params, options);
  const response = await fetch(`/api/dashboard/backtest/robustness?${params}`);
  const payload = (await response.json()) as BacktestRobustnessPayload;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message ?? "稳健性审计失败");
  }
  return payload;
}

export async function fetchBacktestCpcv(
  options: RunRollingBacktestOptions = {},
): Promise<BacktestCpcvPayload> {
  const params = new URLSearchParams({
    strategy: options.strategy ?? "ma_crossover",
    limit: String(options.limit ?? 120),
    stopLoss: String(options.stopLoss ?? 3),
    takeProfit: String(options.takeProfit ?? 5),
  });
  if (options.symbol) {
    params.set("symbol", options.symbol);
  }
  appendCostParams(params, options);
  const response = await fetch(`/api/dashboard/backtest/cpcv?${params}`);
  const payload = (await response.json()) as BacktestCpcvPayload;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message ?? "CPCV 审计失败");
  }
  return payload;
}

export async function fetchBacktestAudit(
  strategy?: string,
): Promise<BacktestTrialAuditPayload> {
  const params = new URLSearchParams();
  if (strategy) {
    params.set("strategy", strategy);
  }
  const response = await fetch(`/api/dashboard/backtest/audit?${params}`);
  const payload = (await response.json()) as BacktestTrialAuditPayload;
  if (!response.ok || !payload.ok) {
    throw new Error("试验日志加载失败");
  }
  return payload;
}

export interface FetchFactorMineOptions {
  mode?: "gp" | "ml" | "template" | "llm" | "both" | "all";
  target?: "return" | "risk";
  riskKind?: "abs_ret" | "realized_vol";
  symbol?: string;
  limit?: number;
  horizon?: number;
  gpGenerations?: number;
  gpPopulation?: number;
  seed?: number;
  refresh?: boolean;
  llmModel?: string;
}

export async function fetchFactorMine(options: FetchFactorMineOptions = {}): Promise<FactorMiningPayload> {
  const params = new URLSearchParams({
    mode: options.mode ?? "all",
    target: options.target ?? "return",
    riskKind: options.riskKind ?? "abs_ret",
    limit: String(options.limit ?? 120),
    horizon: String(options.horizon ?? 1),
    gpGenerations: String(options.gpGenerations ?? 10),
    gpPopulation: String(options.gpPopulation ?? 20),
    seed: String(options.seed ?? 42),
  });
  if (options.symbol) {
    params.set("symbol", options.symbol);
  }
  if (options.refresh) {
    params.set("refresh", "1");
  }
  if (options.llmModel) {
    params.set("llmModel", options.llmModel);
  }
  const response = await fetch(`/api/dashboard/factor-mine?${params}`);
  const payload = (await response.json()) as FactorMiningPayload;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message ?? "因子挖掘失败");
  }
  return payload;
}

export interface RunMinedFactorBacktestOptions extends RunRollingBacktestOptions {
  backtestSpec: FactorBacktestSpec;
  entryThreshold?: number;
}

export async function runMinedFactorBacktest(
  options: RunMinedFactorBacktestOptions,
): Promise<MinedFactorBacktestPayload> {
  const response = await fetch("/api/dashboard/factor-mine/backtest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      backtest_spec: options.backtestSpec,
      symbol: options.symbol,
      limit: options.limit ?? 120,
      stopLoss: options.stopLoss ?? 3,
      takeProfit: options.takeProfit ?? 5,
      trailingStop: options.trailingStop ?? 0,
      maxHoldBars: options.maxHoldBars ?? 0,
      refresh: options.refresh ?? false,
      entryThreshold: options.entryThreshold ?? 0.5,
    }),
  });
  const payload = (await response.json()) as MinedFactorBacktestPayload;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message ?? "挖掘因子回测失败");
  }
  return payload;
}
