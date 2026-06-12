import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ConfigProvider, App } from "antd";

vi.mock("../../api/services", () => ({
  walletApi: {
    get: vi.fn().mockResolvedValue({
      data: { balance: "100", frozen_amount: "0", total_earned: "50", total_spent: "30" },
    }),
    listTransactions: vi.fn().mockResolvedValue({ data: { items: [] } }),
  },
  contractApi: {
    list: vi.fn().mockResolvedValue({ data: { items: [] } }),
  },
  paymentMethodApi: {
    list: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
    create: vi.fn().mockResolvedValue({ data: {} }),
    remove: vi.fn().mockResolvedValue({ data: {} }),
  },
  agentApi: {
    get: vi.fn().mockResolvedValue({ data: {} }),
  },
  workflowApi: {
    list: vi.fn().mockResolvedValue({ data: { items: [] } }),
  },
}));

vi.mock("../../api/client", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

vi.mock("../../contexts/UserContext", () => ({
  useCurrentUser: () => ({
    currentUser: { id: "1", display_name: "Test", username: "testuser", roles: ["employer"] },
    isAdmin: false,
    isTrader: true,
    isStrategyProvider: false,
    activeRole: "trader",
  }),
}));

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <ConfigProvider>
      <App>
        <MemoryRouter>{ui}</MemoryRouter>
      </App>
    </ConfigProvider>,
  );
}

describe("AccountPage", () => {
  let AccountPage: typeof import("../../pages/account/AccountPage").default;

  beforeEach(async () => {
    vi.clearAllMocks();
    const mod = await import("../../pages/account/AccountPage");
    AccountPage = mod.default;
  });

  it("renders the page title", () => {
    renderWithProviders(<AccountPage />);
    expect(screen.getByText("我的账户")).toBeInTheDocument();
  });

  it("shows the username next to the title", () => {
    renderWithProviders(<AccountPage />);
    expect(screen.getByText("@testuser")).toBeInTheDocument();
  });

  it("has tabs for wallet and settings", () => {
    renderWithProviders(<AccountPage />);
    expect(screen.getByRole("tab", { name: /钱包/ })).toBeInTheDocument();
    // 合约 (WorkDAO employment-contract) tab removed — ADR-0019 §4.2 disposition.
    expect(screen.getByRole("tab", { name: /设置/ })).toBeInTheDocument();
  });

  it("renders without crashing", () => {
    const { container } = renderWithProviders(<AccountPage />);
    expect(container).toBeTruthy();
  });

  it("opens the 收款方式 modal and binds a method", async () => {
    // delay: null drops user-event's realistic inter-keystroke delay. Without
    // it, typing 13 chars + antd modal animation tips this async test over the
    // default 5s testTimeout when the whole suite runs under coverage
    // instrumentation (it passes in isolation but timed out in the gate).
    const user = userEvent.setup({ delay: null });
    const services = await import("../../api/services");
    renderWithProviders(<AccountPage />);

    // Wallet tab is default but shows a loading spinner until the wallet
    // resolves — findByRole waits for the (previously dead) button to appear.
    await user.click(
      await screen.findByRole("button", { name: /绑定收款方式/ }),
    );

    // Modal opens and loads the bound list.
    const accountInput = await screen.findByPlaceholderText(
      "支付宝/微信账号或银行卡号",
    );
    await waitFor(() =>
      expect(services.paymentMethodApi.list).toHaveBeenCalled(),
    );

    await user.type(accountInput, "13800138000");
    await user.type(screen.getByPlaceholderText("收款人真实姓名"), "张三");
    // antd inserts a space between two CJK chars ("绑定" → "绑 定"); anchor
    // the regex so it matches the submit, not the "绑定收款方式" trigger.
    await user.click(screen.getByRole("button", { name: /^绑\s*定$/ }));

    await waitFor(() =>
      expect(services.paymentMethodApi.create).toHaveBeenCalledWith(
        expect.objectContaining({
          method_type: "alipay",
          account: "13800138000",
          holder_name: "张三",
        }),
      ),
    );
  }, 15000);
});
