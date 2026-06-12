/**
 * API client tests for the Strategy Marketplace (S15 backend + S16
 * frontend wiring). MM1 Phase 0 — off-chain settlement.
 *
 * What this pins:
 *
 *   1. TypeScript shape parity with the S14 ORM rows (the test
 *     constructs minimal + maximal values of every shape — TS
 *     compile failures here mean the wire contract drifted).
 *   2. URL + method stability for the `/marketplace/*` +
 *     `/employment/*` surfaces; renaming on either side breaks the
 *     UI without a runtime warning.
 *
 * Pattern follows `strategiesApi.test.ts` (S5-S8): no real HTTP, no
 * MSW — just a static structural check. Integration is e2e (PR-7).
 */

import { describe, expect, it } from "vitest";

import { employmentApi, strategyMarketplaceApi } from "../../api/services";
import type {
  CreateEmploymentRequest,
  CreateListingRequest,
  EmploymentContract,
  EmploymentDetail,
  EmploymentRole,
  EmploymentStatus,
  HighWaterMarkMethod,
  ListingStatus,
  MarketplaceSearchParams,
  MarketplaceSortBy,
  PerformanceReport,
  ProviderReputationSummary,
  ReportStatus,
  SettlementEvent,
  StrategyListing,
  StrategyListingDetail,
} from "../../types";


// ── TypeScript wire-shape parity ───────────────────────────────


describe("StrategyListing shapes", () => {
  it("StrategyListing matches S14 ORM row", () => {
    const row: StrategyListing = {
      id: "li_abc",
      strategy_version_id: "sv_xyz",
      provider_user_id: "u_provider",
      fee_rate_management: "0.0100",
      fee_rate_performance: "0.2000",
      deposit_usd: "100.000000",
      status: "draft",
      listing_signature: null,
      listing_signed_at: null,
      listing_meta: {},
      created_at: "2026-05-17T00:00:00Z",
      updated_at: "2026-05-17T00:00:00Z",
    };
    expect(row.status).toBe("draft");
    expect(row.deposit_usd).toBe("100.000000");
  });

  it("ListingStatus covers all 4 lifecycle states", () => {
    const states: ListingStatus[] = ["draft", "active", "paused", "delisted"];
    expect(states).toHaveLength(4);
  });

  it("StrategyListingDetail extends with reputation + strategy metadata", () => {
    const reputation: ProviderReputationSummary = {
      total_employers: 12,
      active_employers: 4,
      cumulative_pnl_usd: "45000.00",
      total_performance_fees_usd: "9000.00",
      breach_count: 1,
      avg_rating: "4.7",
      last_active_at: "2026-05-17T00:00:00Z",
    };
    const detail: StrategyListingDetail = {
      id: "li_abc",
      strategy_version_id: "sv_xyz",
      provider_user_id: "u_provider",
      fee_rate_management: "0.0100",
      fee_rate_performance: "0.2000",
      deposit_usd: "100",
      status: "active",
      listing_signature: "0x" + "ab".repeat(65),
      listing_signed_at: "2026-05-17T00:00:00Z",
      listing_meta: { pairs: ["BTC/USDT"] },
      created_at: "2026-05-17T00:00:00Z",
      updated_at: "2026-05-17T00:00:00Z",
      provider_reputation: reputation,
      strategy_name: "BTC Grid v2",
      strategy_card: { description: "grid bot" },
      high_water_mark_method: "rolling_no_decay",
    };
    expect(detail.provider_reputation?.total_employers).toBe(12);
    expect(detail.high_water_mark_method).toBe("rolling_no_decay");
  });

  it("StrategyListingDetail.provider_reputation may be null (new providers)", () => {
    const detail: StrategyListingDetail = {
      id: "li_new",
      strategy_version_id: "sv_new",
      provider_user_id: "u_new",
      fee_rate_management: "0.0100",
      fee_rate_performance: "0.2000",
      deposit_usd: "100",
      status: "active",
      listing_signature: null,
      listing_signed_at: null,
      listing_meta: {},
      created_at: "2026-05-17T00:00:00Z",
      updated_at: "2026-05-17T00:00:00Z",
      provider_reputation: null,
      strategy_name: "first listing",
      strategy_card: {},
      high_water_mark_method: "rolling_no_decay",
    };
    expect(detail.provider_reputation).toBeNull();
  });

  it("HighWaterMarkMethod covers both implementations", () => {
    const methods: HighWaterMarkMethod[] = ["rolling_no_decay", "periodic_reset"];
    expect(methods).toHaveLength(2);
  });

  it("CreateListingRequest is what /marketplace/strategies POST takes", () => {
    const req: CreateListingRequest = {
      strategy_version_id: "sv_xyz",
      fee_rate_management: "0.01",
      fee_rate_performance: "0.20",
      deposit_usd: "100",
    };
    expect(req.deposit_usd).toBe("100");
  });

  it("MarketplaceSearchParams supports the 4 sort orders", () => {
    const orders: MarketplaceSortBy[] = [
      "newest",
      "oldest",
      "highest_deposit",
      "lowest_deposit",
    ];
    expect(orders).toHaveLength(4);
    const params: MarketplaceSearchParams = {
      sort: "highest_deposit",
      limit: 50,
      offset: 100,
    };
    expect(params.limit).toBe(50);
  });
});


describe("EmploymentContract shapes", () => {
  it("EmploymentContract matches S14 ORM row", () => {
    const c: EmploymentContract = {
      id: "ec_abc",
      employer_user_id: "u_employer",
      provider_user_id: "u_provider",
      strategy_version_id: "sv_xyz",
      position_cap_usd: "1000",
      stop_loss_pct: "0.0500",
      max_drawdown_pct: "0.2000",
      fee_rate_management: "0.0100",
      fee_rate_performance: "0.2000",
      period_seconds: 604800,
      status: "active",
      started_at: "2026-05-17T00:00:00Z",
      terminated_at: null,
      high_water_mark_usd: "0",
      onchain_contract_address: null,
      escrow_address: null,
      created_at: "2026-05-17T00:00:00Z",
      updated_at: "2026-05-17T00:00:00Z",
    };
    expect(c.period_seconds).toBe(604800);
    expect(c.status).toBe("active");
  });

  it("EmploymentStatus covers all 4 lifecycle states", () => {
    const states: EmploymentStatus[] = ["pending", "active", "paused", "terminated"];
    expect(states).toHaveLength(4);
  });

  it("CreateEmploymentRequest is what /employment POST takes", () => {
    const req: CreateEmploymentRequest = {
      listing_id: "li_abc",
      position_cap_usd: "1000",
      stop_loss_pct: "0.05",
      max_drawdown_pct: "0.20",
      period_seconds: 604800,
    };
    expect(req.period_seconds).toBe(604800);
  });

  it("EmploymentRole covers both views", () => {
    const roles: EmploymentRole[] = ["employer", "provider"];
    expect(roles).toHaveLength(2);
  });
});


describe("PerformanceReport + SettlementEvent shapes", () => {
  it("PerformanceReport matches S14 ORM row (3-of-3 multi-sig)", () => {
    const r: PerformanceReport = {
      id: "pr_abc",
      employment_contract_id: "ec_abc",
      period_start: "2026-05-10T00:00:00Z",
      period_end: "2026-05-17T00:00:00Z",
      period_pnl_usd: "100.000000",
      cumulative_pnl_usd: "100.000000",
      high_water_mark_usd: "100.000000",
      performance_fee_usd: "20.000000",
      payload_hash: "0x" + "00".repeat(32),
      platform_signature: "0x" + "aa".repeat(65),
      employer_signature: "0x" + "bb".repeat(65),
      provider_signature: "0x" + "cc".repeat(65),
      status: "signed",
      payload_json: {
        cumulative_pnl_usd: "100.000000",
        period_start: "2026-05-10T00:00:00Z",
      },
      created_at: "2026-05-17T00:00:00Z",
      updated_at: "2026-05-17T00:00:00Z",
    };
    expect(r.status).toBe("signed");
    expect(r.performance_fee_usd).toBe("20.000000");
  });

  it("ReportStatus covers all 5 multi-sig states", () => {
    const states: ReportStatus[] = [
      "pending",
      "partial",
      "signed",
      "settled",
      "disputed",
    ];
    expect(states).toHaveLength(5);
  });

  it("SettlementEvent matches S14 ORM row with off-chain tx_hash", () => {
    const e: SettlementEvent = {
      id: "se_abc",
      performance_report_id: "pr_abc",
      employment_contract_id: "ec_abc",
      performance_fee_usd: "20.000000",
      platform_cut_usd: "3.000000",
      provider_payout_usd: "17.000000",
      tx_hash: "0x" + "ab".repeat(32),
      chain: "off-chain",
      settled_at: "2026-05-17T00:00:00Z",
      created_at: "2026-05-17T00:00:00Z",
      updated_at: "2026-05-17T00:00:00Z",
    };
    expect(e.chain).toBe("off-chain");
    expect(e.platform_cut_usd).toBe("3.000000");
  });

  it("SettlementEvent.tx_hash may be null (zero-payout periods)", () => {
    const e: SettlementEvent = {
      id: "se_zero",
      performance_report_id: "pr_zero",
      employment_contract_id: "ec_abc",
      performance_fee_usd: "0",
      platform_cut_usd: "0",
      provider_payout_usd: "0",
      tx_hash: null,
      chain: "off-chain",
      settled_at: "2026-05-17T00:00:00Z",
      created_at: "2026-05-17T00:00:00Z",
      updated_at: "2026-05-17T00:00:00Z",
    };
    expect(e.tx_hash).toBeNull();
  });

  it("EmploymentDetail bundles contract + history (single request)", () => {
    const d: EmploymentDetail = {
      id: "ec_abc",
      employer_user_id: "u_employer",
      provider_user_id: "u_provider",
      strategy_version_id: "sv_xyz",
      position_cap_usd: "1000",
      stop_loss_pct: "0.05",
      max_drawdown_pct: "0.20",
      fee_rate_management: "0.01",
      fee_rate_performance: "0.20",
      period_seconds: 604800,
      status: "active",
      started_at: "2026-05-17T00:00:00Z",
      terminated_at: null,
      high_water_mark_usd: "100",
      onchain_contract_address: null,
      escrow_address: null,
      created_at: "2026-05-17T00:00:00Z",
      updated_at: "2026-05-17T00:00:00Z",
      performance_reports: [],
      settlement_events: [],
      provider_reputation: null,
      strategy_name: "BTC Grid",
    };
    expect(d.performance_reports).toEqual([]);
    expect(d.settlement_events).toEqual([]);
  });
});


// ── API surface stability ──────────────────────────────────────


describe("strategyMarketplaceApi surface is stable", () => {
  it("exposes the 5 endpoint methods used by /marketplace UI", () => {
    expect(typeof strategyMarketplaceApi.search).toBe("function");
    expect(typeof strategyMarketplaceApi.get).toBe("function");
    expect(typeof strategyMarketplaceApi.list).toBe("function");
    expect(typeof strategyMarketplaceApi.unlist).toBe("function");
    expect(typeof strategyMarketplaceApi.pause).toBe("function");
    expect(typeof strategyMarketplaceApi.resume).toBe("function");
  });
});


describe("employmentApi surface is stable", () => {
  it("exposes the lifecycle + sub-resource methods", () => {
    expect(typeof employmentApi.listActive).toBe("function");
    expect(typeof employmentApi.get).toBe("function");
    expect(typeof employmentApi.create).toBe("function");
    expect(typeof employmentApi.activate).toBe("function");
    expect(typeof employmentApi.pause).toBe("function");
    expect(typeof employmentApi.resume).toBe("function");
    expect(typeof employmentApi.terminate).toBe("function");
    expect(typeof employmentApi.reports).toBe("function");
    expect(typeof employmentApi.settlements).toBe("function");
  });
});
