/**
 * Tests for the Research panel — the unified surface over
 * ValueScan + DexScan that wraps `/api/v1/research/{catalogue,invoke}`.
 *
 * Contract under test:
 *   1. The page fetches `/research/catalogue` and renders every tool
 *      as a clickable card grouped by source.
 *   2. The source filter chips narrow the visible set.
 *   3. The search box matches against qualified_key + label + local_key.
 *   4. Selecting a tool primes the payload editor with a default JSON
 *      seed appropriate to the source.
 *   5. Submitting calls `/research/invoke` with the parsed payload
 *      and renders the response envelope.
 *   6. Invalid JSON in the editor produces an inline error, not a
 *      network call.
 *   7. Backend 502 maps to an error Alert in the response pane.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp } from "antd";

// Mock the API client before the page module is imported. The page
// only touches `researchApi`; per-test we control the mock's
// promise resolution.
vi.mock("../../api/services", () => ({
  researchApi: {
    catalogue: vi.fn(),
    invoke: vi.fn(),
  },
}));

import { researchApi } from "../../api/services";
import ResearchPanel from "../../pages/research/ResearchPanel";

interface MockTool {
  qualified_key: string;
  source: "vs" | "dex";
  local_key: string;
  path: string;
  label: string;
}

interface MockToolWithShape extends MockTool {
  body_shape: "dict" | "coin_key" | "coin_key_list" | "unknown";
}

const MOCK_TOOLS: MockToolWithShape[] = [
  {
    qualified_key: "vs.tokens",
    source: "vs",
    local_key: "tokens",
    path: "/api/open/v1/vs-token/list",
    label: "Token search — resolves symbol → vsTokenId",
    body_shape: "dict",
  },
  {
    qualified_key: "vs.token_detail",
    source: "vs",
    local_key: "token_detail",
    path: "/api/open/v1/vs-token/detail",
    label: "Token detail: price, market cap, 24h change",
    body_shape: "dict",
  },
  {
    qualified_key: "dex.current_price",
    source: "dex",
    local_key: "current_price",
    path: "v3/dex/market/current-price",
    label: "Latest DEX price",
    body_shape: "coin_key_list",
  },
];

function mockCatalogue(): void {
  // Returns an Axios-like { data } envelope to match the page's
  // assumption that `researchApi.catalogue()` returns AxiosResponse.
  (researchApi.catalogue as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: {
      tools: MOCK_TOOLS,
      valuescan_configured: true,
      dexscan_configured: true,
      total: MOCK_TOOLS.length,
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
        <ResearchPanel />
      </QueryClientProvider>
    </AntApp>,
  );
}

describe("ResearchPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches the catalogue and renders every tool card", async () => {
    mockCatalogue();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("research-tool-vs.tokens")).toBeInTheDocument();
    });

    expect(
      screen.getByTestId("research-tool-vs.token_detail"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("research-tool-dex.current_price"),
    ).toBeInTheDocument();
  });

  it("surfaces the total tool count in the aside", async () => {
    mockCatalogue();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("research-total-tools")).toHaveTextContent("3");
    });
  });

  it("filters by source when chip is clicked", async () => {
    const user = userEvent.setup();
    mockCatalogue();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("research-tool-vs.tokens")).toBeInTheDocument();
    });

    // Click the DexScan segment to hide ValueScan tools
    await user.click(screen.getByText(/DexScan \(1\)/));

    expect(
      screen.queryByTestId("research-tool-vs.tokens"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("research-tool-dex.current_price"),
    ).toBeInTheDocument();
  });

  it("searches by qualified_key, label, and local_key", async () => {
    const user = userEvent.setup();
    mockCatalogue();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("research-tool-vs.tokens")).toBeInTheDocument();
    });

    const searchBox = screen.getByPlaceholderText(/搜工具/);
    await user.clear(searchBox);
    await user.type(searchBox, "current_price");

    expect(
      screen.queryByTestId("research-tool-vs.tokens"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("research-tool-dex.current_price"),
    ).toBeInTheDocument();
  });

  it("primes the payload editor when a tool is selected", async () => {
    const user = userEvent.setup();
    mockCatalogue();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("research-tool-vs.token_detail")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("research-tool-vs.token_detail"));

    // token_detail seeds {"vsTokenId": 1}
    const editor = screen.getByPlaceholderText(/vsTokenId/) as HTMLTextAreaElement;
    expect(editor.value).toContain("vsTokenId");
  });

  it("invokes /research/invoke with the parsed payload on submit", async () => {
    const user = userEvent.setup();
    mockCatalogue();
    (researchApi.invoke as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        tool: "vs.token_detail",
        source: "vs",
        path: "/api/open/v1/vs-token/detail",
        data: {
          code: 200,
          data: { vsTokenId: "1", symbol: "BTC", price: "78154.5" },
        },
      },
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("research-tool-vs.token_detail")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("research-tool-vs.token_detail"));
    await user.click(screen.getByTestId("research-invoke"));

    await waitFor(() => {
      expect(researchApi.invoke).toHaveBeenCalledWith({
        tool: "vs.token_detail",
        payload: { vsTokenId: 1 },
      });
    });

    // The response should render in the console pane
    await waitFor(() => {
      expect(screen.getByTestId("research-response")).toBeInTheDocument();
    });
  });

  it("shows an inline error when payload is invalid JSON", async () => {
    const user = userEvent.setup();
    mockCatalogue();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("research-tool-vs.tokens")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("research-tool-vs.tokens"));

    // Replace the editor content with invalid JSON. Use fireEvent to
    // bypass user-event's curly-brace key modifier parsing.
    const editor = screen.getByPlaceholderText(/vsTokenId/) as HTMLTextAreaElement;
    await user.clear(editor);
    // user.type interprets `{` as a special key; use the {{ escape
    // sequence to emit a literal brace, OR use paste() which bypasses
    // the modifier parser entirely.
    await user.click(editor);
    await user.paste("{this is not json");

    await user.click(screen.getByTestId("research-invoke"));

    await waitFor(() => {
      expect(screen.getByText(/Payload is not valid JSON/)).toBeInTheDocument();
    });

    // The API must NOT have been called for invalid JSON.
    expect(researchApi.invoke).not.toHaveBeenCalled();
  });

  it("surfaces a backend error as an Alert in the console pane", async () => {
    const user = userEvent.setup();
    mockCatalogue();
    (researchApi.invoke as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: {
        status: 502,
        data: { detail: "DexScan upstream broken" },
      },
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("research-tool-dex.current_price")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("research-tool-dex.current_price"));
    await user.click(screen.getByTestId("research-invoke"));

    await waitFor(() => {
      expect(screen.getByText(/HTTP 502/)).toBeInTheDocument();
      expect(screen.getByText(/DexScan upstream broken/)).toBeInTheDocument();
    });
  });
});
