"""Unit tests for candle validation + multi-timeframe resampling.

Two boundaries:

  * ``validate_candles(candles, timeframe)`` — must catch the common
    bad-data shapes (gaps, monotonicity, OHLC, volume).
  * ``resample_candles(candles, from, to)`` — must produce OHLC-correct
    output buckets and refuse impossible conversions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.market_data import Candle
from app.strategy_engine.backtest import (
    resample_candles,
    validate_candles,
)

# ── Helpers ──────────────────────────────────────────────────────


def _candle(
    ts: datetime,
    *,
    open_: float = 100.0,
    high: float | None = None,
    low: float | None = None,
    close: float = 100.0,
    volume: float = 1.0,
    timeframe: str = "1m",
    quote_volume: float | None = None,
) -> Candle:
    """Convenient builder. Defaults to a flat OHLC at 100.0 with
    volume 1.0 — useful as the "happy path" candle."""
    return Candle(
        exchange="test",
        symbol="BTC/USDT",
        timeframe=timeframe,
        ts=ts,
        open=Decimal(f"{open_:.4f}"),
        high=Decimal(f"{(high if high is not None else max(open_, close)):.4f}"),
        low=Decimal(f"{(low if low is not None else min(open_, close)):.4f}"),
        close=Decimal(f"{close:.4f}"),
        volume=Decimal(f"{volume:.4f}"),
        quote_volume=Decimal(f"{quote_volume:.4f}") if quote_volume is not None else None,
    )


def _series_1m(start: datetime, n: int) -> list[Candle]:
    """Synthesise N consecutive 1m candles starting at ``start``."""
    return [_candle(start + timedelta(minutes=i)) for i in range(n)]


# ── validate_candles ─────────────────────────────────────────────


def test_validate_empty_list_returns_c001() -> None:
    """Empty input is rejected outright with C001 — and NO downstream
    checks should run (avoid spamming irrelevant findings)."""
    errors = validate_candles([], "1m")
    assert len(errors) == 1
    assert errors[0].rule == "C001"


def test_validate_clean_series_returns_no_errors() -> None:
    """The happy path: 1m series with monotonic timestamps + valid
    OHLC + positive volume → zero errors."""
    candles = _series_1m(datetime(2026, 1, 1, tzinfo=UTC), 10)
    assert validate_candles(candles, "1m") == []


def test_validate_catches_non_monotonic_timestamps() -> None:
    """Two candles at the same timestamp → C002 monotonicity."""
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    c1 = _candle(ts)
    c2 = _candle(ts)  # same ts
    errors = validate_candles([c1, c2], "1m")
    assert any(e.rule == "C002" for e in errors)


def test_validate_catches_gap() -> None:
    """A missing bar between ts and ts+2m → C003 cadence mismatch."""
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    c1 = _candle(ts)
    c3 = _candle(ts + timedelta(minutes=2))  # skipped ts+1m
    errors = validate_candles([c1, c3], "1m")
    cadence_errors = [e for e in errors if e.rule == "C003"]
    assert len(cadence_errors) == 1
    assert cadence_errors[0].candle_index == 1


def test_validate_catches_ohlc_violation() -> None:
    """open > high should be impossible. C004 fires."""
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    bad = _candle(ts, open_=110.0, high=100.0, low=90.0, close=95.0)
    errors = validate_candles([bad], "1m")
    assert any(e.rule == "C004" for e in errors)


def test_validate_catches_negative_volume() -> None:
    """Volume is a count of base asset traded; negative is impossible.
    C005 fires."""
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    bad = _candle(ts, volume=-1.0)
    errors = validate_candles([bad], "1m")
    assert any(e.rule == "C005" for e in errors)


def test_validate_reports_all_issues_not_just_first() -> None:
    """Mirror DSL validator philosophy — multiple problems must all
    surface so the caller can fix them in one pass."""
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    c1 = _candle(ts, open_=110.0, high=100.0, low=90.0, close=95.0)  # C004
    c2 = _candle(ts, volume=-2.0)  # C002 (same ts) + C005
    errors = validate_candles([c1, c2], "1m")
    rules = {e.rule for e in errors}
    assert {"C002", "C004", "C005"} <= rules


def test_validate_respects_declared_timeframe() -> None:
    """Same candle series declared as 5m vs 1m → different cadence
    verdicts. 1m candles spaced 1 minute apart are wrong if the user
    claims 5m."""
    candles = _series_1m(datetime(2026, 1, 1, tzinfo=UTC), 4)
    # As 1m → fine.
    assert validate_candles(candles, "1m") == []
    # As 5m → every gap is wrong.
    errors = validate_candles(candles, "5m")
    assert sum(1 for e in errors if e.rule == "C003") >= 1


# ── resample_candles ─────────────────────────────────────────────


def test_resample_empty_returns_empty() -> None:
    """Empty input → empty output. No exception."""
    assert resample_candles([], "1m", "5m") == []


def test_resample_1m_to_5m_aggregates_ohlc_correctly() -> None:
    """5 consecutive 1m candles with known O/H/L/C should produce ONE
    5m candle with O=first.open, H=max, L=min, C=last.close."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # Prices: 100, 102, 98, 103, 99. Volumes: 1, 2, 3, 4, 5.
    candles = [
        _candle(base, open_=100.0, high=100.0, low=100.0, close=100.0, volume=1.0),
        _candle(base + timedelta(minutes=1), open_=100.0, high=102.0, low=100.0, close=102.0, volume=2.0),
        _candle(base + timedelta(minutes=2), open_=102.0, high=102.0, low=98.0, close=98.0, volume=3.0),
        _candle(base + timedelta(minutes=3), open_=98.0, high=103.0, low=98.0, close=103.0, volume=4.0),
        _candle(base + timedelta(minutes=4), open_=103.0, high=103.0, low=99.0, close=99.0, volume=5.0),
    ]
    out = resample_candles(candles, "1m", "5m")
    assert len(out) == 1
    bar = out[0]
    assert bar.timeframe == "5m"
    assert bar.open == Decimal("100.0000")
    assert bar.high == Decimal("103.0000")  # max
    assert bar.low == Decimal("98.0000")    # min
    assert bar.close == Decimal("99.0000")  # last
    assert bar.volume == Decimal("15.0000")  # sum
    # First candle's ts becomes the bucket ts (ccxt / Binance convention)
    assert bar.ts == base


def test_resample_drops_trailing_partial_bucket() -> None:
    """7 × 1m candles aggregated to 5m → 1 full bucket, 2 trailing
    bars dropped. Caller should re-resample when they have a full
    bucket. Documented in the docstring; pin it as test."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = _series_1m(base, 7)
    out = resample_candles(candles, "1m", "5m")
    assert len(out) == 1


def test_resample_handles_multiple_full_buckets() -> None:
    """10 × 1m → exactly 2 × 5m. No partial drops."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = _series_1m(base, 10)
    out = resample_candles(candles, "1m", "5m")
    assert len(out) == 2


def test_resample_identity_returns_copy() -> None:
    """from == to → identity. Returns a copy (caller may mutate the
    output without affecting the input). Useful as a no-op pass-through
    in code that always resamples."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = _series_1m(base, 3)
    out = resample_candles(candles, "1m", "1m")
    assert out == candles
    assert out is not candles  # different list object


def test_resample_rejects_finer_target() -> None:
    """5m → 1m can't synthesise the missing intra-bar data. Refuse."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [_candle(base, timeframe="5m")]
    with pytest.raises(ValueError, match="must be coarser"):
        resample_candles(candles, "5m", "1m")


def test_resample_rejects_non_integer_ratio() -> None:
    """7m isn't a clean multiple of 5m; refuse — no honest OHLC
    interpretation."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [_candle(base, timeframe="5m")]
    with pytest.raises(ValueError, match="integer multiple"):
        resample_candles(candles, "5m", "7m")


def test_resample_quote_volume_sums_when_all_present() -> None:
    """Optional quote_volume: when EVERY input candle has it, the
    output gets the sum. Realistic case — most exchanges populate it."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [
        _candle(base + timedelta(minutes=i), quote_volume=100.0 + i)
        for i in range(5)
    ]
    out = resample_candles(candles, "1m", "5m")
    assert out[0].quote_volume == Decimal("510.0000")  # 100+101+102+103+104


def test_resample_quote_volume_none_when_any_missing() -> None:
    """If even ONE input candle lacks quote_volume, the output is None.
    Better than emitting a misleading partial sum."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [
        _candle(base, quote_volume=100.0),
        _candle(base + timedelta(minutes=1), quote_volume=None),
        _candle(base + timedelta(minutes=2), quote_volume=102.0),
        _candle(base + timedelta(minutes=3), quote_volume=103.0),
        _candle(base + timedelta(minutes=4), quote_volume=104.0),
    ]
    out = resample_candles(candles, "1m", "5m")
    assert out[0].quote_volume is None


def test_resample_aligns_to_unix_epoch() -> None:
    """Bucket alignment uses UNIX epoch, NOT the first input candle.
    Two runs that start at slightly different offsets must produce
    bucket-aligned results so they're directly comparable.

    Input starting at 00:01 (not 00:00) → first 5m bucket [00:00, 00:05)
    is partial (only 4 bars: 00:01, 00:02, 00:03, 00:04). It MUST be
    dropped; the first emitted bar is the bucket starting at 00:05.
    """
    base = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    candles = _series_1m(base, 10)  # 00:01 … 00:10
    out = resample_candles(candles, "1m", "5m")
    # Buckets the candles fall into:
    #   [00:00, 00:05) — partial (4 bars: 00:01–00:04), dropped
    #   [00:05, 00:10) — full   (5 bars: 00:05–00:09), kept
    #   [00:10, 00:15) — partial (1 bar:  00:10), dropped
    assert len(out) == 1
    assert out[0].ts == datetime(2026, 1, 1, 0, 5, tzinfo=UTC)
