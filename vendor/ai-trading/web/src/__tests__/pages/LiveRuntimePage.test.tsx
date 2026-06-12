/**
 * Regression test for LiveRuntimePage (实盘监控).
 *
 * Pins the rules-of-hooks fix. The page used to call `useQuery` inside
 * `.map(run_ids)`, so the moment the runtime list went from 0 → ≥1
 * runner the NUMBER of hooks changed between renders and React crashed
 * the entire page ("Rendered more hooks than during the previous
 * render") — rendering a blank screen. It now uses `useQueries` (a
 * single hook call for a dynamic array of queries).
 *
 * Test 1 reproduces the crash scenario: list() resolves with one active
 * runner (0 → 1 transition). With the old code this threw during render;
 * with useQueries it renders the runner row.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/services", () => ({
  strategiesRuntimeApi: {
    list: vi.fn(),
    health: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    tripKillSwitch: vi.fn(),
  },
}));

import { strategiesRuntimeApi } from "../../api/services";
import LiveRuntimePage from "../../pages/trading/LiveRuntimePage";

const RUN_ID = "0660aee75eba4920ad2bb0cbc4a99265";

type MockFn = ReturnType<typeof vi.fn>;

function mockOneActiveRunner(): void {
  (strategiesRuntimeApi.list as MockFn).mockResolvedValue({
    data: { run_ids: [RUN_ID], count: 1 },
  });
  (strategiesRuntimeApi.health as MockFn).mockResolvedValue({
    data: {
      run_id: RUN_ID,
      state: "running",
      candles_processed: 42,
      fills: 3,
      rejected: 1,
      equity: "10250.50",
      kill_switch_tripped: false,
    },
  });
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <AntApp>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <LiveRuntimePage />
        </MemoryRouter>
      </QueryClientProvider>
    </AntApp>,
  );
}

describe("LiveRuntimePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the active runner without crashing (rules-of-hooks regression)", async () => {
    mockOneActiveRunner();
    renderPage();

    // The runner list only mounts when count > 0 — the exact 0 → 1
    // transition that crashed the old useQuery-in-map render path.
    await waitFor(() => {
      expect(screen.getByTestId("runner-list")).toBeInTheDocument();
    });
    // The runner row carries the run_id prefix; its presence proves the
    // per-runner health query mounted (useQueries) instead of throwing.
    expect(
      screen.getByText((t) => t.includes(RUN_ID.slice(0, 12))),
    ).toBeInTheDocument();
  });

  it("shows the empty state when there are no active runners", async () => {
    (strategiesRuntimeApi.list as MockFn).mockResolvedValue({
      data: { run_ids: [], count: 0 },
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/尚未启动任何策略/)).toBeInTheDocument();
    });
  });
});
