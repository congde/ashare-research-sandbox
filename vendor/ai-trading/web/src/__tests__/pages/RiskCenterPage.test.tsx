/**
 * Regression test for RiskCenterPage (风控中心).
 *
 * Pins the fixture→API wiring of the risk-rule reference table: it used to
 * render from the `riskRules` fixture. It now loads `riskApi.list` and maps
 * real RiskRule rows (kind→label, action→tone, active→state), falling back
 * to fixtures when the API is unavailable. The approvals / runtime surfaces
 * were already wired and are mocked empty here.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/services", () => ({
  riskApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
  strategiesRuntimeApi: {
    list: vi.fn().mockResolvedValue({ data: { count: 0, run_ids: [] } }),
    listApprovals: vi.fn().mockResolvedValue({ data: { count: 0, approvals: [] } }),
    createApproval: vi.fn(),
    approve: vi.fn(),
    reject: vi.fn(),
  },
}));

import { riskApi } from "../../api/services";
import RiskCenterPage from "../../pages/trading/RiskCenterPage";

type MockFn = ReturnType<typeof vi.fn>;

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <AntApp>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RiskCenterPage />
        </MemoryRouter>
      </QueryClientProvider>
    </AntApp>,
  );
}

function rule(kind: string, action: string) {
  return {
    id: `rr-${kind}`,
    scope: "global",
    scope_target_id: null,
    kind,
    threshold: { pct: 18 },
    action,
    active: true,
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
  };
}

describe("RiskCenterPage — risk-rule fixture→API", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("maps real risk rules from the API into the reference table", async () => {
    (riskApi.list as MockFn).mockResolvedValue({
      data: {
        items: [rule("max_position_pct", "auto_halt")],
        total: 1,
        offset: 0,
        limit: 100,
      },
    });

    renderPage();

    await waitFor(() => expect(riskApi.list).toHaveBeenCalledTimes(1));
    // kind → 中文 label; the live-data description shows.
    await waitFor(() => expect(screen.getAllByText("最大持仓").length).toBeGreaterThan(0));
    expect(screen.getByText(/后端 \/risk-rules 实时/)).toBeInTheDocument();
  });

  it("falls back to fixture rules when the API fails", async () => {
    (riskApi.list as MockFn).mockRejectedValue(new Error("503"));

    renderPage();

    await waitFor(() => expect(riskApi.list).toHaveBeenCalledTimes(1));
    // The reference card flips to the 占位 description.
    await waitFor(() => expect(screen.getByText(/占位/)).toBeInTheDocument());
  });

  it("creates a rule from the modal using the pre-filled defaults", async () => {
    (riskApi.list as MockFn).mockResolvedValue({
      data: { items: [], total: 0, offset: 0, limit: 100 },
    });
    (riskApi.create as MockFn).mockResolvedValue({
      data: rule("hard_daily_loss_pct", "auto_halt"),
    });

    renderPage();
    await waitFor(() => expect(riskApi.list).toHaveBeenCalled());

    // Open the create modal (pre-fills kind/pct/action/active), wait for it to
    // render, then submit the defaults. (antd spaces 2-CJK-char button labels,
    // so the OK button's accessible name is "创 建".)
    fireEvent.click(screen.getByText("新建规则"));
    fireEvent.click(await screen.findByRole("button", { name: /创\s*建/ }));

    await waitFor(() => expect(riskApi.create).toHaveBeenCalledTimes(1));
    // Owner is server-side; the form sends the global hard-loss defaults.
    expect(riskApi.create).toHaveBeenCalledWith({
      kind: "hard_daily_loss_pct",
      action: "auto_halt",
      active: true,
      threshold: { pct: 15 },
    });
  });
});
