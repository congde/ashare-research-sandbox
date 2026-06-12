/**
 * MarketplacePmfPage — internal admin dashboard for the strategy
 * marketplace's 6 PMF metrics.
 *
 * Sprint S17 PR-2. Route: `/admin/marketplace-pmf`. Backed by
 * `/api/v1/internal/marketplace-pmf` (admin-gated; 403 for non-admin).
 *
 * Renders 6 KPI cards in a 3x2 grid + a "last computed" timestamp.
 * No charts — that's MM3 when we have enough data to plot trends.
 */

import { useEffect, useState } from "react";
import {
  Alert,
  App,
  Col,
  Row,
  Space,
  Spin,
  Typography,
} from "antd";
import {
  ReloadOutlined,
  RiseOutlined,
  TeamOutlined,
  TrophyOutlined,
  UserOutlined,
  WalletOutlined,
} from "@ant-design/icons";
import GlowCard from "../../components/GlowCard";
import {
  marketplacePmfApi,
} from "../../api/services";
import type { MarketplacePmfResponse } from "../../types";

const { Title, Text } = Typography;

// ── KPI metric card ─────────────────────────────────────────────

type Metric = {
  label: string;
  value: string;
  hint: string;
  icon: React.ReactNode;
  color: string;
};

function MetricCard({ label, value, hint, icon, color }: Metric) {
  return (
    <GlowCard color="cyan" style={{ height: "100%" }}>
      <Space direction="vertical" size={4} style={{ width: "100%" }}>
        <Space>
          <span style={{ color, fontSize: 18 }}>{icon}</span>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {label}
          </Text>
        </Space>
        <Title
          level={2}
          className="mono"
          style={{ margin: 0, color, fontVariantNumeric: "tabular-nums" }}
        >
          {value}
        </Title>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {hint}
        </Text>
      </Space>
    </GlowCard>
  );
}

// ── Format helpers ──────────────────────────────────────────────

function fmtPct(s: string): string {
  // Decimal string in [0, 1] → "XX.X%"
  const n = Number(s);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function fmtUsd(s: string): string {
  const n = Number(s);
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${n.toFixed(2)}`;
}

// ── Page ────────────────────────────────────────────────────────

export default function MarketplacePmfPage() {
  const { message } = App.useApp();
  const [data, setData] = useState<MarketplacePmfResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await marketplacePmfApi.get();
      setData(resp.data);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      message.error(`Failed to load PMF metrics: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (loading && !data) {
    return (
      <div style={{ padding: 32, textAlign: "center" }}>
        <Spin size="large" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div style={{ padding: 32 }}>
        <Alert
          message="PMF metrics unavailable"
          description={error}
          type="error"
          showIcon
          action={
            <a onClick={load} style={{ cursor: "pointer" }}>
              <ReloadOutlined /> Retry
            </a>
          }
        />
      </div>
    );
  }

  if (!data) return null;

  const metrics: Metric[] = [
    {
      label: "Weekly Active Strategies",
      value: String(data.weekly_active_strategies),
      hint: "Distinct strategy versions with ACTIVE employment",
      icon: <RiseOutlined />,
      color: "var(--primary, #22d3ee)",
    },
    {
      label: "Employer Retention W+1",
      value: fmtPct(data.employer_retention_w1),
      hint: "Of W=0 cohort, still active 1 week later (MM1 stub)",
      icon: <UserOutlined />,
      color: "var(--cyan, #22d3ee)",
    },
    {
      label: "Employer Retention W+4",
      value: fmtPct(data.employer_retention_w4),
      hint: "Of W=0 cohort, still active 4 weeks later",
      icon: <UserOutlined />,
      color: "var(--purple, #a78bfa)",
    },
    {
      label: "Provider Retention W+4",
      value: fmtPct(data.provider_retention_w4),
      hint: "Providers still listing 4 weeks after first activation",
      icon: <TeamOutlined />,
      color: "var(--purple, #a78bfa)",
    },
    {
      label: "Avg Period PnL (USD)",
      value: fmtUsd(data.average_period_pnl_usd),
      hint: "Mean per-period PnL across SETTLED reports",
      icon: <WalletOutlined />,
      color: "var(--primary, #22d3ee)",
    },
    {
      label: "Cumulative Perf Fees",
      value: fmtUsd(data.cumulative_performance_fees_usd),
      hint: "Total performance fee USD across all settlements",
      icon: <TrophyOutlined />,
      color: "#00ff88",
    },
    {
      label: "Cumulative Platform Cut",
      value: fmtUsd(data.cumulative_platform_cut_usd),
      hint: "Platform 15% take total to date",
      icon: <TrophyOutlined />,
      color: "#f59e0b",
    },
    {
      label: "Employer Retention W+2",
      value: fmtPct(data.employer_retention_w2),
      hint: "Of W=0 cohort, still active 2 weeks later",
      icon: <UserOutlined />,
      color: "var(--cyan, #22d3ee)",
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            Marketplace PMF Dashboard
          </Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Last computed: {new Date(data.computed_at).toLocaleString()}
            {" · "}
            MM1 phase — cohort retention is a count/100 stub; refines in MM3
          </Text>
        </div>
        <a onClick={load} style={{ cursor: "pointer" }}>
          <ReloadOutlined /> Refresh
        </a>
      </Space>

      <Row gutter={[16, 16]}>
        {metrics.map((m) => (
          <Col xs={24} sm={12} md={8} lg={6} key={m.label}>
            <MetricCard {...m} />
          </Col>
        ))}
      </Row>
    </div>
  );
}
