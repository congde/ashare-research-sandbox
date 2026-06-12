import { SafetyOutlined } from "@ant-design/icons";
import { Table } from "antd";
import { useReport } from "../../contexts/ReportContext";
import {
  MetricTile,
  QuantGlowCard,
  SectionHeader,
  SignalRow,
  StatusPill,
  TradingPageShell,
} from "./TradingPageShell";

export default function RiskPage() {
  const { report, loading } = useReport();
  const riskChecks = report?.risk_checks ?? [];
  const trades = report?.backtest.trades ?? [];

  return (
    <TradingPageShell
      eyebrow="Risk Center"
      title="风控中心"
      description="展示 ai-trading risk_manager 适配后的模拟规则检查结果。仅作教学演示，不会执行真实交易。"
      actions={<StatusPill tone="profit">{loading ? "Loading" : "Simulation"}</StatusPill>}
    >
      <section className="trading-grid">
        <QuantGlowCard className="trading-span-12">
          <div className="trading-metric-grid">
            <MetricTile label="触发规则" value={riskChecks.length} subtle="当前参数组合" />
            <MetricTile
              label="最大回撤"
              value={report?.backtest.metrics.maximum_drawdown_pct ?? 0}
              kind="pct"
              tone="loss"
              showSign
            />
            <MetricTile
              label="策略收益"
              value={report?.backtest.metrics.strategy_return_pct ?? 0}
              kind="pct"
              tone="profit"
              showSign
            />
            <MetricTile label="交易动作" value={report?.backtest.metrics.trade_count ?? 0} />
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-6"
          title={<SectionHeader title="模拟风险检查" description="risk_manager 适配" />}
          badge={<SafetyOutlined style={{ color: "var(--qa-neutral)" }} />}
        >
          <div className="trading-list">
            {riskChecks.length ? (
              riskChecks.map((item) => (
                <SignalRow
                  key={item.rule_id}
                  title={item.rule_id}
                  meta={item.message}
                  badge={
                    <StatusPill tone={item.severity === "warning" ? "ai" : "loss"}>
                      {item.severity}
                    </StatusPill>
                  }
                />
              ))
            ) : (
              <SignalRow
                title="未触发规则"
                meta="当前参数组合通过模拟风控"
                badge={<StatusPill tone="profit">通过</StatusPill>}
              />
            )}
          </div>
        </QuantGlowCard>

        <QuantGlowCard className="trading-span-6" title={<SectionHeader title="交易记录" />}>
          <Table
            className="trading-ant-table"
            pagination={false}
            rowKey={(row) => `${row.date}-${row.action}-${row.price}`}
            dataSource={trades}
            columns={[
              { title: "日期", dataIndex: "date" },
              { title: "动作", dataIndex: "action" },
              { title: "价格", dataIndex: "price" },
            ]}
          />
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}
