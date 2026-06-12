import { theme, type ThemeConfig } from "antd";
import type { ThemeMode } from "../theme";

const shared: ThemeConfig["token"] = {
  colorPrimary: "#22d3ee",
  colorSuccess: "#00d084",
  colorWarning: "#f59e0b",
  colorError: "#ff4d4f",
  borderRadius: 12,
  borderRadiusLG: 16,
  borderRadiusSM: 8,
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Inter", "PingFang SC", sans-serif',
  fontFamilyCode: '"JetBrains Mono", "Fira Code", "Courier New", monospace',
};

export function buildAntTheme(mode: ThemeMode): ThemeConfig {
  if (mode === "light") {
    return {
      algorithm: theme.defaultAlgorithm,
      token: {
        ...shared,
        colorBgBase: "#f4f0e7",
        colorBgContainer: "rgba(255, 253, 248, 0.88)",
        colorBgElevated: "#fffdf8",
        colorBgLayout: "#f4f0e7",
        colorBorder: "rgba(23, 33, 24, 0.10)",
        colorBorderSecondary: "rgba(23, 33, 24, 0.06)",
        colorText: "#172118",
        colorTextSecondary: "#5d695f",
        boxShadow: "0 8px 32px rgba(23, 33, 24, 0.06)",
      },
      components: {
        Menu: {
          itemBorderRadius: 12,
        },
        Button: {
          defaultBg: "rgba(255, 255, 255, 0.85)",
          defaultBorderColor: "rgba(23, 33, 24, 0.12)",
          defaultColor: "#172118",
        },
        Input: {
          colorBgContainer: "rgba(255, 255, 255, 0.9)",
        },
        Select: {
          colorBgContainer: "rgba(255, 255, 255, 0.9)",
        },
      },
    };
  }

  return {
    algorithm: theme.darkAlgorithm,
    token: {
      ...shared,
      colorBgBase: "#000000",
      colorBgContainer: "rgba(5, 5, 8, 0.72)",
      colorBgElevated: "#0a0a0e",
      colorBgLayout: "#000000",
      colorBorder: "rgba(255,255,255,0.10)",
      colorBorderSecondary: "rgba(255,255,255,0.07)",
      colorText: "#e2e8f0",
      colorTextSecondary: "#8b92a5",
      boxShadow: "0 4px 24px rgba(0,0,0,0.50)",
    },
    components: {
      Menu: {
        darkItemBg: "#000000",
        darkSubMenuItemBg: "#000000",
        darkItemSelectedBg: "rgba(34,211,238,0.15)",
        darkItemSelectedColor: "#22d3ee",
        darkItemHoverBg: "rgba(34,211,238,0.08)",
        itemBorderRadius: 12,
      },
      Card: { colorBgContainer: "rgba(5, 5, 8, 0.72)" },
      Table: {
        colorBgContainer: "transparent",
        headerBg: "rgba(0,0,0,0.3)",
        rowHoverBg: "rgba(34,211,238,0.06)",
      },
    },
  };
}
