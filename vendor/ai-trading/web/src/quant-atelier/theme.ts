/**
 * AntD 5 ConfigProvider theme override for Quant Atelier.
 *
 * Drop into App.tsx like:
 *   import { ConfigProvider } from 'antd'
 *   import { quantAtelierTheme } from '@/quant-atelier/theme'
 *   <ConfigProvider theme={quantAtelierTheme}>...</ConfigProvider>
 *
 * Per ADR-0003 (React + Vite + AntD) and frontend-design skill output.
 */

import { theme, type ThemeConfig } from 'antd'

/** Single source of truth for token values mirrored from `tokens.css`. */
export const quantAtelierTokens = {
  void: '#060A12',
  deep: '#0A0F1B',
  surface: '#0E1424',
  elevated: '#161E33',
  lineFaint: '#182142',
  lineSubtle: '#21305A',
  lineStrong: '#2E4378',
  text1: '#ECF3FF',
  text2: '#93A4CC',
  text3: '#5267A0',
  textMute: '#2E3B66',
  profit: '#00FFA3',
  loss: '#FF2D75',
  warn: '#FFB627',
  neutral: '#00D4FF',
  ai: '#7B5BFF',
  fontBody: '"Söhne", "Helvetica Neue", system-ui, sans-serif',
  fontMono: '"JetBrains Mono", "SF Mono", Consolas, monospace',
} as const

export const quantAtelierTheme: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: quantAtelierTokens.profit,
    colorBgBase: quantAtelierTokens.void,
    colorBgContainer: quantAtelierTokens.surface,
    colorBgElevated: quantAtelierTokens.elevated,
    colorBgLayout: quantAtelierTokens.void,
    colorBorder: quantAtelierTokens.lineSubtle,
    colorBorderSecondary: quantAtelierTokens.lineFaint,
    colorText: quantAtelierTokens.text1,
    colorTextSecondary: quantAtelierTokens.text2,
    colorTextTertiary: quantAtelierTokens.text3,
    colorTextQuaternary: quantAtelierTokens.textMute,
    colorSuccess: quantAtelierTokens.profit,
    colorError: quantAtelierTokens.loss,
    colorWarning: quantAtelierTokens.warn,
    colorInfo: quantAtelierTokens.neutral,
    fontFamily: quantAtelierTokens.fontBody,
    fontFamilyCode: quantAtelierTokens.fontMono,
    borderRadius: 4,
    borderRadiusLG: 8,
    wireframe: false,
  },
  components: {
    Table: {
      headerBg: quantAtelierTokens.deep,
      headerColor: quantAtelierTokens.text3,
      rowHoverBg: 'rgba(0,212,255,0.04)',
      borderColor: quantAtelierTokens.lineFaint,
    },
    Button: {
      fontFamily: 'inherit',
      controlHeight: 36,
    },
    Input: {
      paddingBlock: 9,
      activeBorderColor: quantAtelierTokens.profit,
    },
    Card: {
      colorBgContainer: quantAtelierTokens.surface,
      colorBorderSecondary: quantAtelierTokens.lineSubtle,
    },
    Modal: {
      contentBg: quantAtelierTokens.elevated,
      headerBg: quantAtelierTokens.elevated,
    },
    Tabs: {
      itemActiveColor: quantAtelierTokens.profit,
      inkBarColor: quantAtelierTokens.profit,
    },
    Tag: {
      defaultBg: 'rgba(0,212,255,0.05)',
      defaultColor: quantAtelierTokens.neutral,
    },
  },
}
