import type {
  DashboardAiPicks,
  DashboardOnchain,
  DashboardSectorFund,
  DashboardSourcesStatus,
  MarketCandlesPayload,
  ReportPayload,
  RuntimeConfig,
  StrategyValidationResult,
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

export function fetchDashboardSources(): Promise<DashboardSourcesStatus> {
  return fetchDashboard("/api/dashboard/sources/status");
}

export function fetchAiPicks(): Promise<DashboardAiPicks> {
  return fetchDashboard("/api/dashboard/vs/ai-picks");
}

export function fetchOnchain(symbol = "BTC"): Promise<DashboardOnchain> {
  return fetchDashboard(`/api/dashboard/onchain?symbol=${encodeURIComponent(symbol)}&limit=1`);
}

export function fetchSectorFund(tradeType = 1): Promise<DashboardSectorFund> {
  return fetchDashboard(`/api/dashboard/vs/sector-fund?trade_type=${tradeType}`);
}

export function fetchDexTrending(chain = "solana", limit = 5) {
  return fetchDashboard<{ ok: boolean; tokens?: Array<{ symbol?: string; value?: number; priceChange?: number }> }>(
    `/api/dashboard/dex/trending?chain=${encodeURIComponent(chain)}&limit=${limit}`,
  );
}

export function fetchMarketTickers(limit = 300) {
  return fetchDashboard<{ ok: boolean; count?: number; tickers?: unknown[] }>(
    `/api/market/tickers?quote=USDT&limit=${limit}`,
  );
}

export function fetchTokenFund(symbol: string) {
  return fetchDashboard(`/api/dashboard/vs/token-fund?symbol=${encodeURIComponent(symbol)}`);
}

export function fetchRuntimeConfig() {
  return fetchDashboard<RuntimeConfig>("/api/dashboard/config");
}

export function fetchMarketCandles(short = 3, long = 7, symbol?: string) {
  const params = new URLSearchParams({
    short: String(short),
    long: String(long),
    type: "1day",
    limit: "120",
  });
  if (symbol) {
    params.set("symbol", symbol);
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
