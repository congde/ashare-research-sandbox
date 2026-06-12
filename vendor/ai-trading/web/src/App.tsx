import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ConfigProvider, App as AntApp, Spin, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { UserProvider, useCurrentUser } from "./contexts/UserContext";
import MainLayout from "./layouts/MainLayout";

// RFC 0011 Phase C3 (2026-05-08): every route is lazy-loaded so the
// initial bundle only contains React + antd + the layout shell. Each
// route becomes its own chunk that the browser fetches the first time
// the user navigates to it.
const LoginPage = lazy(() => import("./pages/Login"));
const RegisterPage = lazy(() => import("./pages/Register"));
const LandingPage = lazy(() => import("./pages/landing/LandingPage"));
const TradingDashboard = lazy(() => import("./pages/trading/TradingDashboard"));
const StrategyCopilotPage = lazy(() => import("./pages/trading/StrategyCopilotPage"));
const StrategyLibraryPage = lazy(() => import("./pages/trading/StrategyLibraryPage"));
const BacktestsPage = lazy(() => import("./pages/trading/BacktestsPage"));
const ExchangeAccountsPage = lazy(() => import("./pages/trading/ExchangeAccountsPage"));
const LiveRuntimePage = lazy(() => import("./pages/trading/LiveRuntimePage"));
const RiskCenterPage = lazy(() => import("./pages/trading/RiskCenterPage"));
const ResearchPanel = lazy(() => import("./pages/research/ResearchPanel"));
const ResearchStreamPanel = lazy(() => import("./pages/research/ResearchStreamPanel"));
const WalletPage = lazy(() => import("./pages/wallet/WalletPage"));
const AccountPage = lazy(() => import("./pages/account/AccountPage"));
const FundDetail = lazy(() => import("./pages/account/FundDetail"));
const ApiKeyPage = lazy(() => import("./pages/settings/ApiKeyPage"));
const UsersPage = lazy(() => import("./pages/admin/UsersPage"));
// Strategy-marketplace PMF dashboard (PR #114 — ai-trading product surface).
const MarketplacePmfPage = lazy(() => import("./pages/admin/MarketplacePmfPage"));

function HomeRouter() {
  const { currentUser, userLoaded } = useCurrentUser();
  if (!userLoaded) return null;
  if (currentUser) return <Navigate to="/trading" replace />;
  return <LandingPage />;
}

// Spinner shown while a route chunk is being fetched.
function RouteFallback() {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      minHeight: "60vh",
    }}>
      <Spin size="large" />
    </div>
  );
}

// RFC 0011 Phase F (2026-05-08): single shared QueryClient for the
// app. Defaults tuned for an internal admin tool — refetch on focus
// is too eager for our long-form pages, and a 30s stale time covers
// the typical "user navigates back to a page they just left" case
// without hammering the API.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000,
      gcTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary:        "#22d3ee",
          colorBgBase:         "#000000",
          colorBgContainer:    "#050508",
          colorBgElevated:     "#0a0a0e",
          colorBgLayout:       "#000000",
          colorBorder:         "rgba(255,255,255,0.10)",
          colorBorderSecondary:"rgba(255,255,255,0.07)",
          colorText:           "#e2e8f0",
          colorTextSecondary:  "#8b92a5",
          colorSuccess:        "#00d084",
          colorWarning:        "#f59e0b",
          colorError:          "#ff4d4f",
          borderRadius:        12,
          borderRadiusLG:      16,
          borderRadiusSM:      8,
          boxShadow:           "0 4px 24px rgba(0,0,0,0.50)",
          fontFamily:          '-apple-system, BlinkMacSystemFont, "Inter", "PingFang SC", sans-serif',
          fontFamilyCode:      '"JetBrains Mono", "Fira Code", "Courier New", monospace',
        },
        components: {
          Menu: {
            darkItemBg:             "#000000",
            darkSubMenuItemBg:      "#000000",
            darkItemSelectedBg:     "rgba(34,211,238,0.15)",
            darkItemSelectedColor:  "#22d3ee",
            darkItemHoverBg:        "rgba(34,211,238,0.08)",
            itemBorderRadius:       12,
          },
          Card: {
            colorBgContainer: "#050508",
          },
          Table: {
            colorBgContainer:  "transparent",
            headerBg:          "rgba(0,0,0,0.3)",
            rowHoverBg:        "rgba(34,211,238,0.06)",
          },
          Modal: {
            contentBg: "#080810",
            headerBg:  "#080810",
          },
          Drawer: {
            colorBgElevated: "#080810",
          },
          Tabs: {
            cardBg: "#050508",
          },
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
        <UserProvider>
        <BrowserRouter>
          <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/home" element={<LandingPage />} />
            <Route path="/" element={<HomeRouter />} />
            <Route element={<MainLayout />}>
              <Route path="/trading" element={<TradingDashboard />} />
              <Route path="/copilot" element={<StrategyCopilotPage />} />
              <Route path="/strategies" element={<StrategyLibraryPage />} />
              <Route path="/backtests" element={<BacktestsPage />} />
              <Route path="/exchange-accounts" element={<ExchangeAccountsPage />} />
              <Route path="/live" element={<LiveRuntimePage />} />
              <Route path="/risk" element={<RiskCenterPage />} />
              <Route path="/research" element={<ResearchPanel />} />
              <Route path="/research/stream" element={<ResearchStreamPanel />} />
              <Route path="/wallet" element={<WalletPage />} />
              <Route path="/account" element={<AccountPage />} />
              <Route path="/account/funds" element={<FundDetail />} />
              <Route path="/settings/api-keys" element={<ApiKeyPage />} />
              <Route path="/admin/users" element={<UsersPage />} />
              <Route path="/admin/marketplace-pmf" element={<MarketplacePmfPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
          </Suspense>
        </BrowserRouter>
        </UserProvider>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  );
}
