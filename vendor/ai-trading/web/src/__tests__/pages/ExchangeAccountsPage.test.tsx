/**
 * Regression test for ExchangeAccountsPage (交易账户).
 *
 * Pins the "新增账户" button fix. The button used to render with no
 * `onClick` handler and no modal wired up, so clicking it did nothing —
 * the create-account flow was a dead end. It now opens a Modal + Form
 * that POSTs to `exchangeAccountApi.create` and reloads the list.
 *
 * Test 1: clicking 新增账户 opens the create modal.
 * Test 2: filling the form and submitting calls create() with the
 *         normalized payload (withdraw permission forced off) and then
 *         refreshes the account list.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/services", () => ({
  exchangeAccountApi: {
    list: vi.fn(),
    create: vi.fn(),
  },
}));

import { exchangeAccountApi } from "../../api/services";
import ExchangeAccountsPage from "../../pages/trading/ExchangeAccountsPage";

type MockFn = ReturnType<typeof vi.fn>;

function emptyList(): void {
  (exchangeAccountApi.list as MockFn).mockResolvedValue({
    data: { items: [], total: 0, offset: 0, limit: 50 },
  });
}

function renderPage() {
  return render(
    <AntApp>
      <MemoryRouter>
        <ExchangeAccountsPage />
      </MemoryRouter>
    </AntApp>,
  );
}

describe("ExchangeAccountsPage — 新增账户", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    emptyList();
  });

  it("opens the create modal when 新增账户 is clicked", async () => {
    renderPage();
    await waitFor(() => expect(exchangeAccountApi.list).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("button", { name: /新增账户/ }));

    expect(
      await screen.findByText("新增交易账户"),
    ).toBeInTheDocument();
  });

  it("submits the form and reloads the list on success", async () => {
    (exchangeAccountApi.create as MockFn).mockResolvedValue({
      data: {
        id: "acc-1",
        user_id: "u-1",
        exchange: "binance",
        label: "default",
        permissions: { spot: true, futures: false, margin: false, withdraw: false },
        is_testnet: true,
        last_verified_at: null,
        fingerprint: "ab12",
      },
    });

    renderPage();
    await waitFor(() => expect(exchangeAccountApi.list).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole("button", { name: /新增账户/ }));
    const dialog = await screen.findByRole("dialog");

    await userEvent.type(
      within(dialog).getByPlaceholderText("交易所生成的 API Key"),
      "MY_API_KEY",
    );
    await userEvent.type(
      within(dialog).getByPlaceholderText("交易所生成的 API Secret"),
      "MY_API_SECRET",
    );

    await userEvent.click(
      within(dialog).getByRole("button", { name: "保存账户" }),
    );

    await waitFor(() => expect(exchangeAccountApi.create).toHaveBeenCalledTimes(1));

    expect(exchangeAccountApi.create).toHaveBeenCalledWith(
      expect.objectContaining({
        exchange: "binance",
        label: "default",
        api_key: "MY_API_KEY",
        api_secret: "MY_API_SECRET",
        is_testnet: true,
        permissions: { spot: true, futures: false, margin: false, withdraw: false },
      }),
    );

    // List is reloaded after a successful create (initial load + refresh).
    await waitFor(() => expect(exchangeAccountApi.list).toHaveBeenCalledTimes(2));
  });
});
