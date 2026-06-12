import type { RiskAction, RiskRuleKind } from "../../api/services";

export type RiskTone = "profit" | "loss" | "neutral" | "ai";

/** RiskRuleKind → human label for the trading UI (Risk Center + dashboard). */
export const RISK_KIND_LABEL: Record<RiskRuleKind, string> = {
  max_position_pct: "最大持仓",
  max_slippage_pct: "最大滑点",
  max_daily_loss_pct: "单日亏损",
  abnormal_orderbook: "异常订单簿",
  hard_daily_loss_pct: "硬性熔断",
};

// auto_halt is the hard guardrail (critical); propose is advisory; alert is informational.
export const RISK_ACTION_TONE: Record<RiskAction, RiskTone> = {
  alert: "ai",
  propose: "neutral",
  auto_halt: "loss",
};

/** RiskAction → human label for the action select. */
export const RISK_ACTION_LABEL: Record<RiskAction, string> = {
  alert: "告警",
  propose: "提议审批",
  auto_halt: "自动熔断",
};

/**
 * Kinds whose threshold is a single percent figure under `pct`. The lone
 * exception, `abnormal_orderbook`, carries a free-form heuristic dict, so the
 * create/edit form hides the pct input for it.
 */
export const PCT_RULE_KINDS: readonly RiskRuleKind[] = [
  "max_position_pct",
  "max_slippage_pct",
  "max_daily_loss_pct",
  "hard_daily_loss_pct",
];

export function isPctKind(kind: RiskRuleKind): boolean {
  return PCT_RULE_KINDS.includes(kind);
}
