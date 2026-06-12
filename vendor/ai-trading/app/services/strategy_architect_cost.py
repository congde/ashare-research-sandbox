"""Cost gating for the Strategy Architect agent.

Closes the last Sprint-S5 DoD checkbox: **"单次会话成本 < $0.05"**.

The price table here is the **only** source of truth for the agent's
per-token cost estimates. Keep it explicit (not auto-fetched) so we
can audit cost-control behaviour without depending on external APIs.

Pricing is a model-specific (input_per_million, output_per_million)
in USD. When a model isn't in the table, the estimator falls back to
a **conservative** rate (the most expensive entry's output rate
applied to ALL tokens) — over-estimating is the safe failure mode
when comparing against a budget cap.

Pricing data sources:

  * Anthropic — https://www.anthropic.com/api (pricing tab)
  * OpenAI — https://openai.com/api/pricing
  * DeepSeek — https://api-docs.deepseek.com/quick_start/pricing

Snapshot taken 2026-05-16. Refresh quarterly or when CLAUDE.md's
"default model" choice changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class _ModelPrice(NamedTuple):
    """USD per **one million** tokens, separately for input and
    output. NamedTuple (not dataclass) so it's hashable + cheap to
    construct on every estimator call."""

    input_usd_per_million: float
    output_usd_per_million: float


# ── Price catalogue ──────────────────────────────────────────────


# Key format: lower-cased provider/model or bare model name. The
# estimator first tries an exact match against ``LLMResponse.model``,
# then falls back to substring matching for ``anthropic/claude-...``
# style prefixed names.
#
# Numbers in USD per 1M tokens, snapshot 2026-05-16.
_PRICE_TABLE: dict[str, _ModelPrice] = {
    # ── Anthropic ────────────────────────────────────────────────
    "claude-opus-4.7": _ModelPrice(15.0, 75.0),
    "claude-opus-4-7": _ModelPrice(15.0, 75.0),
    "claude-opus-4.6": _ModelPrice(15.0, 75.0),
    "claude-sonnet-4.6": _ModelPrice(3.0, 15.0),
    "claude-sonnet-4-6": _ModelPrice(3.0, 15.0),
    "claude-haiku-4.5": _ModelPrice(0.8, 4.0),
    "claude-haiku-4-5": _ModelPrice(0.8, 4.0),
    # ── OpenAI ───────────────────────────────────────────────────
    "gpt-4o": _ModelPrice(2.5, 10.0),
    "gpt-4o-mini": _ModelPrice(0.15, 0.6),
    "o1": _ModelPrice(15.0, 60.0),
    "o3-mini": _ModelPrice(3.0, 12.0),
    # ── DeepSeek ─────────────────────────────────────────────────
    "deepseek-chat": _ModelPrice(0.27, 1.10),
    "deepseek-reasoner": _ModelPrice(0.55, 2.19),
    # ── Test stub ────────────────────────────────────────────────
    "fake": _ModelPrice(1.0, 1.0),
}


# Conservative ceiling for unknown models — picks the most expensive
# output rate in the table. Better to over-estimate (and trip the
# budget gate too early) than under-estimate (and let a budget bust
# happen unnoticed).
_FALLBACK_RATE = _ModelPrice(15.0, 75.0)


# ── Settings ─────────────────────────────────────────────────────


#: Default per-session USD budget. Per Sprint-S5 DoD and SKILL.md.
#: A typical clean generation costs $0.04-0.08 — 5 cents is the
#: median plus a slim margin.
DEFAULT_MAX_USD_PER_SESSION = 0.05


# ── Public API ───────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """USD cost broken down by input vs output side.

    Provided as a struct (not a bare float) so the wire response can
    surface the split — useful for UI tooltips and audit log entries.
    """

    input_usd: float
    output_usd: float
    model: str
    price_known: bool  # False if the model fell through to fallback

    @property
    def total_usd(self) -> float:
        return self.input_usd + self.output_usd


def estimate_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    model: str,
) -> CostEstimate:
    """Return a :class:`CostEstimate` for the given token counts.

    ``model`` is the string LiteLLM reports back in ``LLMResponse.model``.
    Matching is **case-insensitive** and tolerates the
    ``provider/model`` prefix LiteLLM applies (e.g.
    ``"anthropic/claude-opus-4.7"``).

    Never raises. Unknown models fall through to the conservative
    fallback rate; the returned :attr:`CostEstimate.price_known`
    flag is False so callers can warn.
    """
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError(
            f"token counts must be non-negative; got "
            f"input={input_tokens} output={output_tokens}"
        )

    price, price_known = _lookup_price(model)

    input_usd = input_tokens * price.input_usd_per_million / 1_000_000
    output_usd = output_tokens * price.output_usd_per_million / 1_000_000
    return CostEstimate(
        input_usd=input_usd,
        output_usd=output_usd,
        model=model,
        price_known=price_known,
    )


def _lookup_price(model: str) -> tuple[_ModelPrice, bool]:
    """Match ``model`` against the price table.

    Strategy: exact (lower-cased) match → substring scan against the
    table keys → fallback. Substring matching handles LiteLLM's
    ``provider/model`` prefix (the table only carries the bare model
    name) and partial version strings.
    """
    key = model.lower()
    if key in _PRICE_TABLE:
        return _PRICE_TABLE[key], True

    # Strip optional provider prefix (``anthropic/...``) → re-check.
    if "/" in key:
        suffix = key.split("/", 1)[1]
        if suffix in _PRICE_TABLE:
            return _PRICE_TABLE[suffix], True

    # Substring scan — most specific (longest) match wins so
    # "claude-opus-4.7-preview" picks up "claude-opus-4.7" before
    # "claude-opus".
    candidates = sorted(
        (k for k in _PRICE_TABLE if k in key),
        key=len,
        reverse=True,
    )
    if candidates:
        return _PRICE_TABLE[candidates[0]], True

    return _FALLBACK_RATE, False


# ── Budget gating ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BudgetCheck:
    """Verdict from :func:`should_continue`.

    ``allowed`` is the headline bool the loop branches on; ``reason``
    carries a human-readable explanation that propagates into the
    final result + audit log.
    """

    allowed: bool
    spent_usd: float
    budget_usd: float
    reason: str


def should_continue(
    spent_usd: float,
    *,
    budget_usd: float = DEFAULT_MAX_USD_PER_SESSION,
) -> BudgetCheck:
    """Decide whether the agent loop may run another iteration.

    Called BEFORE every LLM round-trip (including the first), so:

      * On the first call ``spent_usd`` is 0 → always allowed unless
        the operator set a degenerate ``budget_usd <= 0``.
      * After each attempt, ``spent_usd`` is recomputed from the
        accumulated attempt costs.

    The gate is intentionally simple — no time-based, per-IP, or
    rolling-window logic. Per-session budget is enough for v1.0; the
    cost-ledger middleware (S8) handles the org-wide aggregation.
    """
    if budget_usd <= 0:
        return BudgetCheck(
            allowed=False,
            spent_usd=spent_usd,
            budget_usd=budget_usd,
            reason="budget_usd is non-positive; refuse to call LLM",
        )

    if spent_usd >= budget_usd:
        return BudgetCheck(
            allowed=False,
            spent_usd=spent_usd,
            budget_usd=budget_usd,
            reason=(
                f"session budget exhausted: "
                f"${spent_usd:.4f} >= ${budget_usd:.4f}"
            ),
        )

    return BudgetCheck(
        allowed=True,
        spent_usd=spent_usd,
        budget_usd=budget_usd,
        reason="within budget",
    )
