/**
 * Smoke tests for the Marketplace PMF dashboard page.
 *
 * Sprint S17 PR-2. Pinns format helpers + auth gate UI feedback path.
 * Heavy data render is left for Playwright (admin login + real backend).
 */

import { render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { describe, expect, it, vi } from "vitest";

import MarketplacePmfPage from "../../pages/admin/MarketplacePmfPage";

vi.mock("../../api/services", async () => {
  const actual: Record<string, unknown> = await vi.importActual(
    "../../api/services",
  );
  return {
    ...actual,
    marketplacePmfApi: {
      get: vi.fn(),
    },
  };
});

import { marketplacePmfApi } from "../../api/services";

describe("MarketplacePmfPage", () => {
  it("renders all 8 metric cards on a successful fetch", async () => {
    (marketplacePmfApi.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        weekly_active_strategies: 42,
        employer_retention_w1: "0.80",
        employer_retention_w2: "0.65",
        employer_retention_w4: "0.45",
        provider_retention_w4: "0.30",
        average_period_pnl_usd: "125.50",
        cumulative_performance_fees_usd: "5000",
        cumulative_platform_cut_usd: "750",
        computed_at: "2026-05-18T00:00:00+00:00",
      },
    });

    render(
      <AntApp>
        <MarketplacePmfPage />
      </AntApp>,
    );

    await waitFor(() => {
      expect(screen.getByText("Weekly Active Strategies")).toBeInTheDocument();
    });

    // The 8 metric labels render once each (page also shows 6 metric values
    // + 2 derived variants from the response).
    expect(screen.getByText("42")).toBeInTheDocument(); // WAS
    expect(screen.getByText("80.0%")).toBeInTheDocument(); // employer W+1
    expect(screen.getByText("65.0%")).toBeInTheDocument(); // employer W+2
    expect(screen.getByText("45.0%")).toBeInTheDocument(); // employer W+4
    expect(screen.getByText("30.0%")).toBeInTheDocument(); // provider W+4
    expect(screen.getByText("$125.50")).toBeInTheDocument(); // avg PnL
    expect(screen.getByText("$5.0k")).toBeInTheDocument(); // perf fees
    expect(screen.getByText("$750.00")).toBeInTheDocument(); // platform cut
  });

  it("renders error alert on 403 from non-admin user", async () => {
    (marketplacePmfApi.get as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("Request failed with status code 403"),
    );

    render(
      <AntApp>
        <MarketplacePmfPage />
      </AntApp>,
    );

    await waitFor(() => {
      expect(screen.getByText(/PMF metrics unavailable/i)).toBeInTheDocument();
    });
  });

  it("formats large USD numbers compactly", async () => {
    (marketplacePmfApi.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        weekly_active_strategies: 0,
        employer_retention_w1: "0",
        employer_retention_w2: "0",
        employer_retention_w4: "0",
        provider_retention_w4: "0",
        average_period_pnl_usd: "0",
        cumulative_performance_fees_usd: "2500000", // 2.5M
        cumulative_platform_cut_usd: "375000", // 375k
        computed_at: "2026-05-18T00:00:00+00:00",
      },
    });

    render(
      <AntApp>
        <MarketplacePmfPage />
      </AntApp>,
    );

    await waitFor(() => {
      expect(screen.getByText("$2.50M")).toBeInTheDocument();
      expect(screen.getByText("$375.0k")).toBeInTheDocument();
    });
  });
});
