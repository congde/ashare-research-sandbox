import { useReport } from "../../contexts/ReportContext";
import { QuantGlowCard, SectionHeader, SignalRow, StatusPill, TradingPageShell } from "../trading/TradingPageShell";

export default function ResearchPage() {
  const { report, loading } = useReport();
  const research = report?.research;

  return (
    <TradingPageShell
      eyebrow="Research / Intelligence"
      title="市场情报"
      description="用来源卡区分事实、解释与仍然未知。所有数据来自固定离线样本，不代表真实链上或交易所状态。"
    >
      <section className="trading-grid">
        <QuantGlowCard
          className="trading-span-7"
          title={
            <SectionHeader
              title={research?.company ?? "加载研究摘要..."}
              description="Facts · Interpretation · Unknowns"
            />
          }
          badge={<StatusPill tone="neutral">{loading ? "Loading" : "Fixed sample"}</StatusPill>}
        >
          <div className="trading-list">
            {(research?.facts ?? []).map((item) => (
              <SignalRow
                key={item.source_id}
                title={item.claim}
                meta={`来源 ${item.source_id}`}
                badge={<StatusPill tone="neutral">{item.source_id}</StatusPill>}
              />
            ))}
            <SignalRow title="解释" meta={research?.interpretation ?? "加载中..."} />
            {(research?.unknowns ?? []).map((item) => (
              <SignalRow key={item} title="仍然未知" meta={item} />
            ))}
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-5"
          title={<SectionHeader title="来源卡" description="可追溯证据链" />}
        >
          <div className="trading-list">
            {(research?.sources ?? []).map((source) => (
              <SignalRow
                key={source.id}
                title={`${source.id} · ${source.title}`}
                meta={`${source.date} · ${source.evidence}`}
              />
            ))}
          </div>
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}
