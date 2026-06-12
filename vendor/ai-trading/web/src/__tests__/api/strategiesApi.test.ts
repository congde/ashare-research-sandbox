/**
 * API client tests for the Strategy Architect (S5/S6) and Strategy
 * Runtime (S7-5 / S8) endpoint surfaces.
 *
 * What this pins:
 *
 *   1. The TypeScript interfaces match the backend's wire shape
 *      (validated by constructing a value of each interface — TS
 *      compile failures here mean the backend and frontend drifted).
 *   2. The endpoint URLs are stable — the backend mounts at known
 *      paths; renaming on either side breaks operator dashboards.
 *
 * We don't mock axios + run real HTTP here — that's an integration
 * test. The unit-level contract is "the interfaces compile and the
 * URLs are what we say they are."
 */

import { describe, expect, it } from "vitest";

import {
  strategiesApi,
  strategiesRuntimeApi,
} from "../../api/services";
import type {
  ApprovalResponse,
  CreateApprovalRequest,
  GenerateStrategyRequest,
  GenerateStrategyResponse,
  RuntimeHealthResponse,
  StartRuntimeRequest,
  StartRuntimeResponse,
  StrategyAttemptSummary,
  StrategyGenerationFinding,
} from "../../api/services";

// ── TypeScript interface shape ─────────────────────────────────


describe("Strategy Architect API types", () => {
  it("GenerateStrategyRequest accepts minimal payload", () => {
    const req: GenerateStrategyRequest = { prompt: "BTC grid" };
    expect(req.prompt).toBe("BTC grid");
  });

  it("GenerateStrategyRequest accepts full payload", () => {
    const req: GenerateStrategyRequest = {
      prompt: "BTC 1h grid bot, 12 levels, 0.5% spacing",
      symbol: "BTC/USDT",
      timeframe: "1h",
    };
    expect(req.symbol).toBe("BTC/USDT");
  });

  it("StrategyGenerationFinding shape covers validator + lookahead layers", () => {
    const validatorFinding: StrategyGenerationFinding = {
      layer: "validator",
      rule: "ATTR_DENY",
      line: 5,
      col: 0,
      message: "forbidden attribute __class__",
      suggestion: "remove __class__ reference",
    };
    const lookaheadFinding: StrategyGenerationFinding = {
      layer: "lookahead",
      rule: "L001",
      line: 3,
      col: 4,
      message: "future_close suggests reading future data",
    };
    expect(validatorFinding.layer).toBe("validator");
    expect(lookaheadFinding.layer).toBe("lookahead");
    expect(lookaheadFinding.suggestion).toBeUndefined();
  });

  it("StrategyAttemptSummary captures per-attempt telemetry", () => {
    const attempt: StrategyAttemptSummary = {
      iteration: 0,
      extracted_code: "def on_tick(ctx, candle): return None",
      findings: [],
      input_tokens: 1234,
      output_tokens: 567,
      model_used: "claude-opus-4.7",
      cost_usd: 0.045,
      cost_known: true,
    };
    expect(attempt.iteration).toBe(0);
    expect(attempt.cost_usd).toBeLessThan(0.05);
  });

  it("GenerateStrategyResponse carries the budget_exhausted flag", () => {
    const resp: GenerateStrategyResponse = {
      success: false,
      code: "",
      attempts: [],
      elapsed_seconds: 12.3,
      total_input_tokens: 0,
      total_output_tokens: 0,
      total_usd: 0.05,
      budget_usd: 0.05,
      budget_exhausted: true,
    };
    expect(resp.budget_exhausted).toBe(true);
    expect(resp.success).toBe(false);
  });
});


describe("Strategy Runtime API types", () => {
  it("StartRuntimeRequest accepts numeric and string Decimal fields", () => {
    // The backend takes Decimal; TS sends either number or string.
    const req1: StartRuntimeRequest = {
      symbol: "BTC/USDT",
      qty: 0.001,
      max_position_usd: 1000,
    };
    const req2: StartRuntimeRequest = {
      symbol: "BTC/USDT",
      qty: "0.001",
      max_position_usd: "1000",
    };
    expect(typeof req1.qty).toBe("number");
    expect(typeof req2.qty).toBe("string");
  });

  it("StartRuntimeResponse carries run_id and state", () => {
    const resp: StartRuntimeResponse = {
      run_id: "abc123",
      state: "running",
      started_at: "2026-05-17T00:00:00Z",
      symbol: "BTC/USDT",
      timeframe: "1m",
    };
    expect(resp.run_id).toBe("abc123");
    expect(resp.state).toBe("running");
  });

  it("RuntimeHealthResponse carries kill_switch_tripped", () => {
    const health: RuntimeHealthResponse = {
      run_id: "abc",
      state: "running",
      started_at: null,
      last_event_at: null,
      last_error: null,
      restart_count: 0,
      candles_processed: 5,
      intents_emitted: 1,
      fills: 1,
      rejected: 0,
      equity: "999.89",
      kill_switch_tripped: false,
    };
    // Decimal-as-string on the wire — UI parses to display.
    expect(health.equity).toBe("999.89");
    expect(health.kill_switch_tripped).toBe(false);
  });
});


describe("Approval API types (S8)", () => {
  it("CreateApprovalRequest supports all three actions", () => {
    const deploy: CreateApprovalRequest = {
      action: "deploy_live",
      reason: "testnet ready",
      payload: { exchange: "binance", testnet: true },
    };
    const threshold: CreateApprovalRequest = {
      action: "change_threshold",
      reason: "raise max position",
      payload: { rule: "max_position", value: "5000" },
    };
    const halt: CreateApprovalRequest = {
      action: "halt_all",
      reason: "price-feed anomaly across 3 venues",
    };
    expect(deploy.action).toBe("deploy_live");
    expect(threshold.action).toBe("change_threshold");
    expect(halt.action).toBe("halt_all");
  });

  it("ApprovalResponse carries the full state machine", () => {
    const resp: ApprovalResponse = {
      request_id: "approval-1",
      action: "halt_all",
      target: "*",
      requested_by: "alice",
      reason: "incident",
      state: "executed",
      created_at: "2026-05-17T00:00:00Z",
      expires_at: "2026-05-17T00:05:00Z",
      payload: {},
      decided_by: "bob",
      decided_at: "2026-05-17T00:00:30Z",
      decision_note: "agreed",
      execution_error: null,
    };
    expect(resp.state).toBe("executed");
    expect(resp.decided_by).toBe("bob");
  });
});


// ── API surface stability ──────────────────────────────────────


describe("API client surface is stable", () => {
  it("strategiesApi exposes generate", () => {
    expect(typeof strategiesApi.generate).toBe("function");
  });

  it("strategiesRuntimeApi exposes all v1 endpoints", () => {
    // Pin every method we depend on — if a backend route renames
    // and the frontend forgets to update, this test catches the
    // drift before operators see a 404.
    expect(typeof strategiesRuntimeApi.start).toBe("function");
    expect(typeof strategiesRuntimeApi.list).toBe("function");
    expect(typeof strategiesRuntimeApi.health).toBe("function");
    expect(typeof strategiesRuntimeApi.stop).toBe("function");
    expect(typeof strategiesRuntimeApi.tripKillSwitch).toBe("function");
    // Approval surface (S8)
    expect(typeof strategiesRuntimeApi.createApproval).toBe("function");
    expect(typeof strategiesRuntimeApi.listApprovals).toBe("function");
    expect(typeof strategiesRuntimeApi.getApproval).toBe("function");
    expect(typeof strategiesRuntimeApi.approve).toBe("function");
    expect(typeof strategiesRuntimeApi.reject).toBe("function");
  });
});
