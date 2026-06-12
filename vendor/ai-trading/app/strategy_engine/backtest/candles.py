"""Candle preprocessing — validation + multi-timeframe resampling.

Sprint-S4 scope: "多 timeframe 回测 (1m / 5m / 15m / 1h / 1d)". Today
``BacktestEngine.run`` accepts a ``timeframe`` string but never
verifies that the candles it received are actually at that timeframe.
That's fine when the caller is the data plane (which writes Candle
rows with the right timeframe in the first place), but breaks the
moment a user wants to run a 5m strategy against 1m data — there's
no resampler.

This module provides two boundaries:

  * :func:`validate_candles` — given a candle list and a declared
    timeframe, fail fast on the obvious-bad shapes: non-monotonic
    timestamps, gaps wider than expected, OHLC invariants violated,
    timeframe / actual cadence mismatch.

  * :func:`resample_candles` — aggregate finer-grained candles into
    coarser ones (1m → 5m, 1h → 1d, etc.). OHLC semantics: open is
    the first bar's open, high is max, low is min, close is the last
    bar's close, volume sums.

Both functions are pure / synchronous and reuse
``app.connectors.ws_aggregator.parse_timeframe`` for the timeframe
string-to-timedelta conversion so we don't duplicate the regex.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.connectors.ws_aggregator import parse_timeframe
from app.domain.market_data import Candle

# ── Validation ───────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CandleValidationError:
    """One detected issue. ``candle_index`` is None for global issues
    (e.g. empty list)."""

    rule: str
    message: str
    candle_index: int | None = None


def validate_candles(
    candles: list[Candle], timeframe: str
) -> list[CandleValidationError]:
    """Static checks on a candle series. Returns ALL problems found,
    not just the first — same philosophy as the DSL validator.

    Rules:

      * **C001** — empty input
      * **C002** — timestamps must be strictly monotonic increasing
      * **C003** — gap between consecutive candles must equal the
        declared timeframe (no missing bars)
      * **C004** — OHLC invariant: low ≤ open ≤ high AND low ≤ close ≤ high
      * **C005** — volume must be ≥ 0

    Returns:
      List of :class:`CandleValidationError`. Empty list means the
      candles are well-formed for ``timeframe``.
    """
    errors: list[CandleValidationError] = []

    if not candles:
        errors.append(
            CandleValidationError(
                rule="C001",
                message="candle list is empty",
            )
        )
        return errors  # no further checks meaningful

    tf_delta = parse_timeframe(timeframe)
    prev: Candle | None = None

    for i, c in enumerate(candles):
        # C004: OHLC invariants. Decimal comparisons — no float drift.
        if not (c.low <= c.open <= c.high and c.low <= c.close <= c.high):
            errors.append(
                CandleValidationError(
                    rule="C004",
                    candle_index=i,
                    message=(
                        f"OHLC invariant violated at ts={c.ts.isoformat()}: "
                        f"O={c.open} H={c.high} L={c.low} C={c.close}"
                    ),
                )
            )

        # C005: non-negative volume.
        if c.volume < 0:
            errors.append(
                CandleValidationError(
                    rule="C005",
                    candle_index=i,
                    message=f"negative volume at ts={c.ts.isoformat()}: {c.volume}",
                )
            )

        # C002 / C003: cadence checks need a predecessor.
        if prev is not None:
            if c.ts <= prev.ts:
                errors.append(
                    CandleValidationError(
                        rule="C002",
                        candle_index=i,
                        message=(
                            f"non-monotonic timestamp at index {i}: "
                            f"prev={prev.ts.isoformat()} curr={c.ts.isoformat()}"
                        ),
                    )
                )
            elif c.ts - prev.ts != tf_delta:
                # Reported as gap whether the actual delta is too
                # small (duplicate-like) or too large (missing bars).
                # Either way it breaks the timeframe contract.
                errors.append(
                    CandleValidationError(
                        rule="C003",
                        candle_index=i,
                        message=(
                            f"cadence mismatch at index {i}: expected "
                            f"{tf_delta}, got {c.ts - prev.ts} "
                            f"(prev={prev.ts.isoformat()}, "
                            f"curr={c.ts.isoformat()})"
                        ),
                    )
                )

        prev = c

    return errors


# ── Resampling ───────────────────────────────────────────────────


def resample_candles(
    candles: list[Candle],
    from_timeframe: str,
    to_timeframe: str,
) -> list[Candle]:
    """Aggregate fine-grained candles into a coarser timeframe.

    Examples: 1m → 5m, 5m → 1h, 1h → 1d. ``to_timeframe`` must be an
    integer multiple of ``from_timeframe``; non-integer ratios raise
    ``ValueError`` (5m → 7m doesn't have a clean OHLC mapping).

    OHLC semantics within each output bucket:

      * open  ← first input candle's open
      * high  ← max(input.high)
      * low   ← min(input.low)
      * close ← last input candle's close
      * volume ← sum(input.volume)
      * quote_volume ← sum if all present, else None
      * ts ← first input candle's ts (bucket start, ccxt convention)

    The function is **conservative on partial buckets**: if the input
    series doesn't divide evenly into ``to_timeframe``, the trailing
    partial bucket is DROPPED rather than emitted with a misleading
    "close" that's actually a mid-bar value. Callers who want partial
    buckets should resample after they have a full final bucket.

    Args:
      candles: source series, already validated at ``from_timeframe``.
      from_timeframe / to_timeframe: ccxt-style strings.

    Raises:
      ValueError: when ``to_timeframe`` isn't an integer multiple of
        ``from_timeframe``, or when timeframes are inverted (asking
        to "resample" 1h → 1m is undefined — we don't synthesise
        finer data from coarser).
    """
    if not candles:
        return []

    from_delta = parse_timeframe(from_timeframe)
    to_delta = parse_timeframe(to_timeframe)

    if to_delta < from_delta:
        raise ValueError(
            f"cannot resample {from_timeframe} → {to_timeframe}: target "
            "timeframe must be coarser than source"
        )
    if to_delta == from_delta:
        # Identity resample — return a copy to keep the contract
        # consistent with the multi-bar case.
        return list(candles)

    # Integer ratio guard. ``timedelta`` comparison handles the
    # second-level resolution exactly.
    ratio_seconds = to_delta.total_seconds()
    src_seconds = from_delta.total_seconds()
    if ratio_seconds % src_seconds != 0:
        raise ValueError(
            f"cannot resample {from_timeframe} → {to_timeframe}: target "
            f"is not an integer multiple of source "
            f"({ratio_seconds}s / {src_seconds}s)"
        )

    bars_per_bucket = int(ratio_seconds // src_seconds)
    out: list[Candle] = []
    bucket: list[Candle] = []
    bucket_start: datetime | None = None

    for c in candles:
        # Align bucket boundary to UNIX epoch — same as Binance / ccxt:
        # ``ts.timestamp() % to_delta.total_seconds() == 0`` for a
        # bucket-start candle. This makes the resample independent of
        # the input series's starting candle, which matters when two
        # sub-runs need to agree on bucket alignment.
        bucket_aligned_ts = _floor_to_bucket(c.ts, to_delta)
        if bucket_start is None:
            bucket_start = bucket_aligned_ts
        if bucket_aligned_ts != bucket_start:
            # New bucket starts here; flush the previous if it's full.
            if len(bucket) == bars_per_bucket:
                out.append(_aggregate_bucket(bucket, to_timeframe))
            # ELSE: partial bucket — drop it (see docstring).
            bucket = []
            bucket_start = bucket_aligned_ts
        bucket.append(c)

    # Final bucket flush — only emit if complete.
    if len(bucket) == bars_per_bucket:
        out.append(_aggregate_bucket(bucket, to_timeframe))

    return out


def _floor_to_bucket(ts: datetime, bucket_size: timedelta) -> datetime:
    """Round ``ts`` DOWN to the nearest bucket-aligned timestamp.

    Uses the UNIX epoch as the alignment origin so that all candles
    bucket the same way regardless of where the input series starts.
    """
    epoch = ts.replace(year=1970, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    # datetime arithmetic preserves tzinfo if the source is aware —
    # ``ts.replace(year=...)`` keeps the tz, so the subtraction below
    # is tz-consistent.
    delta = ts - epoch
    floored_seconds = (delta.total_seconds() // bucket_size.total_seconds()) * (
        bucket_size.total_seconds()
    )
    return epoch + timedelta(seconds=floored_seconds)


def _aggregate_bucket(bucket: list[Candle], to_timeframe: str) -> Candle:
    """Collapse N input candles into one output candle.

    Precondition: ``bucket`` is non-empty and all candles share the
    same symbol / exchange (caller's responsibility — resample is
    single-series).
    """
    first = bucket[0]
    last = bucket[-1]

    high = max(c.high for c in bucket)
    low = min(c.low for c in bucket)
    volume = sum((c.volume for c in bucket), Decimal(0))

    # quote_volume is optional. Sum only if EVERY input candle has it;
    # otherwise the aggregated value would be misleading (mixing
    # known-and-unknown).
    quote_volumes = [c.quote_volume for c in bucket if c.quote_volume is not None]
    qv: Decimal | None = (
        sum(quote_volumes, Decimal(0)) if len(quote_volumes) == len(bucket) else None
    )

    return Candle(
        exchange=first.exchange,
        symbol=first.symbol,
        timeframe=to_timeframe,
        ts=first.ts,
        open=first.open,
        high=high,
        low=low,
        close=last.close,
        volume=volume,
        quote_volume=qv,
    )
