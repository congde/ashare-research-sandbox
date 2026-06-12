"""Strategy Card schema — structured output the Strategy Architect
emits alongside generated code.

Sprint-S6 deliverable. Where PR #50's ``GenerationResult`` carries
just the safelist-clean Python code, the card carries the **human-
readable thesis** that explains what the strategy does, when it
should work, when it shouldn't, and what to watch.

Why structured (vs free-form text):

  * The UI renders a consistent shell — operators don't have to
    read free-form prose to understand the strategy intent.
  * Refinement loops can ask the LLM "modify the valid_when
    condition" rather than "modify the strategy" — sharper signal.
  * Audit trail captures the *thesis* not just the code, so a
    later post-mortem can ask "was the thesis sound?" separately
    from "did the implementation match the thesis?"

Schema decisions:

  * ``thesis`` — one sentence, must explain the edge (NOT just the
    pattern). "BTC tends to revert to its 50-day MA when …" beats
    "use SMA crossover".
  * ``valid_when`` — list of conditions where the strategy is
    EXPECTED to outperform. Operators check these against current
    market state before deploying.
  * ``invalid_when`` — explicit failure-mode list. Crucial for
    risk — "high vol regime" / "news-driven gaps" / "low-liquidity
    hours" force the LLM to think about what kills the edge.
  * ``expected_metrics`` — what the author expects the backtest to
    show. ``backtest_metrics_match()`` compares the actual backtest
    against these.
  * ``risk_checklist`` — operator pre-deploy gates that aren't
    captured by the safelist or the risk rules.

This module is pure schema — no LLM calls, no IO. The LLM
prompts in S6-2's SKILL.md drive the LLM to emit JSON matching
this shape; ``parse_card_json`` reconstructs the dataclass.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

# ── Schema ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExpectedMetrics:
    """What the strategy author expects the backtest to show.

    All fields optional — the LLM may omit a metric if it doesn't
    have a reasoned expectation. ``None`` means "no claim". Empty
    string is treated the same as None for the float fields.

    ``backtest_metrics_match`` (below) tolerates either omission
    pattern so the wire shape is forgiving.
    """

    pnl_pct_min: float | None = None
    sharpe_min: float | None = None
    max_drawdown_pct_max: float | None = None
    win_rate_min: float | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True)
class StrategyCard:
    """The structured side-car for a generated strategy.

    Goes alongside the raw Python code in ``GenerationResult``.
    """

    name: str
    thesis: str
    valid_when: tuple[str, ...]
    invalid_when: tuple[str, ...]
    risk_checklist: tuple[str, ...]
    expected_metrics: ExpectedMetrics = field(default_factory=ExpectedMetrics)
    # Optional metadata — symbol / timeframe / version. Useful for
    # the UI but not required for the strategy itself.
    symbol: str = ""
    timeframe: str = ""
    version: int = 1

    def to_json(self) -> str:
        """Canonical JSON serialisation — sort_keys for stable diff
        + audit-log embedding."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


# ── Construction / parsing ──────────────────────────────────────


_REQUIRED_FIELDS = frozenset({"name", "thesis", "valid_when", "invalid_when", "risk_checklist"})


def parse_card_json(raw: str | dict[str, Any]) -> StrategyCard:
    """Build a :class:`StrategyCard` from JSON (or dict).

    Raises :class:`ValueError` on missing required fields or wrong
    type — caller catches and surfaces to the LLM self-correction
    loop (S6-2 handler).

    Defensive about list-vs-tuple — JSON has no tuple, so the input
    arrives as lists; we coerce to tuples to keep the dataclass
    frozen-safe.
    """
    data: dict[str, Any] = json.loads(raw) if isinstance(raw, str) else dict(raw)

    missing = _REQUIRED_FIELDS - data.keys()
    if missing:
        raise ValueError(
            f"strategy card missing required fields: {sorted(missing)}"
        )

    for list_field in ("valid_when", "invalid_when", "risk_checklist"):
        value = data[list_field]
        if not isinstance(value, list | tuple):
            raise ValueError(
                f"strategy card field {list_field!r} must be list; got {type(value).__name__}"
            )
        if not all(isinstance(x, str) for x in value):
            raise ValueError(
                f"strategy card field {list_field!r} must contain only strings"
            )

    raw_metrics = data.get("expected_metrics") or {}
    if not isinstance(raw_metrics, dict):
        raise ValueError(
            f"expected_metrics must be dict; got {type(raw_metrics).__name__}"
        )

    metrics = ExpectedMetrics(
        pnl_pct_min=_to_optional_float(raw_metrics.get("pnl_pct_min")),
        sharpe_min=_to_optional_float(raw_metrics.get("sharpe_min")),
        max_drawdown_pct_max=_to_optional_float(raw_metrics.get("max_drawdown_pct_max")),
        win_rate_min=_to_optional_float(raw_metrics.get("win_rate_min")),
        notes=str(raw_metrics.get("notes", "")),
    )

    return StrategyCard(
        name=str(data["name"]),
        thesis=str(data["thesis"]),
        valid_when=tuple(data["valid_when"]),
        invalid_when=tuple(data["invalid_when"]),
        risk_checklist=tuple(data["risk_checklist"]),
        expected_metrics=metrics,
        symbol=str(data.get("symbol", "")),
        timeframe=str(data.get("timeframe", "")),
        version=int(data.get("version", 1)),
    )


def _to_optional_float(value: Any) -> float | None:
    """Forgiving converter — empty string / None / 'null' all become None."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip() in ("", "null", "none"):
        return None
    return float(value)


# ── Backtest comparison ────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MetricsMatchReport:
    """Per-metric verdict on whether the backtest matched the card's
    expectations. Each field is None when the card didn't make a
    claim; otherwise True (met) or False (missed)."""

    pnl_pct_pass: bool | None = None
    sharpe_pass: bool | None = None
    drawdown_pass: bool | None = None
    win_rate_pass: bool | None = None
    # Headline — True iff every non-None per-metric pass is True.
    overall_pass: bool = False
    notes: str = ""


def backtest_metrics_match(
    card: StrategyCard,
    *,
    pnl_pct: float,
    sharpe: float,
    max_drawdown_pct: float,
    win_rate: float,
) -> MetricsMatchReport:
    """Compare actual backtest metrics against the card's
    expectations.

    Semantics:
      * pnl_pct_min — actual must be >= expected (more profit allowed)
      * sharpe_min — actual must be >= expected
      * max_drawdown_pct_max — actual must be <= expected (less DD allowed)
      * win_rate_min — actual must be >= expected

    Metrics where the card didn't make a claim get pass=None;
    overall_pass is True iff every non-None metric passed.

    Catches the realistic case where the LLM's thesis predicts
    pnl_pct >= 5% but the backtest shows -3% — operator wants to
    know the thesis is broken BEFORE deploying live.
    """
    exp = card.expected_metrics

    def _gte(actual: float, expected: float | None) -> bool | None:
        return actual >= expected if expected is not None else None

    def _lte(actual: float, expected: float | None) -> bool | None:
        return actual <= expected if expected is not None else None

    pnl_pass = _gte(pnl_pct, exp.pnl_pct_min)
    sharpe_pass = _gte(sharpe, exp.sharpe_min)
    dd_pass = _lte(max_drawdown_pct, exp.max_drawdown_pct_max)
    win_pass = _gte(win_rate, exp.win_rate_min)

    per_metric = [pnl_pass, sharpe_pass, dd_pass, win_pass]
    explicit_results = [p for p in per_metric if p is not None]
    overall = bool(explicit_results) and all(explicit_results)

    return MetricsMatchReport(
        pnl_pct_pass=pnl_pass,
        sharpe_pass=sharpe_pass,
        drawdown_pass=dd_pass,
        win_rate_pass=win_pass,
        overall_pass=overall,
        notes="" if explicit_results else "card made no metric claims to verify",
    )
