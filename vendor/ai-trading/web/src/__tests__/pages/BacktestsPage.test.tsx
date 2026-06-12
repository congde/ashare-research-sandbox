/**
 * Regression test for BacktestsPage (回测详情).
 *
 * Pins the "重新回测" button fix. The button used to render with no
 * onClick and the Select had no value/onChange — clicking did nothing
 * and the page was 100% fixtures. It now drives a real
 * `backtestApi.create` and reloads the list; the Select is controlled.
 *
 * Test 1: 重新回测 POSTs {symbol, timeframe} then reloads the list.
 * Test 2: real backtests from the list API render instead of fixtures.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/services", () => ({
  backtestApi: {
    list: vi.fn(),
    create: vi.fn(),
  },
  strategiesApi: {
    list: vi.fn(),
  },
}));

import { backtestApi, strategiesApi } from "../../api/services";
import BacktestsPage from "../../pages/trading/BacktestsPage";

type MockFn = ReturnType<typeof vi.fn>;

function strategyItem(overrides: Record<string, unknown> = {}) {
  return {
    id: "st-1",
    name: "BTC 网格",
    current_version: "0.1.0",
    current_version_id: "ver-123",
    status: "draft",
    strategy_card: { symbol: "BTC/USDT" },
    latest_backtest: null,
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    ...overrides,
  };
}

function doneBacktest(overrides: Record<string, unknown> = {}) {
  return {
    id: "bt-1",
    strategy_version_id: "sv-1",
    state: "done",
    symbol: "ETH/USDT",
    timeframe: "1h",
    period_start: "2024-01-01T00:00:00Z",
    period_end: "2024-02-01T00:00:00Z",
    initial_capital: "1000",
    metrics: {
      total_trades: 1,
      win_rate: 0,
      pnl_pct: 12.5,
      sharpe: 1.4,
      max_drawdown_pct: 6.2,
      final_equity: "1125",
    },
    trades_count: 1,
    error_message: null,
    ...overrides,
  };
}

function emptyList(): void {
  (backtestApi.list as MockFn).mockResolvedValue({
    data: { items: [], total: 0, offset: 0, limit: 50 },
  });
}

function renderPage() {
  return render(
    <AntApp>
      <MemoryRouter>
        <BacktestsPage />
      </MemoryRouter>
    </AntApp>,
  );
}

describe("BacktestsPage — 重新回测", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    emptyList();
    // Default: no saved strategies → picker stays on the baseline.
    (strategiesApi.list as MockFn).mockResolvedValue({
      data: { items: [], total: 0, offset: 0, limit: 50 },
    });
  });

  it("triggers a backtest run and reloads the list", async () => {
    (backtestApi.create as MockFn).mockResolvedValue({
      data: doneBacktest({ symbol: "BTC/USDT" }),
    });

    renderPage();
    await waitFor(() => expect(backtestApi.list).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole("button", { name: /重新回测/ }));

    await waitFor(() => expect(backtestApi.create).toHaveBeenCalledTimes(1));
    expect(backtestApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: "BTC/USDT", timeframe: "1h" }),
    );

    // List reloads after a successful run (initial load + refresh).
    await waitFor(() => expect(backtestApi.list).toHaveBeenCalledTimes(2));
  });

  it("backtests the selected strategy version", async () => {
    (strategiesApi.list as MockFn).mockResolvedValue({
      data: { items: [strategyItem()], total: 1, offset: 0, limit: 50 },
    });
    (backtestApi.create as MockFn).mockResolvedValue({ data: doneBacktest() });

    renderPage();
    await waitFor(() => expect(strategiesApi.list).toHaveBeenCalled());

    // Open the strategy picker (first combobox) and choose the saved strategy.
    const comboboxes = screen.getAllByRole("combobox");
    await userEvent.click(comboboxes[0]);
    await userEvent.click(await screen.findByText(/BTC 网格/));

    await userEvent.click(screen.getByRole("button", { name: /重新回测/ }));

    await waitFor(() => expect(backtestApi.create).toHaveBeenCalledTimes(1));
    // The strategy's current_version_id flows through as strategy_version_id.
    expect(backtestApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ strategy_version_id: "ver-123" }),
    );
  });

  it("renders real backtests from the API instead of fixtures", async () => {
    (backtestApi.list as MockFn).mockResolvedValue({
      data: { items: [doneBacktest()], total: 1, offset: 0, limit: 50 },
    });

    renderPage();

    // "ETH/USDT" appears in both the table row and the "最深回撤" KPI tile,
    // so assert on at least one match rather than a unique element.
    await waitFor(() =>
      expect(screen.getAllByText("ETH/USDT").length).toBeGreaterThan(0),
    );
    // The real run's terminal state shows up as 已完成.
    expect(screen.getAllByText("已完成").length).toBeGreaterThan(0);
  });
});
