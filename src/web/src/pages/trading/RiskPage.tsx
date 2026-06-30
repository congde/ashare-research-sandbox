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
  const rejections = report?.backtest.risk_rejections ?? [];
  const activeRules = report?.fusion.risk_rules ?? report?.backtest.risk_rules ?? [];
  const runtimeChecks = riskChecks.filter((item) => item.phase === "pre_trade");
  const postChecks = riskChecks.filter((item) => item.phase !== "pre_trade");

  return (
    <TradingPageShell
      eyebrow="Risk Center"
      title="风控中心"
      description="ai-trading RiskManager 五条 MVP 规则在回测引擎中逐笔拦截；下方同时展示运行时拦截与回测后复核。"
      actions={<StatusPill tone="profit">{loading ? "Loading" : "Runtime + Review"}</StatusPill>}
    >
      <section className="trading-grid">
        <QuantGlowCard className="trading-span-12">
          <div className="trading-metric-grid">
            <MetricTile label="活跃规则" value={activeRules.length} subtle="ai-trading MVP" />
            <MetricTile label="运行时拦截" value={rejections.length} subtle="pre-trade blocks" />
            <MetricTile label="复核发现" value={riskChecks.length} subtle="runtime + post" />
            <MetricTile
              label="最大回撤"
              value={report?.backtest.metrics.maximum_drawdown_pct ?? 0}
              kind="pct"
              tone="loss"
              showSign
            />
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-4"
          title={<SectionHeader title="MVP 规则栈" description="KillSwitch → 持仓 → 回撤 → 滑点 → 异常 K 线" />}
          badge={<SafetyOutlined style={{ color: "var(--qa-neutral)" }} />}
        >
          <div className="trading-list">
            {activeRules.length ? (
              activeRules.map((ruleId) => (
                <SignalRow
                  key={ruleId}
                  title={ruleId}
                  meta="注册于 RiskManager，首条命中即短路"
                  badge={<StatusPill tone="ai">active</StatusPill>}
                />
              ))
            ) : (
              <SignalRow title="无规则" meta="RiskManager 未配置" />
            )}
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-4"
          title={<SectionHeader title="运行时拦截" description="pre_trade / RiskManager" />}
        >
          <div className="trading-list">
            {runtimeChecks.length ? (
              runtimeChecks.map((item) => (
                <SignalRow
                  key={item.rule_id}
                  title={item.rule_id}
                  meta={item.message}
                  badge={
                    <StatusPill tone={item.severity === "critical" ? "loss" : "ai"}>
                      {item.count && item.count > 1 ? `${item.count}x` : item.severity}
                    </StatusPill>
                  }
                />
              ))
            ) : (
              <SignalRow
                title="未拦截订单"
                meta="当前样本未触发运行时风控"
                badge={<StatusPill tone="profit">通过</StatusPill>}
              />
            )}
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-4"
          title={<SectionHeader title="回测后复核" description="post_backtest gates" />}
        >
          <div className="trading-list">
            {postChecks.length ? (
              postChecks.map((item) => (
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
                title="无额外发现"
                meta="回测指标未触发复核规则"
                badge={<StatusPill tone="profit">通过</StatusPill>}
              />
            )}
          </div>
        </QuantGlowCard>

        <QuantGlowCard className="trading-span-6" title={<SectionHeader title="拦截明细" />}>
          <Table
            className="trading-ant-table"
            pagination={false}
            rowKey={(row) => `${row.date}-${row.side}-${row.rule_id}-${row.reason}`}
            dataSource={rejections}
            locale={{ emptyText: "无运行时拦截记录" }}
            columns={[
              { title: "日期", dataIndex: "date" },
              { title: "方向", dataIndex: "side" },
              { title: "规则", dataIndex: "rule_id" },
              { title: "原因", dataIndex: "reason", ellipsis: true },
            ]}
          />
        </QuantGlowCard>

        <QuantGlowCard className="trading-span-6" title={<SectionHeader title="成交记录" />}>
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
