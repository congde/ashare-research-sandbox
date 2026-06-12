/**
 * Regression test for TradingDashboard (量化交易工作台).
 *
 * Pins the fixture→API wiring: the dashboard used to render 100% from
 * tradingData fixtures. It now loads strategiesApi.list + backtestApi.list
 * in parallel and renders real strategy counts + backtest results, falling
 * back to fixtures per-source when an API is unavailable.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/services", () => ({
  strategiesApi: { list: vi.fn() },
  backtestApi: { list: vi.fn() },
  riskApi: { list: vi.fn(), listEvents: vi.fn() },
}));

import { backtestApi, riskApi, strategiesApi } from "../../api/services";
import TradingDashboard from "../../pages/trading/TradingDashboard";

type MockFn = ReturnType<typeof vi.fn>;

function renderPage() {
  return render(
    <AntApp>
      <MemoryRouter>
        <TradingDashboard />
      </MemoryRouter>
    </AntApp>,
  );
}

function strategy(status: string) {
  return {
    id: `st-${status}`,
    name: status,
    current_version: "0.1.0",
    status,
    strategy_card: {},
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
  };
}

function backtest(symbol: string, pnl: number) {
  return {
    id: `bt-${symbol}`,
    strategy_version_id: "sv-1",
    state: "done",
    symbol,
    timeframe: "1h",
    period_start: "2024-01-01T00:00:00Z",
    period_end: "2024-02-01T00:00:00Z",
    initial_capital: "1000",
    metrics: { pnl_pct: pnl, sharpe: 1.5, max_drawdown_pct: 5 },
    trades_count: 3,
  };
}

describe("TradingDashboard — fixture→API", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders real strategy counts + backtests from the API", async () => {
    (strategiesApi.list as MockFn).mockResolvedValue({
      data: {
        items: [strategy("live"), strategy("draft"), strategy("dry_run")],
        total: 3,
        offset: 0,
        limit: 50,
      },
    });
    (backtestApi.list as MockFn).mockResolvedValue({
      data: { items: [backtest("SOL/USDT", 20)], total: 1, offset: 0, limit: 50 },
    });
    (riskApi.list as MockFn).mockResolvedValue({
      data: {
        items: [
          {
            id: "rr-1",
            scope: "global",
            scope_target_id: null,
            kind: "max_position_pct",
            threshold: { pct: 18 },
            action: "auto_halt",
            active: true,
            created_at: "2026-06-01T00:00:00Z",
            updated_at: "2026-06-01T00:00:00Z",
          },
        ],
        total: 1,
        offset: 0,
        limit: 100,
      },
    });

    (riskApi.listEvents as MockFn).mockResolvedValue({
      data: {
        items: [
          {
            id: "re-1",
            risk_rule_id: "rr-1",
            strategy_run_id: null,
            severity: "high",
            trigger: "position breach",
            context: {},
            explanation_llm: "position exceeded the cap",
            acknowledged: false,
            created_at: "2026-06-01T09:40:00Z",
            updated_at: "2026-06-01T09:40:00Z",
          },
        ],
        total: 1,
        offset: 0,
        limit: 20,
      },
    });

    renderPage();

    await waitFor(() => expect(strategiesApi.list).toHaveBeenCalledTimes(1));
    // A real backtest symbol (not in fixtures) renders → API data is live.
    await waitFor(() => expect(screen.getAllByText("SOL/USDT").length).toBeGreaterThan(0));
    // A real risk rule's kind maps to its 中文 label in the 风险覆盖 card.
    await waitFor(() => expect(screen.getAllByText("最大持仓").length).toBeGreaterThan(0));
    // A real risk event's trigger renders in the 运行事件 card.
    await waitFor(() => expect(screen.getByText(/position breach/)).toBeInTheDocument());
    // The data-source indicator flips to 后端.
    expect(screen.getAllByText("后端").length).toBeGreaterThan(0);
  });

  it("falls back to fixtures when both APIs fail", async () => {
    (strategiesApi.list as MockFn).mockRejectedValue(new Error("503"));
    (backtestApi.list as MockFn).mockRejectedValue(new Error("503"));
    (riskApi.list as MockFn).mockRejectedValue(new Error("503"));
    (riskApi.listEvents as MockFn).mockRejectedValue(new Error("503"));

    renderPage();

    await waitFor(() => expect(strategiesApi.list).toHaveBeenCalledTimes(1));
    // No crash; the data-source indicator stays 占位 and fixtures render.
    await waitFor(() => expect(screen.getAllByText("占位").length).toBeGreaterThan(0));
  });

  it("reports 后端 when only the risk API succeeds (rules but no strategies/backtests)", async () => {
    // A new user: no strategies/backtests yet, but seeded risk rules.
    (strategiesApi.list as MockFn).mockResolvedValue({
      data: { items: [], total: 0, offset: 0, limit: 50 },
    });
    (backtestApi.list as MockFn).mockResolvedValue({
      data: { items: [], total: 0, offset: 0, limit: 50 },
    });
    (riskApi.list as MockFn).mockResolvedValue({
      data: {
        items: [
          {
            id: "rr-1",
            scope: "global",
            scope_target_id: null,
            kind: "max_position_pct",
            threshold: { pct: 18 },
            action: "auto_halt",
            active: true,
            created_at: "2026-06-01T00:00:00Z",
            updated_at: "2026-06-01T00:00:00Z",
          },
        ],
        total: 1,
        offset: 0,
        limit: 100,
      },
    });
    (riskApi.listEvents as MockFn).mockRejectedValue(new Error("no events"));

    renderPage();

    await waitFor(() => expect(riskApi.list).toHaveBeenCalledTimes(1));
    // The risk card renders the real rule...
    await waitFor(() => expect(screen.getAllByText("最大持仓").length).toBeGreaterThan(0));
    // ...so the page-level indicator must report 后端 — not 占位.
    expect(screen.getAllByText("后端").length).toBeGreaterThan(0);
    expect(screen.queryByText("占位")).not.toBeInTheDocument();
  });
});
