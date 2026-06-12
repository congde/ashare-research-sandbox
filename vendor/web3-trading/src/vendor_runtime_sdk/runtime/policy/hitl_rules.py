# -*- coding: utf-8 -*-
"""
Mid-run HITL PolicyEngine rules — §S6 / Gap 6.

Extends :class:`runtime.policy.engine.PolicyEngine` with four rules that
route dangerous / high-cost / off-whitelist tool calls into the existing
HITL ``ask`` path:

  * ``hitl_destructive_shell``    priority 1500 — rm -rf / dd / mkfs / fork bomb
  * ``hitl_destructive_sql``      priority 1400 — DROP TABLE / TRUNCATE / DELETE
  * ``hitl_high_token_llm``       priority 1300 — single LLM call > N tokens
  * ``hitl_non_whitelist_git``    priority 1200 — git subcommand not in §Gap 2 whitelist
  * ``hitl_high_cost_api``        priority 1100 — cumulative cost > USD threshold

Each rule returns ``action_type="ask"`` so :class:`PermissionResolver`
short-circuits to the existing HITL pending queue (``loop.py`` already
handles this — no runtime wiring changes needed).  Higher priority than
the base deny rule ``risk_destructive_bash`` (1000) so the human
approval path takes precedence: a supervised user can still run a
destructive command *if* they explicitly confirm it.

Guarded by the ``mid_run_hitl_policy`` toggle (default OFF per S6 opt-in
rollout).  When disabled, the rules are not loaded and the engine keeps
its existing defaults (deny destructive bash, etc.).

Thresholds are configurable via environment variables so Ops can tune
without a redeploy:

    MID_RUN_HITL_TOKEN_CAP   default 20000  (per-call token ceiling)
    MID_RUN_HITL_COST_USD    default 1.0    (per-task cumulative USD ceiling)

Required context keys (populated by caller before ``PolicyEngine.evaluate``):

    tool_name                     always populated by PermissionResolver
    args                          always populated by PermissionResolver
    token_budget_estimate  int    max(planner_token_estimate, max_tokens)
                                  Populated by the LLM gateway before the call.
    cumulative_cost_usd_x1000 int task-cumulative cost * 1000 (integer; avoids
                                  float quirks in safe-eval).  Populated by
                                  CostTrackingHook between turns.

When the caller does not populate the optional keys, the condition safely
evaluates to ``False`` (returns ``0`` < threshold) and the rule does not fire.

Usage
-----

>>> from runtime.policy.engine import PolicyEngine
>>> from runtime.policy.hitl_rules import attach_hitl_rules
>>> engine = PolicyEngine()
>>> attach_hitl_rules(engine)   # no-op if toggle is off
>>> engine.evaluate({"tool_name": "terminal", "args": {"command": "rm -rf /"}})
PolicyDecision(allowed=False, action_type='ask', ...)
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from vendor_runtime_sdk.runtime.policy.engine import Action, PolicyEngine, PolicyRule

logger = logging.getLogger(__name__)

__all__ = [
    "HITL_RULE_IDS",
    "attach_hitl_rules",
    "build_hitl_rules",
    "get_hitl_token_cap",
    "get_hitl_cost_usd_cap",
]


HITL_RULE_IDS: frozenset[str] = frozenset(
    {
        "hitl_destructive_shell",
        "hitl_destructive_sql",
        "hitl_high_token_llm",
        "hitl_non_whitelist_git",
        "hitl_high_cost_api",
    }
)


# ── Thresholds (env-tunable) ────────────────────────────────────────────

_DEFAULT_TOKEN_CAP = 20_000
_DEFAULT_COST_USD = 1.0


def get_hitl_token_cap() -> int:
    """Per-call LLM token ceiling that triggers the HITL ask rule."""
    raw = os.getenv("MID_RUN_HITL_TOKEN_CAP", "").strip()
    if not raw:
        return _DEFAULT_TOKEN_CAP
    try:
        cap = int(raw)
    except ValueError:
        logger.warning(
            "MID_RUN_HITL_TOKEN_CAP=%r is not an int — falling back to %d",
            raw, _DEFAULT_TOKEN_CAP,
        )
        return _DEFAULT_TOKEN_CAP
    return cap if cap > 0 else _DEFAULT_TOKEN_CAP


def get_hitl_cost_usd_cap() -> float:
    """Per-task cumulative cost (USD) ceiling that triggers the HITL rule."""
    raw = os.getenv("MID_RUN_HITL_COST_USD", "").strip()
    if not raw:
        return _DEFAULT_COST_USD
    try:
        cap = float(raw)
    except ValueError:
        logger.warning(
            "MID_RUN_HITL_COST_USD=%r is not a float — falling back to %.2f",
            raw, _DEFAULT_COST_USD,
        )
        return _DEFAULT_COST_USD
    return cap if cap > 0 else _DEFAULT_COST_USD


# ── Toggle gate ─────────────────────────────────────────────────────────


def _toggle_enabled() -> bool:
    """Returns True iff ``mid_run_hitl_policy`` is enabled.

    Fail-open on toggle lookup errors (matches the pattern used by
    ``AgentTaskQueueDispatcher._cas_enabled`` — a busted toggle lookup
    should never block production).  A missing toggle system is treated
    as disabled (the rules are opt-in by default).
    """
    try:
        from vendor_runtime_sdk.runtime.config.toggles import get_toggles

        return bool(get_toggles().is_enabled("mid_run_hitl_policy"))
    except Exception as exc:
        logger.debug("HITL toggle lookup failed: %s", exc)
        return False


# ── Rule builders ───────────────────────────────────────────────────────


def build_hitl_rules(
    token_cap: Optional[int] = None,
    cost_usd_cap: Optional[float] = None,
) -> List[PolicyRule]:
    """Return the ordered S6 HITL rules.

    Parameters
    ----------
    token_cap : int, optional
        Override :func:`get_hitl_token_cap`.
    cost_usd_cap : float, optional
        Override :func:`get_hitl_cost_usd_cap`.
    """
    token_cap = token_cap if token_cap is not None else get_hitl_token_cap()
    cost_usd_cap = cost_usd_cap if cost_usd_cap is not None else get_hitl_cost_usd_cap()

    rules: List[PolicyRule] = [
        PolicyRule(
            id="hitl_destructive_shell",
            priority=1500,
            condition=(
                'tool_name in ("terminal","bash","exec") '
                'and is_destructive(args.get("command", ""))'
            ),
            action_chain=[
                Action(
                    type="ask",
                    params={
                        "message": (
                            "Destructive shell command detected (rm -rf / dd / "
                            "mkfs / fork bomb). Confirm before running."
                        ),
                        "category": "destructive_shell",
                    },
                ),
                Action(type="alert", params={"channel": "log", "severity": "high"}),
            ],
        ),
        PolicyRule(
            id="hitl_destructive_sql",
            priority=1400,
            condition=(
                'is_destructive_sql(args.get("command", "")) '
                'or is_destructive_sql(args.get("sql", "")) '
                'or is_destructive_sql(args.get("query", ""))'
            ),
            action_chain=[
                Action(
                    type="ask",
                    params={
                        "message": (
                            "Destructive SQL statement detected (DROP TABLE / "
                            "TRUNCATE / unconstrained DELETE or UPDATE). "
                            "Confirm before running."
                        ),
                        "category": "destructive_sql",
                    },
                ),
                Action(type="alert", params={"channel": "log", "severity": "high"}),
            ],
        ),
        PolicyRule(
            id="hitl_high_token_llm",
            priority=1300,
            # Caller populates ``token_budget_estimate`` as a top-level context
            # key (max of the planner's token_estimate and the request's
            # max_tokens).  Flattening keeps the AST shallow enough for the
            # safe-eval depth budget.
            condition=f"token_budget_estimate >= {token_cap}",
            action_chain=[
                Action(
                    type="ask",
                    params={
                        "message": (
                            f"Large LLM call (>= {token_cap} tokens) — "
                            "confirm budget before proceeding."
                        ),
                        "category": "high_token_llm",
                        "token_cap": token_cap,
                    },
                ),
            ],
        ),
        PolicyRule(
            id="hitl_non_whitelist_git",
            priority=1200,
            condition=(
                'tool_name in ("terminal","bash","exec","git") '
                'and is_non_whitelist_git(args.get("command", ""))'
            ),
            action_chain=[
                Action(
                    type="ask",
                    params={
                        "message": (
                            "Git command outside the §Gap 2 whitelist (merge / "
                            "cherry-pick / revert / rebase / reset --hard / "
                            "force push). Confirm before running."
                        ),
                        "category": "non_whitelist_git",
                    },
                ),
                Action(type="alert", params={"channel": "log", "severity": "medium"}),
            ],
        ),
        PolicyRule(
            id="hitl_high_cost_api",
            priority=1100,
            # CostTrackingHook populates ``cumulative_cost_usd_x1000`` as a
            # top-level context key (cost * 1000, integer) before the next
            # tool call.  Multiply by 1000 to avoid float comparisons in the
            # safe-eval sandbox.
            condition=f"cumulative_cost_usd_x1000 >= {int(cost_usd_cap * 1000)}",
            action_chain=[
                Action(
                    type="ask",
                    params={
                        "message": (
                            f"Cumulative external API cost >= ${cost_usd_cap:.2f} "
                            "for this task — confirm budget before further spend."
                        ),
                        "category": "high_cost_api",
                        "cost_cap_usd": cost_usd_cap,
                    },
                ),
            ],
        ),
    ]
    return rules


def attach_hitl_rules(engine: PolicyEngine, *, force: bool = False) -> int:
    """Register the S6 HITL rules on *engine*.

    Returns the number of rules actually attached.  When the toggle is
    off and ``force=False``, the call is a no-op and returns ``0`` —
    this keeps the rules out of production until Ops opts in.  Tests
    pass ``force=True`` to exercise the rule set directly.

    Idempotent: re-registering a rule replaces the existing entry (the
    engine uses ``rule.id`` for dedup).
    """
    if not force and not _toggle_enabled():
        logger.debug("mid_run_hitl_policy disabled — not attaching HITL rules")
        return 0

    rules = build_hitl_rules()
    for rule in rules:
        engine.add_rule(rule)
    logger.info(
        "PolicyEngine: attached %d S6 HITL rules — %s",
        len(rules), [r.id for r in rules],
    )
    return len(rules)
