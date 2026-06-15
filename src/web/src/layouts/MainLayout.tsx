import { useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BarChartOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  RadarChartOutlined,
  SafetyOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { Layout, Menu } from "antd";
import { useThemeMode } from "../contexts/ThemeContext";

const { Header, Sider, Content } = Layout;

/** Flat nav aligned with web3-trading side_nav.html (+ sandbox extras). */
const NAV_ITEMS = [
  { key: "/trading", icon: <DashboardOutlined />, label: "市场总览" },
  { key: "/radar", icon: <RadarChartOutlined />, label: "深度分析" },
  { key: "/backtests", icon: <BarChartOutlined />, label: "策略回测" },
  { key: "/live-trading", icon: <SwapOutlined />, label: "模拟交易" },
  { key: "/data-sources", icon: <DatabaseOutlined />, label: "数据源" },
  { type: "divider" as const },
  { key: "/risk", icon: <SafetyOutlined />, label: "风控中心" },
  { key: "/strategy", icon: <ExperimentOutlined />, label: "策略 DSL" },
  { key: "/research", icon: <FileSearchOutlined />, label: "市场情报" },
];

const LEAF_KEYS = NAV_ITEMS.filter((item) => "key" in item).map((item) => item.key as string);

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const { mode: themeMode, toggle: toggleThemeMode } = useThemeMode();
  const navigate = useNavigate();
  const location = useLocation();

  const selectedKey =
    LEAF_KEYS.sort((a, b) => b.length - a.length).find((key) => location.pathname.startsWith(key)) ??
    "/trading";

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
        <div style={{ display: "flex", flexDirection: "column", height: "calc(100% - 48px)" }}>
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
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 10,
                flexShrink: 0,
                background: "linear-gradient(135deg, #00ffa3, #00d4ff)",
                boxShadow: "0 0 20px rgba(0,255,163,0.32)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 800,
                color: "#020617",
                fontSize: 13,
              }}
            >
              AI
            </div>
            {!collapsed && (
              <div>
                <div style={{ fontSize: 15, fontWeight: 650, color: "#fff", lineHeight: 1.2 }}>AI Trading</div>
                <div style={{ fontSize: 9, color: "rgba(255,255,255,0.45)" }}>教学沙箱 · 无登录</div>
              </div>
            )}
          </div>

          <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden" }}>
            <Menu
              mode="inline"
              theme="dark"
              inlineIndent={28}
              selectedKeys={[selectedKey]}
              items={NAV_ITEMS}
              style={{ background: "transparent", border: "none", paddingTop: 8 }}
              onClick={({ key }) => navigate(key)}
            />
          </div>

          {!collapsed && (
            <div
              style={{
                flexShrink: 0,
                padding: "10px 16px",
                borderTop: "1px solid rgba(255, 255, 255, 0.05)",
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              <div className="sys-status">
                <span className="status-dot green" />
                <span>Web3 Research Sandbox</span>
              </div>
              <div style={{ color: "var(--text-3)", fontSize: 10 }}>教学 · 无真实交易</div>
            </div>
          )}
        </div>
      </Sider>

      <Layout style={{ background: "transparent" }}>
        <Header className="app-shell-header">
          <div className="app-shell-title">Web3 投资研究与模拟策略验证台</div>
          <button type="button" className="btn-gradient app-theme-toggle" onClick={toggleThemeMode}>
            {themeMode === "dark" ? "☀ 白天模式" : "☾ 黑夜模式"}
          </button>
        </Header>
        <Content className="app-shell-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
