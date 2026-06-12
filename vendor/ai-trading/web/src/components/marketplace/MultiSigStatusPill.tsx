/**
 * MultiSigStatusPill — 3-dot row showing platform / employer /
 * provider signature collection status on a PerformanceReport.
 *
 * Sprint S16 PR-2. Reads a `PerformanceReport`'s three signature
 * columns; renders one neon dot per party. Filled = signed, hollow
 * = pending. Hover tooltip names the party + status.
 *
 * Status legend:
 *   - status === "settled"   → all 3 filled + "settled" wrapper
 *   - status === "signed"    → all 3 filled
 *   - status === "partial"   → 1-2 filled
 *   - status === "pending"   → 0 filled
 *   - status === "disputed"  → red ring around the disputed dot
 */

import type { PerformanceReport } from "../../types";

export interface MultiSigStatusPillProps {
  report: Pick<
    PerformanceReport,
    | "platform_signature"
    | "employer_signature"
    | "provider_signature"
    | "status"
  >;
}

type Party = "platform" | "employer" | "provider";

const PARTY_LABELS: Record<Party, string> = {
  platform: "Platform",
  employer: "Employer",
  provider: "Provider",
};

function isSigned(
  report: MultiSigStatusPillProps["report"],
  party: Party,
): boolean {
  if (party === "platform") return report.platform_signature !== null;
  if (party === "employer") return report.employer_signature !== null;
  return report.provider_signature !== null;
}

export function MultiSigStatusPill({ report }: MultiSigStatusPillProps) {
  const parties: Party[] = ["platform", "employer", "provider"];
  const disputed = report.status === "disputed";
  const settled = report.status === "settled";

  return (
    <span
      data-testid="multisig-pill"
      data-status={report.status}
      role="group"
      aria-label={`Multi-sig status: ${report.status}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "4px 8px",
        borderRadius: 999,
        background: settled ? "var(--bg-elevated)" : "transparent",
        border: `1px solid ${settled ? "var(--cyan)" : "var(--bg-elevated)"}`,
      }}
    >
      {parties.map((p) => {
        const signed = isSigned(report, p);
        const partyDisputed = disputed && !signed;
        return (
          <span
            key={p}
            data-testid={`multisig-dot-${p}`}
            data-signed={signed}
            title={`${PARTY_LABELS[p]}: ${signed ? "signed" : partyDisputed ? "disputed" : "pending"}`}
            style={{
              width: 8,
              height: 8,
              borderRadius: 999,
              background: signed
                ? "var(--primary)"
                : partyDisputed
                  ? "transparent"
                  : "transparent",
              border: signed
                ? "1px solid var(--primary)"
                : partyDisputed
                  ? "1px solid var(--text-3)"
                  : "1px solid var(--text-3)",
              outline: partyDisputed ? "2px solid #ef4444" : "none",
              outlineOffset: partyDisputed ? -2 : 0,
              boxShadow: signed ? "0 0 4px var(--primary)" : "none",
            }}
          />
        );
      })}
    </span>
  );
}
