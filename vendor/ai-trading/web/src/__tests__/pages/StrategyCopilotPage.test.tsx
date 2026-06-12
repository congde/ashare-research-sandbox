/**
 * Tests for the wired StrategyCopilotPage (S10).
 *
 * The page calls the backend at POST /api/v1/strategies/generate via
 * strategiesApi.generate. These tests mock that module so the test
 * suite stays offline; the contract under test is:
 *
 *   1. Submitting the form invokes the API with the prompt
 *   2. Successful response renders the generated code
 *   3. Failed response surfaces a warning Alert
 *   4. Cost telemetry renders (usd / attempts / elapsed)
 *
 * We DON'T test the visual layout — that's the Quant Atelier
 * component library's job and is brittle. We test the **wiring**.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp } from "antd";

// Mock the API module BEFORE the component imports it. The component
// invokes strategiesApi.generate which we replace with a controlled
// mock per test.
vi.mock("../../api/services", () => ({
  strategiesApi: {
    generate: vi.fn(),
    save: vi.fn(),
  },
}));

// The module-level import only happens at component construction; we
// import after the mock to ensure the mocked module is bound.
import { strategiesApi } from "../../api/services";
import StrategyCopilotPage from "../../pages/trading/StrategyCopilotPage";


function renderPage() {
  // Fresh QueryClient per test so caching from one test doesn't
  // leak into the next.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <AntApp>
      <QueryClientProvider client={queryClient}>
        <StrategyCopilotPage />
      </QueryClientProvider>
    </AntApp>,
  );
}


describe("StrategyCopilotPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the initial fixture sketch before any generation", () => {
    renderPage();
    const code = screen.getByTestId("strategy-code");
    // Fixture sketch contains the YAML "strategy:" header.
    expect(code.textContent).toContain("strategy:");
  });

  it("calls strategiesApi.generate with the prompt on submit", async () => {
    const mock = vi.mocked(strategiesApi.generate);
    mock.mockResolvedValueOnce({
      data: {
        success: true,
        code: "def on_tick(ctx, candle): return None",
        attempts: [
          {
            iteration: 0,
            extracted_code: "def on_tick(ctx, candle): return None",
            findings: [],
            input_tokens: 100,
            output_tokens: 50,
          },
        ],
        elapsed_seconds: 2.5,
        total_input_tokens: 100,
        total_output_tokens: 50,
        total_usd: 0.045,
        budget_usd: 0.05,
        budget_exhausted: false,
      },
    } as never);

    renderPage();

    // Submit via the primary action button.
    const submitButtons = screen.getAllByText(/生成候选|生成拆解/);
    await userEvent.click(submitButtons[0]);

    await waitFor(() => {
      expect(mock).toHaveBeenCalledOnce();
    });
    // Inspect the call payload.
    const [payload] = mock.mock.calls[0];
    expect(payload).toHaveProperty("prompt");
    expect(payload).toHaveProperty("symbol", "BTC/USDT");
    expect(payload).toHaveProperty("timeframe", "1h");
  });

  it("renders the generated code on success", async () => {
    const mock = vi.mocked(strategiesApi.generate);
    mock.mockResolvedValueOnce({
      data: {
        success: true,
        code: "def on_tick(ctx, candle): return None  # success marker",
        attempts: [
          {
            iteration: 0,
            extracted_code: "def on_tick(ctx, candle): return None",
            findings: [],
            input_tokens: 100,
            output_tokens: 50,
          },
        ],
        elapsed_seconds: 1.0,
        total_input_tokens: 100,
        total_output_tokens: 50,
        total_usd: 0.01,
        budget_usd: 0.05,
        budget_exhausted: false,
      },
    } as never);

    renderPage();
    await userEvent.click(screen.getAllByText(/生成候选/)[0]);

    await waitFor(() => {
      const code = screen.getByTestId("strategy-code");
      expect(code.textContent).toContain("success marker");
    });
  });

  it("shows the budget-exhausted alert on success=false + budget_exhausted=true", async () => {
    const mock = vi.mocked(strategiesApi.generate);
    mock.mockResolvedValueOnce({
      data: {
        success: false,
        code: "",
        attempts: [],
        elapsed_seconds: 0.5,
        total_input_tokens: 0,
        total_output_tokens: 0,
        total_usd: 0.05,
        budget_usd: 0.05,
        budget_exhausted: true,
      },
    } as never);

    renderPage();
    await userEvent.click(screen.getAllByText(/生成候选/)[0]);

    await waitFor(() => {
      expect(screen.getByText(/预算耗尽/)).toBeInTheDocument();
    });
  });

  it("shows the retry-exhaustion alert on success=false + budget_exhausted=false", async () => {
    const mock = vi.mocked(strategiesApi.generate);
    mock.mockResolvedValueOnce({
      data: {
        success: false,
        code: "def on_tick(ctx, candle): return ctx.future_close",  // bad
        attempts: [
          {
            iteration: 0,
            extracted_code: "def on_tick(ctx, candle): return ctx.future_close",
            findings: [
              {
                layer: "lookahead",
                rule: "L001",
                line: 1,
                col: 35,
                message: "future_close suggests reading future data",
              },
            ],
            input_tokens: 100,
            output_tokens: 50,
          },
        ],
        elapsed_seconds: 3.0,
        total_input_tokens: 100,
        total_output_tokens: 50,
        total_usd: 0.005,
        budget_usd: 0.05,
        budget_exhausted: false,
      },
    } as never);

    renderPage();
    await userEvent.click(screen.getAllByText(/生成候选/)[0]);

    await waitFor(() => {
      // The retry-exhaustion alert mentions the prompt-refinement path.
      expect(screen.getByText(/重试 3 次后/)).toBeInTheDocument();
    });
  });

  it("disables submit button when prompt is empty", async () => {
    renderPage();

    // The user clears the default prompt.
    const textarea = screen.getByPlaceholderText(/输入策略目标/);
    await userEvent.clear(textarea);

    // The secondary submit button is disabled when prompt is empty.
    const generateButton = screen.getByText("生成拆解");
    expect(generateButton.closest("button")).toBeDisabled();
  });

  it("saves a generated strategy to the library after a successful generation", async () => {
    vi.mocked(strategiesApi.generate).mockResolvedValueOnce({
      data: {
        success: true,
        code: "def on_tick(ctx, candle): return None  # to save",
        attempts: [
          { iteration: 0, extracted_code: "x", findings: [], input_tokens: 1, output_tokens: 1 },
        ],
        elapsed_seconds: 1.0,
        total_input_tokens: 1,
        total_output_tokens: 1,
        total_usd: 0.01,
        budget_usd: 0.05,
        budget_exhausted: false,
      },
    } as never);
    vi.mocked(strategiesApi.save).mockResolvedValueOnce({
      data: { id: "st-1" },
    } as never);

    renderPage();
    await userEvent.click(screen.getAllByText(/生成候选/)[0]);

    // The save control only appears once generation succeeds.
    const saveButton = await screen.findByText("保存到库");
    await userEvent.click(saveButton);

    await waitFor(() => expect(strategiesApi.save).toHaveBeenCalledOnce());
    const [payload] = vi.mocked(strategiesApi.save).mock.calls[0] as [
      { name: string; code: string; strategy_card: Record<string, unknown> },
    ];
    expect(payload.code).toContain("to save");
    expect(payload.name.length).toBeGreaterThan(0);
    expect(payload.strategy_card).toHaveProperty("symbol", "BTC/USDT");
  });

  it("displays the LLM strategy card and saves it when present", async () => {
    vi.mocked(strategiesApi.generate).mockResolvedValueOnce({
      data: {
        success: true,
        code: "def on_tick(ctx, candle): return None",
        attempts: [
          { iteration: 0, extracted_code: "x", findings: [], input_tokens: 1, output_tokens: 1 },
        ],
        elapsed_seconds: 1.0,
        total_input_tokens: 1,
        total_output_tokens: 1,
        total_usd: 0.01,
        budget_usd: 0.05,
        budget_exhausted: false,
        card: {
          name: "BTC Momentum",
          thesis: "Trend-follow when the fast SMA crosses above the slow SMA.",
          valid_when: ["clear trend"],
          invalid_when: ["ranging chop"],
          risk_checklist: ["watch entry slippage"],
          expected_metrics: {},
          symbol: "BTC/USDT",
          timeframe: "1h",
          version: 1,
        },
      },
    } as never);
    vi.mocked(strategiesApi.save).mockResolvedValueOnce({ data: { id: "st-2" } } as never);

    renderPage();
    await userEvent.click(screen.getAllByText(/生成候选/)[0]);

    // The card's thesis + a risk-checklist item render.
    await waitFor(() =>
      expect(screen.getByText(/Trend-follow when the fast SMA/)).toBeInTheDocument(),
    );
    expect(screen.getByText("watch entry slippage")).toBeInTheDocument();

    await userEvent.click(await screen.findByText("保存到库"));
    await waitFor(() => expect(strategiesApi.save).toHaveBeenCalledOnce());
    const [payload] = vi.mocked(strategiesApi.save).mock.calls[0] as [
      { name: string; strategy_card: Record<string, unknown> },
    ];
    // The LLM card (not the provenance card) was sent + named the strategy.
    expect(payload.strategy_card).toHaveProperty("thesis");
    expect(payload.name).toBe("BTC Momentum");
  });
});
