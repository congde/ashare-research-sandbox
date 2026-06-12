import { useState, useEffect, useCallback } from "react";
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { Layout, Menu, theme, Avatar, Dropdown, App } from "antd";
import JohnnyPanel from "../components/JohnnyPanel";
import {
  RobotOutlined,
  DashboardOutlined,
  ThunderboltOutlined,
  UserOutlined,
  ApiOutlined,
  WalletOutlined,
  SettingOutlined,
  LineChartOutlined,
  ExperimentOutlined,
  BarChartOutlined,
  ControlOutlined,
  RocketOutlined,
  SafetyOutlined,
} from "@ant-design/icons";
import { useCurrentUser } from "../contexts/UserContext";
import { walletApi } from "../api/services";
import { authStorage } from "../utils/auth-storage";
import type { RoleKey } from "../utils/roles";

const { Header, Sider, Content } = Layout;

const ROLE_META: Record<RoleKey, { label: string; dot: string }> = {
  trader:            { label: "交易员", dot: "#22d3ee" },
  strategy_provider: { label: "策略发布者", dot: "#00d084" },
};

// Leaf keys for active-state detection
const LEAF_KEYS = [
  "/trading", "/copilot", "/strategies", "/backtests", "/exchange-accounts", "/live", "/risk",
  "/research/stream", "/research",
  "/wallet",
  "/admin/users",
  "/settings/api-keys",
  "/account",
];

function buildMenuItems() {
  const tradingGroup = {
    key: "trading-group",
    icon: <LineChartOutlined />,
    label: "量化交易",
    children: [
      { key: "/trading", icon: <DashboardOutlined />, label: "交易总览" },
      { key: "/copilot", icon: <RobotOutlined />, label: "AI Co-pilot" },
      { key: "/strategies", icon: <ExperimentOutlined />, label: "策略库" },
      { key: "/backtests", icon: <BarChartOutlined />, label: "回测详情" },
      { key: "/exchange-accounts", icon: <ControlOutlined />, label: "交易账户" },
      { key: "/live", icon: <RocketOutlined />, label: "实盘监控" },
      { key: "/risk", icon: <SafetyOutlined />, label: "风控中心" },
      { key: "/research", icon: <ExperimentOutlined />, label: "市场情报" },
      { key: "/research/stream", icon: <ExperimentOutlined />, label: "实时流" },
    ],
  };

  return [
    tradingGroup,
    { key: "/wallet", icon: <WalletOutlined />, label: "钱包" },
    { key: "/account", icon: <SettingOutlined />, label: "我的账户" },
  ];
}

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [credits, setCredits] = useState<number | null>(null);
  const [johnnyOpen, setJohnnyOpen] = useState(false);
  const closeJohnny = useCallback(() => setJohnnyOpen(false), []);
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = theme.useToken();
  const { message: msg } = App.useApp();
  const { currentUser, userLoaded, isAdmin, isStrategyProvider, activeRole, switchRole } = useCurrentUser();

  useEffect(() => {
    walletApi.get().then((r) => setCredits(Math.round(Number(r.data.balance)))).catch(() => {});
  }, []);

  const selectedKey = LEAF_KEYS
    .sort((a, b) => b.length - a.length)
    .find((k) => location.pathname.startsWith(k)) ?? "/trading";

  const isTradingGroup = ["/trading", "/copilot", "/strategies", "/backtests", "/exchange-accounts", "/live", "/risk", "/research", "/research/stream"].some((k) => location.pathname.startsWith(k));
  const openKeys = collapsed ? [] : [
    isTradingGroup ? "trading-group" : "",
  ].filter(Boolean) as string[];

  const menuItems = buildMenuItems();

  return (
    <Layout style={{ height: "100vh", overflow: "hidden", background: "var(--bg-base)" }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        style={{
          background: "rgba(0,0,0,0.6)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          borderRight: "1px solid rgba(255,255,255,0.10)",
          boxShadow: "none",
        }}
      >
        {/* Inner flex wrapper: logo + scrollable menu + footer */}
        <div style={{
          display: "flex",
          flexDirection: "column",
          height: "calc(100% - 48px)", // 48px = Ant Design collapse trigger
        }}>
          {/* Product logo */}
          <div
            onClick={() => navigate("/trading")}
            style={{
              height: 56,
              display: "flex",
              alignItems: "center",
              justifyContent: collapsed ? "center" : "flex-start",
              gap: 10,
              padding: collapsed ? 0 : "0 16px",
              borderBottom: "1px solid rgba(255,255,255,0.10)",
              flexShrink: 0,
              cursor: "pointer",
            }}
          >
            <div style={{
              width: 32, height: 32, borderRadius: 10, flexShrink: 0,
              background: "linear-gradient(135deg, #00ffa3, #00d4ff)",
              boxShadow: "0 0 20px rgba(0,255,163,0.32)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontWeight: 800, color: "#020617", fontSize: 13,
            }}>
              AI
            </div>
            {!collapsed && (
              <div>
                <div style={{ fontSize: 15, fontWeight: 650, color: "#fff", letterSpacing: 0, lineHeight: 1.2 }}>
                  AI Trading
                </div>
                <div style={{ fontSize: 9, color: "rgba(255,255,255,0.45)", letterSpacing: 0 }}>
                  Agentic Quant Platform
                </div>
              </div>
            )}
          </div>

          {/* Scrollable menu area */}
          <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden" }}>
            <Menu
              mode="inline"
              theme="dark"
              inlineIndent={28}
              selectedKeys={[selectedKey]}
              defaultOpenKeys={openKeys}
              items={menuItems as never}
              style={{ background: "transparent", border: "none" }}
              onClick={({ key }) => {
                if (!key.endsWith("-group")) navigate(key);
              }}
            />
          </div>

          {/* Footer: system status */}
          {!collapsed && (
            <div style={{
              flexShrink: 0,
              padding: "10px 16px",
              borderTop: "1px solid rgba(255, 255, 255, 0.05)",
              display: "flex",
              flexDirection: "column",
              gap: 4,
            }}>
              <div className="sys-status">
                <span className="status-dot green" />
                <span>系统正常</span>
              </div>
              <div style={{ color: "var(--text-3)", fontSize: 10 }}>AI Trading v0.1</div>
            </div>
          )}
        </div>
      </Sider>
      <Layout style={{ background: "transparent" }}>
        <Header
          style={{
            background: "rgba(0,0,0,0.60)",
            backdropFilter: "blur(20px)",
            WebkitBackdropFilter: "blur(20px)",
            padding: "0 24px",
            display: "flex",
            justifyContent: "flex-end",
            alignItems: "center",
            gap: 0,
            borderBottom: "1px solid rgba(255,255,255,0.10)",
            boxShadow: "0 1px 20px rgba(0,0,0,0.40)",
            position: "sticky",
            top: 0,
            zIndex: 100,
          }}
        >
          {/* Ask Johnny button */}
          <button
            onClick={() => setJohnnyOpen((v) => !v)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 7,
              padding: "5px 13px 5px 8px",
              marginRight: 16,
              background: johnnyOpen
                ? "linear-gradient(135deg, #22d3ee 0%, #00d4ff 100%)"
                : "rgba(34,211,238,0.10)",
              border: `1px solid ${johnnyOpen ? "transparent" : "rgba(34,211,238,0.30)"}`,
              borderRadius: 20,
              cursor: "pointer",
              color: johnnyOpen ? "#fff" : "#7aaeff",
              fontSize: 13,
              fontWeight: 600,
              transition: "all 0.2s",
              whiteSpace: "nowrap",
              boxShadow: johnnyOpen ? "0 0 16px rgba(0,212,255,0.35)" : "none",
            }}
          >
            <img
              src="/johnny-avatar-2.png"
              alt="Johnny"
              style={{
                width: 22,
                height: 22,
                borderRadius: "50%",
                objectFit: "cover",
                objectPosition: "center top",
                border: "1px solid rgba(255,255,255,0.25)",
                flexShrink: 0,
              }}
            />
            智能助手
          </button>

          {/* Live stats */}
          <div className="header-live-stats">
            {credits !== null && (
              <div className="header-stat">
                <span className="header-stat-value mono" style={{ color: "var(--warning)" }}>
                  <ThunderboltOutlined style={{ fontSize: 10, marginRight: 3 }} />
                  {credits.toLocaleString()}
                </span>
                <span className="header-stat-label">积分</span>
              </div>
            )}
          </div>

          <Dropdown
            menu={{
              items: [
                {
                  key: "userinfo",
                  label: (
                    <div style={{ padding: "4px 0" }}>
                      <div style={{ fontWeight: 600 }}>{currentUser?.display_name ?? "用户"}</div>
                    </div>
                  ),
                  disabled: true,
                },
                { type: "divider" as const },
                {
                  key: "switch-trader",
                  label: (
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#22d3ee" }} />
                      <span>切换到交易员视角</span>
                      {activeRole === "trader" && <span style={{ color: "#22d3ee", marginLeft: "auto" }}>✓</span>}
                    </div>
                  ),
                },
                {
                  key: "switch-strategy-provider",
                  label: (
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#00d084" }} />
                      <span>切换到策略发布者视角</span>
                      {activeRole === "strategy_provider" && <span style={{ color: "#00d084", marginLeft: "auto" }}>✓</span>}
                    </div>
                  ),
                },
                { type: "divider" as const },
                ...(isAdmin ? [{ key: "/admin/users", icon: <SettingOutlined />, label: "用户管理" }] : []),
                ...(isStrategyProvider ? [{ key: "/settings/api-keys", icon: <ApiOutlined />, label: "API Key 管理" }] : []),
                { type: "divider" as const },
                { key: "logout", label: "退出登录" },
              ],
              onClick: async ({ key }) => {
                if (key === "logout") {
                  authStorage.clear();
                  navigate("/home", { replace: true });
                } else if (key === "switch-trader" && activeRole !== "trader") {
                  try {
                    await switchRole("trader");
                    navigate("/trading", { replace: true });
                  } catch (err) {
                    msg.error(err instanceof Error ? err.message : "切换角色失败");
                  }
                } else if (key === "switch-strategy-provider" && activeRole !== "strategy_provider") {
                  try {
                    await switchRole("strategy_provider");
                    navigate("/trading", { replace: true });
                  } catch (err) {
                    msg.error(err instanceof Error ? err.message : "切换角色失败");
                  }
                } else if (key !== "userinfo" && !key.startsWith("switch-")) {
                  navigate(key);
                }
              },
            }}
          >
            {/* Single non-interactive wrapper — avoids Ant Design circular hover treatment */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
              {userLoaded && currentUser && (() => {
                const roleMeta = ROLE_META[activeRole] || ROLE_META.trader;
                return (
                  <div style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                    padding: "3px 10px",
                    borderRadius: 100,
                    background: "rgba(255,255,255,0.06)",
                    border: "1px solid rgba(255,255,255,0.10)",
                    fontSize: 12,
                    color: "var(--text-2)",
                    lineHeight: 1.4,
                    whiteSpace: "nowrap",
                  }}>
                    <span style={{
                      width: 6, height: 6,
                      borderRadius: "50%",
                      background: roleMeta.dot,
                      flexShrink: 0,
                      display: "inline-block",
                    }} />
                    {roleMeta.label}
                  </div>
                );
              })()}
              <Avatar
                icon={<UserOutlined />}
                style={{
                  background: "linear-gradient(135deg, #22d3ee 0%, #00d4ff 100%)",
                  boxShadow: "0 0 10px rgba(34,211,238,0.45)",
                  flexShrink: 0,
                }}
              />
            </div>
          </Dropdown>
        </Header>
        <div style={{ display: "flex", flex: 1, overflow: "hidden", minHeight: 0 }}>
          <Content style={{ margin: 16, padding: 24, background: token.colorBgContainer, borderRadius: token.borderRadiusLG, overflow: "auto", flex: 1, minWidth: 0 }}>
            <Outlet />
          </Content>
          <JohnnyPanel open={johnnyOpen} onClose={closeJohnny} />
        </div>
      </Layout>
    </Layout>
  );
}
