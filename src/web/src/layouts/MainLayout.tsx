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
import { useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useThemeMode } from "../contexts/ThemeContext";

const { Header, Sider, Content } = Layout;

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
        className="app-shell-sider"
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme={themeMode}
      >
        <div className="app-sider-inner">
          <button
            type="button"
            className={`app-sider-brand${collapsed ? " app-sider-brand-collapsed" : ""}`}
            onClick={() => navigate("/trading")}
          >
            <span className="app-sider-logo">AI</span>
            {!collapsed && (
              <span className="app-sider-brand-copy">
                <strong>AI Trading</strong>
                <span>教学沙箱 / 无需登录</span>
              </span>
            )}
          </button>

          <div className="app-sider-scroll">
            <Menu
              className="app-sider-menu"
              mode="inline"
              theme={themeMode}
              inlineIndent={28}
              selectedKeys={[selectedKey]}
              items={NAV_ITEMS}
              onClick={({ key }) => navigate(key)}
            />
          </div>

          {!collapsed && (
            <div className="app-sider-footer">
              <div className="sys-status">
                <span className="status-dot green" />
                <span>Web3 Research Sandbox</span>
              </div>
              <div className="app-sider-caption">教学 / 无真实交易</div>
            </div>
          )}
        </div>
      </Sider>

      <Layout style={{ background: "transparent" }}>
        <Header className="app-shell-header">
          <div className="app-shell-title">Web3 投资研究与模拟策略验证台</div>
          <button type="button" className="btn-gradient app-theme-toggle" onClick={toggleThemeMode}>
            {themeMode === "dark" ? "白天模式" : "夜间模式"}
          </button>
        </Header>
        <Content className="app-shell-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
