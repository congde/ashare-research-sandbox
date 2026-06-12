"""Unit tests for the lookahead-bias linter.

Each test pins ONE rule: clean code on the negative path, biased code
on the positive path. The contract is that every flagged finding
produces an actionable ``message`` and ``suggestion`` — the LLM
Strategy Architect prompt feeds these back, so vague output is a
regression.
"""

from __future__ import annotations

from app.strategy_engine.dsl import (
    LookaheadFinding,
    check_lookahead_bias,
)

# ── Negative path: clean code passes ─────────────────────────────


def test_clean_strategy_has_no_findings() -> None:
    """Textbook SMA-cross — past-only data access, no suspicious names.
    Must emit zero findings."""
    code = """
def on_tick(ctx, candle):
    if len(ctx.history) < 50:
        return None
    closes = [c.close for c in ctx.history[-50:]]
    short = sum(closes[-20:]) / 20
    long_ = sum(closes) / 50
    if short > long_:
        return ctx.order_intent(side="buy", qty=0.001, type="market")
    return None
"""
    report = check_lookahead_bias(code)
    assert report.clean is True
    assert report.findings == ()


def test_negative_indices_on_history_are_fine() -> None:
    """``history[-1]`` is "now"; ``history[-2]`` is "prior bar". Both
    are the normal pattern, NOT a finding."""
    code = """
def on_tick(ctx, candle):
    if len(ctx.history) < 2:
        return None
    prev = ctx.history[-2]
    if candle.close > prev.close:
        return ctx.order_intent(side="buy", qty=0.001, type="market")
    return None
"""
    report = check_lookahead_bias(code)
    assert report.clean is True


def test_slicing_with_negative_indices_is_fine() -> None:
    """``history[-50:]`` is the last 50 bars — normal. Should not fire
    L004 (which only targets POSITIVE int subscripts)."""
    code = """
def on_tick(ctx, candle):
    window = ctx.history[-50:]
    return None
"""
    report = check_lookahead_bias(code)
    assert report.clean is True


# ── L001: banned attribute prefixes ──────────────────────────────


def test_l001_flags_ctx_future_attribute() -> None:
    """``ctx.future_close`` — the canonical naming-heuristic bias.
    Must fire L001 with severity=error."""
    code = """
def on_tick(ctx, candle):
    if ctx.future_close > candle.close:
        return ctx.order_intent(side="buy", qty=0.001, type="market")
    return None
"""
    report = check_lookahead_bias(code)
    assert report.clean is False
    err = _find_one(report.findings, rule="L001")
    assert err.severity == "error"
    assert "future" in err.message.lower()
    # The suggestion must contain at least one of the alternative idioms.
    assert err.suggestion is not None
    assert "planned" in err.suggestion or "past" in err.suggestion


def test_l001_flags_tomorrow_prefix() -> None:
    """``tomorrow_price`` — flagged by the tomorrow_ prefix rule."""
    code = """
def on_tick(ctx, candle):
    p = ctx.tomorrow_price
    return None
"""
    report = check_lookahead_bias(code)
    assert _find_one(report.findings, rule="L001").severity == "error"


def test_l001_flags_lookahead_attribute() -> None:
    """Strategies sometimes literally name an attribute ``lookahead``
    when they're being explicit about it. The linter still flags."""
    code = """
def on_tick(ctx, candle):
    if ctx.lookahead:
        return None
    return None
"""
    report = check_lookahead_bias(code)
    assert _find_one(report.findings, rule="L001").severity == "error"


def test_l001_does_not_flag_unrelated_attribute() -> None:
    """An attribute named ``next_action`` should NOT match because
    ``next_action`` is not in the prefix list (only ``next_bar`` /
    ``next_candle`` are). False-positive guard."""
    code = """
def on_tick(ctx, candle):
    plan = ctx.next_action
    return None
"""
    report = check_lookahead_bias(code)
    # No L001 findings on ``next_action`` — must stay clean.
    assert not any(f.rule == "L001" for f in report.findings)


# ── L002: shift(-N) ──────────────────────────────────────────────


def test_l002_flags_pandas_negative_shift() -> None:
    """``df.shift(-5)`` aligns 5-step-ahead data into the current row.
    The textbook bias signature."""
    code = """
def on_tick(ctx, candle):
    df = ctx.dataframe
    future_close = df["close"].shift(-5)
    return None
"""
    report = check_lookahead_bias(code)
    err = _find_one(report.findings, rule="L002")
    assert err.severity == "error"
    assert "shift" in err.message.lower()
    assert err.suggestion is not None
    assert "positive" in err.suggestion.lower()


def test_l002_does_not_flag_positive_shift() -> None:
    """``df.shift(5)`` lags PAST data into the present — legitimate."""
    code = """
def on_tick(ctx, candle):
    df = ctx.dataframe
    prior_close = df["close"].shift(5)
    return None
"""
    report = check_lookahead_bias(code)
    assert not any(f.rule == "L002" for f in report.findings)


def test_l002_does_not_flag_shift_with_variable_arg() -> None:
    """``df.shift(n)`` with a variable can't be statically classified.
    Linter conservatively skips — better than false-positive every
    legitimate parameterised shift."""
    code = """
def on_tick(ctx, candle):
    n = compute_lag()
    df = ctx.dataframe
    out = df["close"].shift(n)
    return None
"""
    report = check_lookahead_bias(code)
    assert not any(f.rule == "L002" for f in report.findings)


# ── L003: roll(-N) ───────────────────────────────────────────────


def test_l003_flags_numpy_negative_roll() -> None:
    """``np.roll(arr, -3)`` — same bias as shift(-N) but for arrays."""
    code = """
def on_tick(ctx, candle):
    import numpy as np
    arr = ctx.arr
    rolled = np.roll(arr, -3)
    return None
"""
    report = check_lookahead_bias(code)
    err = _find_one(report.findings, rule="L003")
    assert err.severity == "error"


# ── L004: positive int subscript on history ──────────────────────


def test_l004_warns_on_positive_int_history_subscript() -> None:
    """``ctx.history[5]`` is the 6th bar from the start of the
    backtest. Often a bug, but legitimate for warm-up logic.
    Warning, not error."""
    code = """
def on_tick(ctx, candle):
    first_bar = ctx.history[5]
    return None
"""
    report = check_lookahead_bias(code)
    finding = _find_one(report.findings, rule="L004")
    assert finding.severity == "warning"
    # Warning-only ⇒ clean stays True (clean tracks errors only).
    assert report.clean is True


def test_l004_does_not_warn_on_zero_index() -> None:
    """``history[0]`` is unambiguously the oldest bar — well-defined,
    not suspicious."""
    code = """
def on_tick(ctx, candle):
    oldest = ctx.history[0]
    return None
"""
    report = check_lookahead_bias(code)
    assert not any(f.rule == "L004" for f in report.findings)


# ── Reporting / aggregation ──────────────────────────────────────


def test_multiple_findings_all_recorded() -> None:
    """One file can contain multiple distinct bias patterns. The
    linter must surface ALL of them, not just the first."""
    code = """
def on_tick(ctx, candle):
    a = ctx.future_close
    b = ctx.tomorrow_open
    c = ctx.history[10]
    return None
"""
    report = check_lookahead_bias(code)
    # 2 errors + 1 warning
    assert len(report.errors) == 2
    assert len(report.warnings) == 1
    assert not report.clean


def test_findings_include_line_and_col() -> None:
    """Every finding must carry source coordinates so the UI can
    highlight the bad line."""
    code = """
def on_tick(ctx, candle):
    pass

def helper():
    return ctx.future_x
"""
    report = check_lookahead_bias(code)
    err = _find_one(report.findings, rule="L001")
    # The ``ctx.future_x`` reference is on line 6 (1-indexed).
    assert err.line == 6
    assert err.col >= 0


def test_clean_property_tracks_errors_only() -> None:
    """``LookaheadReport.clean`` is True iff there are no ERROR
    findings; pure warnings don't flip it. UI uses this to decide
    whether to allow strategy submission."""
    code = """
def on_tick(ctx, candle):
    x = ctx.history[3]  # warning, not error
    return None
"""
    report = check_lookahead_bias(code)
    assert report.warnings  # there IS a warning
    assert report.clean is True  # but report still "clean" for gating


# ── Helpers ──────────────────────────────────────────────────────


def _find_one(
    findings: tuple[LookaheadFinding, ...], *, rule: str
) -> LookaheadFinding:
    """Locate the single finding for a rule. Raises if 0 or > 1 —
    keeps tests honest about exactly which finding they're inspecting."""
    matches = [f for f in findings if f.rule == rule]
    assert len(matches) == 1, (
        f"Expected exactly one {rule} finding, got {len(matches)}: {matches}"
    )
    return matches[0]
