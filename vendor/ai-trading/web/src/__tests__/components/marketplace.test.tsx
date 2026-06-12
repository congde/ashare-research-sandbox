/**
 * Component tests for HighWaterMarkChart + MultiSigStatusPill.
 *
 * Sprint S16 PR-2. Both components are pure presentational (no state,
 * no hooks beyond useMemo); jsdom + testing-library is enough.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HighWaterMarkChart } from "../../components/marketplace/HighWaterMarkChart";
import { MultiSigStatusPill } from "../../components/marketplace/MultiSigStatusPill";
import type { PerformanceReport } from "../../types";


// ── Fixtures ────────────────────────────────────────────────────


function makeReport(overrides: Partial<PerformanceReport> = {}): PerformanceReport {
  return {
    id: "pr_test",
    employment_contract_id: "ec_test",
    period_start: "2026-05-10T00:00:00Z",
    period_end: "2026-05-17T00:00:00Z",
    period_pnl_usd: "100",
    cumulative_pnl_usd: "100",
    high_water_mark_usd: "100",
    performance_fee_usd: "20",
    payload_hash: "0x" + "00".repeat(32),
    platform_signature: null,
    employer_signature: null,
    provider_signature: null,
    status: "pending",
    payload_json: {},
    created_at: "2026-05-17T00:00:00Z",
    updated_at: "2026-05-17T00:00:00Z",
    ...overrides,
  };
}


// ── HighWaterMarkChart ─────────────────────────────────────────


describe("HighWaterMarkChart", () => {
  it("shows empty state when no reports", () => {
    render(<HighWaterMarkChart reports={[]} />);
    expect(screen.getByTestId("hwm-chart-empty")).toBeInTheDocument();
    expect(
      screen.getByText(/No settlements yet/i),
    ).toBeInTheDocument();
  });

  it("renders SVG with equity + HWM polylines for a single report", () => {
    render(<HighWaterMarkChart reports={[makeReport()]} />);
    expect(screen.getByTestId("hwm-chart")).toBeInTheDocument();
    expect(screen.getByTestId("hwm-chart-equity")).toBeInTheDocument();
    expect(screen.getByTestId("hwm-chart-hwm")).toBeInTheDocument();
  });

  it("equity polyline has N points for N reports", () => {
    const reports = [
      makeReport({
        period_end: "2026-05-10T00:00:00Z",
        cumulative_pnl_usd: "100",
        high_water_mark_usd: "100",
      }),
      makeReport({
        period_end: "2026-05-17T00:00:00Z",
        cumulative_pnl_usd: "150",
        high_water_mark_usd: "150",
      }),
      makeReport({
        period_end: "2026-05-24T00:00:00Z",
        cumulative_pnl_usd: "120",
        high_water_mark_usd: "150",
      }),
    ];
    render(<HighWaterMarkChart reports={reports} />);
    const equity = screen.getByTestId("hwm-chart-equity");
    const points = equity.getAttribute("points") ?? "";
    expect(points.trim().split(/\s+/)).toHaveLength(3);
  });

  it("HWM polyline never decreases (no-decay HWM)", () => {
    const reports = [
      makeReport({
        period_end: "2026-05-10T00:00:00Z",
        cumulative_pnl_usd: "100",
        high_water_mark_usd: "100",
      }),
      makeReport({
        period_end: "2026-05-17T00:00:00Z",
        cumulative_pnl_usd: "80",
        high_water_mark_usd: "100", // unchanged on loss
      }),
      makeReport({
        period_end: "2026-05-24T00:00:00Z",
        cumulative_pnl_usd: "150",
        high_water_mark_usd: "150", // new high
      }),
    ];
    render(<HighWaterMarkChart reports={reports} />);
    const hwm = screen.getByTestId("hwm-chart-hwm");
    const points = (hwm.getAttribute("points") ?? "")
      .trim()
      .split(/\s+/)
      .map((p) => Number(p.split(",")[1]));
    // SVG Y is inverted (larger value = smaller Y). Monotonic-up data
    // means SVG Y is monotonic-down (non-increasing).
    expect(points[0]).toBeGreaterThanOrEqual(points[2]);
  });

  it("respects width / height props", () => {
    render(<HighWaterMarkChart reports={[makeReport()]} width={400} height={120} />);
    const svg = screen.getByTestId("hwm-chart");
    expect(svg.getAttribute("width")).toBe("400");
    expect(svg.getAttribute("height")).toBe("120");
  });

  it("has accessible aria-label", () => {
    render(<HighWaterMarkChart reports={[makeReport()]} label="Custom label" />);
    expect(screen.getByLabelText("Custom label")).toBeInTheDocument();
  });
});


// ── MultiSigStatusPill ─────────────────────────────────────────


describe("MultiSigStatusPill", () => {
  it("renders 3 dots (platform / employer / provider)", () => {
    render(<MultiSigStatusPill report={makeReport()} />);
    expect(screen.getByTestId("multisig-dot-platform")).toBeInTheDocument();
    expect(screen.getByTestId("multisig-dot-employer")).toBeInTheDocument();
    expect(screen.getByTestId("multisig-dot-provider")).toBeInTheDocument();
  });

  it("pending status: no dots signed", () => {
    render(<MultiSigStatusPill report={makeReport()} />);
    expect(screen.getByTestId("multisig-dot-platform")).toHaveAttribute("data-signed", "false");
    expect(screen.getByTestId("multisig-dot-employer")).toHaveAttribute("data-signed", "false");
    expect(screen.getByTestId("multisig-dot-provider")).toHaveAttribute("data-signed", "false");
  });

  it("partial status: only signed parties are filled", () => {
    const report = makeReport({
      status: "partial",
      platform_signature: "0xPlatformSig",
      employer_signature: "0xEmployerSig",
    });
    render(<MultiSigStatusPill report={report} />);
    expect(screen.getByTestId("multisig-dot-platform")).toHaveAttribute("data-signed", "true");
    expect(screen.getByTestId("multisig-dot-employer")).toHaveAttribute("data-signed", "true");
    expect(screen.getByTestId("multisig-dot-provider")).toHaveAttribute("data-signed", "false");
  });

  it("signed status: all 3 dots filled", () => {
    const report = makeReport({
      status: "signed",
      platform_signature: "0xP",
      employer_signature: "0xE",
      provider_signature: "0xPro",
    });
    render(<MultiSigStatusPill report={report} />);
    expect(screen.getByTestId("multisig-dot-platform")).toHaveAttribute("data-signed", "true");
    expect(screen.getByTestId("multisig-dot-employer")).toHaveAttribute("data-signed", "true");
    expect(screen.getByTestId("multisig-dot-provider")).toHaveAttribute("data-signed", "true");
    expect(screen.getByTestId("multisig-pill")).toHaveAttribute("data-status", "signed");
  });

  it("settled status: visible wrapper highlight", () => {
    const report = makeReport({
      status: "settled",
      platform_signature: "0xP",
      employer_signature: "0xE",
      provider_signature: "0xPro",
    });
    render(<MultiSigStatusPill report={report} />);
    expect(screen.getByTestId("multisig-pill")).toHaveAttribute("data-status", "settled");
  });

  it("disputed status surfaces in aria-label", () => {
    const report = makeReport({ status: "disputed" });
    render(<MultiSigStatusPill report={report} />);
    expect(screen.getByLabelText(/Multi-sig status: disputed/i)).toBeInTheDocument();
  });

  it("tooltip on each dot names the party + status", () => {
    const report = makeReport({
      status: "partial",
      platform_signature: "0xP",
    });
    render(<MultiSigStatusPill report={report} />);
    expect(screen.getByTestId("multisig-dot-platform")).toHaveAttribute(
      "title",
      expect.stringContaining("Platform"),
    );
    expect(screen.getByTestId("multisig-dot-platform")).toHaveAttribute(
      "title",
      expect.stringContaining("signed"),
    );
    expect(screen.getByTestId("multisig-dot-employer")).toHaveAttribute(
      "title",
      expect.stringContaining("pending"),
    );
  });
});
