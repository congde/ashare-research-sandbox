/**
 * Regression test for StrategyLibraryPage (策略库).
 *
 * Pins the fixture→API wiring: the page used to render 100% from
 * `strategyRows` fixtures. It now loads `strategiesApi.list()` and renders
 * real saved strategies, falling back to fixtures (with a warning) only when
 * the API is unavailable.
 *
 * Test 1: real strategies from the list API render instead of fixtures.
 * Test 2: API failure → fixture fallback + the 占位 warning.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/services", () => ({
  strategiesApi: {
    list: vi.fn(),
  },
}));

import { strategiesApi } from "../../api/services";
import StrategyLibraryPage from "../../pages/trading/StrategyLibraryPage";

type MockFn = ReturnType<typeof vi.fn>;

function strategy(overrides: Record<string, unknown> = {}) {
  return {
    id: "st-1",
    name: "BTC 动量网格",
    current_version: "0.1.0",
    status: "draft",
    strategy_card: { symbol: "BTC/USDT" },
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <AntApp>
      <MemoryRouter>
        <StrategyLibraryPage />
      </MemoryRouter>
    </AntApp>,
  );
}

describe("StrategyLibraryPage — fixture→API", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders real strategies from the API instead of fixtures", async () => {
    (strategiesApi.list as MockFn).mockResolvedValue({
      data: { items: [strategy()], total: 1, offset: 0, limit: 50 },
    });

    renderPage();

    await waitFor(() => expect(strategiesApi.list).toHaveBeenCalledTimes(1));
    // The saved strategy's name + its card symbol render in the table.
    await waitFor(() => expect(screen.getAllByText("BTC 动量网格").length).toBeGreaterThan(0));
    expect(screen.getAllByText("BTC/USDT").length).toBeGreaterThan(0);
    // API mode advertises 后端 as the data source.
    expect(screen.getAllByText("后端").length).toBeGreaterThan(0);
  });

  it("renders the latest backtest metrics for an API strategy", async () => {
    (strategiesApi.list as MockFn).mockResolvedValue({
      data: {
        items: [
          strategy({
            latest_backtest: {
              sharpe: 1.42,
              pnl_pct: 12.5,
              max_drawdown_pct: 8.3, // engine emits positive magnitude
              total_trades: 7,
              ran_at: "2026-06-02T00:00:00Z",
            },
          }),
        ],
        total: 1,
        offset: 0,
        limit: 50,
      },
    });

    renderPage();

    await waitFor(() => expect(strategiesApi.list).toHaveBeenCalledTimes(1));
    // The joined backtest's Sharpe renders (precision 2) instead of the "—" placeholder.
    await waitFor(() => expect(screen.getByText("1.42")).toBeInTheDocument());
  });

  it("falls back to fixtures with a warning when the API fails", async () => {
    (strategiesApi.list as MockFn).mockRejectedValue(new Error("503"));

    renderPage();

    await waitFor(() => expect(strategiesApi.list).toHaveBeenCalledTimes(1));
    // The 占位 warning surfaces; fixtures (e.g. a known demo name) still show.
    await waitFor(() => expect(screen.getByText(/策略接口暂不可用/)).toBeInTheDocument());
  });
});
