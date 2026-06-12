"""Runtime risk manager — the safety net between strategy and venue.

Sprint-S8 deliverable. The strategy emits an ``OrderIntent``; the
runtime asks the :class:`RiskManager` "may I submit this?" before
handing it to the order router. The manager runs a stack of rules
and shorts on the first block.

Three v1 rules ship here:

  * :class:`MaxPositionRule` — cap the **notional** value of the
    held position (units × last close). Catches strategies that
    drift into oversized exposure regardless of how their PnL is
    going.

  * :class:`MaxDrawdownRule` — block new orders once equity drops
    by more than X% from its peak. A "kill switch" for losing
    streaks; prevents a bug-ridden strategy from chasing losses.

  * :class:`KillSwitch` — operator-controlled toggle. Always-blocking
    when ``.tripped is True``. Wired into the HTTP layer (next PR)
    so an operator can flip it from a dashboard.

The :class:`RiskManager` is a small composer. The Protocol is what
matters: anything quack-typed to ``check(intent, ctx, portfolio,
candle) -> RiskCheckResult`` works. Tests inject their own rules to
exercise the manager's composition logic.

This module is **pure / synchronous** — risk evaluation must be
microsecond-fast (it runs on every intent). Persistence of fired
events into the ``risk_events`` PG table is a downstream concern
(audit log writer subscribes to the runtime's RuntimeEvent stream).
"""

from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError, dataclass, replace
from decimal import Decimal
from typing import Protocol

from app.connectors.protocol import OrderIntent, OrderSide
from app.domain.market_data import Candle
from app.strategy_engine.backtest.engine import StrategyContext
from app.strategy_engine.backtest.portfolio import Portfolio

logger = logging.getLogger("risk_manager")


# ── Verdict + Protocol ───────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RiskCheckResult:
    """One rule's verdict on one OrderIntent.

    ``allowed=False`` blocks the intent. ``rule_id`` is the stable
    machine-readable name (used in audit logs); ``reason`` is the
    human-readable explanation.

    On allow, ``reason`` defaults to empty — saves an allocation
    on the hot path (every intent invokes every rule's check).
    """

    allowed: bool
    rule_id: str = ""
    reason: str = ""

    @classmethod
    def allow(cls) -> RiskCheckResult:
        """Pre-allocated allow result. Most checks return this in the
        common case; reusing a singleton saves GC churn on hot path."""
        return _ALLOW_SINGLETON


_ALLOW_SINGLETON = RiskCheckResult(allowed=True)


class RiskRule(Protocol):
    """Structural type for any risk rule.

    Rules MUST be pure — no I/O, no async, no shared state. The
    runtime calls ``check`` synchronously between the strategy and
    the order router; a rule that blocks here blocks every intent
    for every strategy on the process.

    ``rule_id`` is a class attribute (or property) used by the
    manager + audit log to identify which rule fired. Convention:
    SCREAMING_SNAKE matching the ``RiskRuleKind`` enum value in
    ``app.domain.risk_rule.models``.
    """

    rule_id: str

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult: ...


# ── Concrete rules ───────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MaxPositionRule:
    """Cap the post-fill notional position value.

    Computes the *would-be* position value if the intent fills at
    the current candle's close. If it exceeds ``max_notional_usd``,
    block.

    Why post-fill, not pre-fill: a SELL that closes a position is
    always safe under this rule. The check is "what would happen
    AFTER this fills" — which is the operationally interesting
    question.

    Why notional (not qty): different symbols have different
    prices; a 1.0 BTC limit looks very different from a 1.0 DOGE
    limit. Notional in USD is the apples-to-apples comparison.

    ``max_notional_usd`` is Decimal so the rule doesn't import a
    float-precision bug into a Decimal-everywhere codebase.
    """

    max_notional_usd: Decimal
    rule_id: str = "MAX_POSITION_PCT"  # matches RiskRuleKind enum

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult:
        position = portfolio.position(intent.symbol)
        # Post-fill qty: BUY adds, SELL subtracts. Same convention
        # as the Portfolio's apply_buy/apply_sell.
        delta = intent.qty if intent.side == OrderSide.BUY else -intent.qty
        post_qty = position.qty + delta
        # ``abs`` so the cap applies symmetrically to long and short.
        # v1.0 is spot-only so post_qty < 0 wouldn't normally happen;
        # defending it costs nothing and prepares for futures.
        notional = abs(post_qty) * candle.close
        if notional > self.max_notional_usd:
            return RiskCheckResult(
                allowed=False,
                rule_id=self.rule_id,
                reason=(
                    f"post-fill notional ${notional} would exceed "
                    f"max ${self.max_notional_usd} "
                    f"({position.qty} + {delta} = {post_qty} × {candle.close})"
                ),
            )
        return RiskCheckResult.allow()


@dataclass(slots=True)
class MaxDrawdownRule:
    """Block new BUY orders once equity drops >= ``max_drawdown_pct``
    from its session peak.

    State held: the running peak equity. The rule observes equity
    through the Portfolio's mark-to-market at the candle's close.
    SELL orders are NOT blocked — letting strategies close losing
    positions is the correct behaviour during drawdown.

    ``max_drawdown_pct`` is expressed as a fraction (0.10 = 10%),
    NOT a percentage scalar. Pin tested.
    """

    max_drawdown_pct: Decimal
    rule_id: str = "MAX_DAILY_LOSS_PCT"  # matches enum
    # Mutable because the rule tracks running peak. Slots-dataclass
    # with default keeps this lean.
    _peak: Decimal = Decimal("0")

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult:
        # SELL is always allowed — closing positions during a
        # drawdown is exactly what this rule is meant to encourage.
        if intent.side == OrderSide.SELL:
            return RiskCheckResult.allow()

        # Mark-to-market against the current candle.
        equity = portfolio.equity({intent.symbol: candle.close})
        # Update running peak. Decimal max() is type-safe.
        if equity > self._peak:
            self._peak = equity

        # Avoid divide-by-zero on a degenerate first tick where the
        # Portfolio's initial cash is 0 (extreme test fixture). In
        # that case there's no peak to drawdown from — allow.
        if self._peak <= 0:
            return RiskCheckResult.allow()

        drawdown = (self._peak - equity) / self._peak
        if drawdown >= self.max_drawdown_pct:
            return RiskCheckResult(
                allowed=False,
                rule_id=self.rule_id,
                reason=(
                    f"equity ${equity} is {float(drawdown * 100):.2f}% "
                    f"below peak ${self._peak}; max allowed drawdown "
                    f"{float(self.max_drawdown_pct * 100):.2f}%"
                ),
            )
        return RiskCheckResult.allow()


@dataclass(slots=True)
class MaxSlippageRule:
    """Block orders when the candle's intra-bar spread suggests
    bad fills.

    Heuristic: a single 1m candle whose ``(high - low) / close``
    exceeds ``max_spread_pct`` indicates either a volatile spike or
    a thin orderbook — both increase the probability that a MARKET
    order will eat through the book and fill far from the strategy's
    expectation.

    The rule **does not** observe the actual fill price (the order
    hasn't been submitted yet). It's a **pre-trade** spread check.
    Post-trade slippage validation is a separate auditing concern,
    not a pre-route gate.

    ``max_spread_pct`` is a fraction (0.02 = 2%). For 1m BTC bars in
    quiet markets the typical spread is 0.05–0.20%; 2% is the
    "something's wrong" threshold. Operators tune per symbol.

    Why this is the right v1 shape:

      * Honest about what we can know pre-fill (the candle's range,
        nothing else)
      * Catches the realistic failure mode (executing during a flash
        crash / wick) without needing an L2 orderbook subscription
      * Symmetrical to LIMIT vs MARKET — strategies that submit
        LIMIT orders in volatile conditions also benefit (their
        IOC variants will reject; their GTC variants will sit
        farther from market than expected)

    SELL is also gated — closing a position during a wick can lock
    in a bad print just as much as opening one.
    """

    max_spread_pct: Decimal
    rule_id: str = "MAX_SLIPPAGE_PCT"  # matches RiskRuleKind enum

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult:
        # Defend against degenerate candles (close=0 in a test
        # fixture, or a wholly-cancelled symbol). A 0-close candle
        # has no defined spread fraction — allow rather than divide.
        if candle.close <= 0:
            return RiskCheckResult.allow()

        spread = (candle.high - candle.low) / candle.close
        if spread > self.max_spread_pct:
            return RiskCheckResult(
                allowed=False,
                rule_id=self.rule_id,
                reason=(
                    f"intra-bar spread "
                    f"{float(spread * 100):.2f}% exceeds max "
                    f"{float(self.max_spread_pct * 100):.2f}% "
                    f"(H={candle.high} L={candle.low} C={candle.close})"
                ),
            )
        return RiskCheckResult.allow()


@dataclass(slots=True)
class AbnormalCandleRule:
    """Block orders when a candle looks structurally broken or
    statistically extreme.

    Three sub-conditions, any one trips the block:

      1. **Volume-zero candle**: ``candle.volume <= 0`` while price
         moves are non-trivial. Indicates either exchange feed
         corruption or a halt+restart sequence — either way,
         executing into it is unsafe.

      2. **Price-jump candle**: ``(close - history[-2].close) /
         history[-2].close`` exceeds ``max_price_jump_pct``. Catches
         flash-crash / flash-rally bars where the prior-bar close
         is wildly out of line with the current close.

      3. **Candle of zero range**: ``high == low`` AND ``volume > 0``
         is a stale-feed indicator on liquid pairs. Some venues emit
         this when they fail to update; the strategy shouldn't trade
         on stale prices.

    Why this is the v1 stand-in for full L2-orderbook anomaly
    detection: the runtime doesn't have an orderbook subscription
    wired in yet (S9). Candle-level heuristics catch most of the
    realistic feed-corruption / halt-symbol scenarios with the data
    we DO have.

    ``max_price_jump_pct`` is a fraction (0.10 = 10% jump bar-to-bar
    is suspicious). Operators tune per symbol — illiquid alts may
    legitimately gap 20%; majors should never.

    Needs at least 2 candles of history; first tick falls through
    to allow (rule defers until it has a comparison baseline).
    """

    max_price_jump_pct: Decimal
    rule_id: str = "ABNORMAL_ORDERBOOK"  # matches RiskRuleKind enum

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult:
        # Sub-condition 1: volume-zero with price motion.
        if candle.volume <= 0 and candle.high != candle.low:
            return RiskCheckResult(
                allowed=False,
                rule_id=self.rule_id,
                reason=(
                    f"candle has zero volume but non-flat price "
                    f"(H={candle.high} L={candle.low}) — feed "
                    "may be corrupted or symbol halted"
                ),
            )

        # Sub-condition 3: zero-range with volume — stale tick.
        if candle.high == candle.low and candle.volume > 0:
            return RiskCheckResult(
                allowed=False,
                rule_id=self.rule_id,
                reason=(
                    f"candle has zero range (H==L=={candle.high}) "
                    f"but volume {candle.volume} — likely stale feed"
                ),
            )

        # Sub-condition 2: bar-to-bar jump exceeds threshold.
        # Needs a predecessor candle in history. ctx.history[-1] is
        # the CURRENT candle (already appended by the runtime); we
        # want history[-2] for the prior bar.
        if len(ctx.history) >= 2:
            prev_close = ctx.history[-2].close
            if prev_close > 0:
                jump = abs(candle.close - prev_close) / prev_close
                if jump > self.max_price_jump_pct:
                    return RiskCheckResult(
                        allowed=False,
                        rule_id=self.rule_id,
                        reason=(
                            f"bar-to-bar price jump "
                            f"{float(jump * 100):.2f}% exceeds max "
                            f"{float(self.max_price_jump_pct * 100):.2f}% "
                            f"({prev_close} → {candle.close})"
                        ),
                    )

        return RiskCheckResult.allow()


@dataclass(slots=True)
class KillSwitch:
    """Operator-controlled hard stop.

    ``trip()`` flips the switch; once tripped, every subsequent
    check blocks. ``reset()`` un-trips (for cases where the
    operator needs to recover after a fault).

    The reason carried in :attr:`tripped_reason` is intended for
    audit log entries — operators should always include WHY they
    tripped the switch.
    """

    rule_id: str = "EMERGENCY_HALT"
    tripped: bool = False
    tripped_reason: str = ""

    def trip(self, reason: str) -> None:
        """Activate the switch. Idempotent — re-tripping is OK but
        the original reason is preserved (don't overwrite the first
        operator's audit trail)."""
        if not self.tripped:
            self.tripped = True
            self.tripped_reason = reason
            logger.warning("KillSwitch tripped: %s", reason)

    def reset(self) -> None:
        """Un-trip. Use sparingly; document the recovery rationale
        in the operator runbook."""
        self.tripped = False
        self.tripped_reason = ""

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult:
        if self.tripped:
            return RiskCheckResult(
                allowed=False,
                rule_id=self.rule_id,
                reason=f"kill switch tripped: {self.tripped_reason}",
            )
        return RiskCheckResult.allow()


# ── Live threshold patching (change_threshold approval, 3.1) ─────


class RiskThresholdPatchError(ValueError):
    """A change_threshold request named an unknown rule, a field that is
    not an operator-patchable threshold, or a non-positive value."""


# Whitelist of operator-patchable threshold fields, keyed by ``rule_id``.
# This is the security boundary for the reflective patch: an approved
# change_threshold may ONLY touch these numeric thresholds — never a rule's
# internal state (``_peak``), its ``rule_id``, or any other attribute.
# KillSwitch (EMERGENCY_HALT) is intentionally absent — it has no tunable
# threshold; halting is the halt_all action, not a threshold change.
_PATCHABLE_FIELDS: dict[str, frozenset[str]] = {
    "MAX_POSITION_PCT": frozenset({"max_notional_usd"}),
    "MAX_DAILY_LOSS_PCT": frozenset({"max_drawdown_pct"}),
    "MAX_SLIPPAGE_PCT": frozenset({"max_spread_pct"}),
    "ABNORMAL_ORDERBOOK": frozenset({"max_price_jump_pct"}),
}


# ── Manager ──────────────────────────────────────────────────────


class RiskManager:
    """Composes rules; short-circuits on first block.

    The manager owns the rule list. Adding a rule at runtime
    (e.g. operator deploys a new max-loss limit) is supported via
    ``add_rule``; runtime removal isn't (operators flip kill-switch
    instead, which is the correct semantic for "stop trading").

    Why short-circuit-on-first-block: keeps the hot path fast and
    the audit log clean. A blocked intent should produce ONE
    explanation, not three competing ones; the operator who reads
    the alert wants "kill switch tripped" — not also "max position
    would exceed" (irrelevant if the switch is on).
    """

    def __init__(self, rules: list[RiskRule] | None = None) -> None:
        self._rules: list[RiskRule] = list(rules) if rules else []

    def add_rule(self, rule: RiskRule) -> None:
        self._rules.append(rule)

    def patch_threshold(self, rule_id: str, field: str, value: Decimal) -> RiskRule:
        """Set a live rule's numeric threshold (change_threshold approval).

        Whitelisted reflection: ``rule_id`` must name a rule with patchable
        thresholds and ``field`` must be one of its allowed threshold fields
        (see :data:`_PATCHABLE_FIELDS`) — anything else raises
        :class:`RiskThresholdPatchError`. ``value`` must be a positive Decimal.

        Mutable rules are patched **in place** so running state (e.g. a
        MaxDrawdownRule's accrued ``_peak``) survives the threshold change;
        the frozen MaxPositionRule is swapped for a ``dataclasses.replace``
        copy. Returns the (possibly new) rule object.
        """
        allowed = _PATCHABLE_FIELDS.get(rule_id)
        if allowed is None:
            raise RiskThresholdPatchError(
                f"rule {rule_id!r} has no patchable thresholds; "
                f"patchable rules: {sorted(_PATCHABLE_FIELDS)}"
            )
        if field not in allowed:
            raise RiskThresholdPatchError(
                f"field {field!r} is not patchable on {rule_id!r}; allowed: {sorted(allowed)}"
            )
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        if value <= 0:
            raise RiskThresholdPatchError(f"threshold {field!r} must be positive, got {value}")

        for i, rule in enumerate(self._rules):
            if getattr(rule, "rule_id", None) != rule_id:
                continue
            try:
                setattr(rule, field, value)  # mutable slots-dataclass
            except FrozenInstanceError:
                # Frozen rule → swap a replaced copy. replace() wants a concrete
                # dataclass; RiskRule is a Protocol so mypy can't prove it, but
                # every concrete rule IS a dataclass at runtime.
                self._rules[i] = replace(rule, **{field: value})  # type: ignore[type-var]
            logger.warning("RiskManager.patch_threshold: %s.%s set to %s", rule_id, field, value)
            return self._rules[i]

        raise RiskThresholdPatchError(f"no active rule with id {rule_id!r} in this manager")

    @property
    def rules(self) -> tuple[RiskRule, ...]:
        """Read-only snapshot of the current rule list. Returns a
        tuple to discourage callers from mutating the manager's
        internal state."""
        return tuple(self._rules)

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult:
        """Evaluate all rules in registration order. First block wins.

        Returns ``RiskCheckResult.allow()`` if every rule allowed.
        """
        for rule in self._rules:
            result = rule.check(intent, ctx=ctx, portfolio=portfolio, candle=candle)
            if not result.allowed:
                logger.info(
                    "RiskManager blocked intent: %s (%s)",
                    result.rule_id,
                    result.reason,
                )
                return result
        return RiskCheckResult.allow()
