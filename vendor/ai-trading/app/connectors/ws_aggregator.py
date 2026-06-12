"""WSAggregator — WebSocket reconnect + REST gap-fill wrapper.

Spec: docs/implementation/03-detailed-design/01-connector-ccxt.md §7.
US: US-AT-046 (WS reconnect), US-AT-047 (rate-limit handling).

Wraps any ``ExchangeAdapter.watch_ohlcv`` to provide:

* **Gap detection** — when a streamed candle's timestamp is more than
  ``2 * timeframe_delta`` past the last seen candle, treat it as a
  gap and call ``adapter.fetch_ohlcv(since=last_ts)`` to backfill the
  missing range before yielding the out-of-band candle.
* **De-duplication** — the REST backfill response often overlaps the
  last-seen timestamp; the aggregator skips any candle whose ``ts``
  is not strictly newer than the running watermark.
* **Exponential reconnect** — on ``ConnectionError`` /
  ``asyncio.TimeoutError``, sleep ``initial * 2^attempt`` seconds
  (clamped at ``max``) and re-subscribe. After
  ``max_reconnect_attempts`` consecutive failures, raise
  ``WSReconnectExhaustedError`` rather than spin forever.
* **Backoff reset** — any successfully streamed candle resets the
  attempt counter, so an 8h connection that drops once does not
  inherit a 60s sleep on its single retry.

State is per-instance and not shared. The ``sleep`` callable is
injectable (default :func:`asyncio.sleep`) so tests can verify the
backoff sequence without waiting wall-clock seconds.

Counters are exposed via the :class:`WSAggregatorMetrics` dataclass
attached to ``aggregator.metrics``; the design doc §11 envisions
mapping these to Prometheus gauges in a follow-up integration.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.connectors.protocol import ExchangeAdapter
    from app.domain.market_data import Candle


# ── Public exception types ────────────────────────────────────────


class WSReconnectExhaustedError(Exception):
    """Raised when consecutive WS reconnects exceed ``max_reconnect_attempts``.

    The caller (typically the strategy runtime) should treat this as a
    fatal connection condition and decide whether to halt the strategy
    or re-instantiate the aggregator with a fresh underlying connector
    (e.g. swapping in a different :class:`KeyPool` credential).
    """


# ── Timeframe parsing ─────────────────────────────────────────────

# Whole-number quantity + single-letter unit. ``ms`` / ``us`` are
# explicitly excluded — sub-second timeframes are not part of the v1.0
# scope and would change the retry-budget math (a "gap" should always
# represent a meaningful chunk of missed market data).
_UNITS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}
_TIMEFRAME_RE = re.compile(r"^([1-9]\d*)([smhd])$")


def parse_timeframe(spec: str) -> timedelta:
    """Convert a Binance/ccxt-style timeframe string to a ``timedelta``.

    Args:
        spec: ``"1m"``, ``"5m"``, ``"15m"``, ``"1h"``, ``"4h"``, ``"1d"``...

    Raises:
        ValueError: when ``spec`` does not match ``<positive int><unit>``
        or when the unit is not in ``{s, m, h, d}``.
    """
    match = _TIMEFRAME_RE.fullmatch(spec)
    if not match:
        raise ValueError(f"invalid timeframe spec: {spec!r}")
    value, unit = match.groups()
    return timedelta(seconds=int(value) * _UNITS[unit])


# ── Metrics struct ────────────────────────────────────────────────


@dataclass
class WSAggregatorMetrics:
    """Plain counter struct exposed for instrumentation.

    Exposed under ``aggregator.metrics`` so call sites can read
    snapshots and forward to Prometheus / structlog. We do not hold
    a Prometheus client here to keep this module dependency-free.
    """

    candles_emitted: int = 0
    gaps_detected: int = 0
    gaps_filled: int = 0
    reconnects: int = 0


# ── Aggregator ────────────────────────────────────────────────────


SleepFn = Callable[[float], Awaitable[None]]


@dataclass
class WSAggregator:
    """WebSocket wrapper that auto-recovers from gaps and disconnects.

    Args:
        adapter: any object satisfying ``ExchangeAdapter`` —
            production adapters or test fakes both work.
        sleep: awaitable invoked between reconnect attempts; default
            ``asyncio.sleep``. Tests inject a recorder to verify the
            backoff sequence without real waits.
        backoff_initial_seconds: first reconnect delay.
        backoff_max_seconds: cap so we don't sleep an hour after a
            long string of failures.
        max_reconnect_attempts: after this many *consecutive* failed
            reconnects, raise :class:`WSReconnectExhaustedError`.
            Successful candle yields reset the counter to 0.
        backfill_limit: ``limit`` argument forwarded to
            ``adapter.fetch_ohlcv`` when filling a gap.
    """

    adapter: ExchangeAdapter
    sleep: SleepFn = field(default=asyncio.sleep)
    backoff_initial_seconds: float = 1.0
    backoff_max_seconds: float = 60.0
    max_reconnect_attempts: int = 10
    backfill_limit: int = 200
    metrics: WSAggregatorMetrics = field(default_factory=WSAggregatorMetrics)

    async def watch(
        self, symbol: str, timeframe: str,
    ) -> AsyncIterator[Candle]:
        """Yield candles forever, healing gaps and reconnecting as needed.

        The async generator terminates only via:
          * caller breaking out (cancellation),
          * :class:`WSReconnectExhaustedError` after exhausting
            consecutive reconnect attempts.

        Consumer responsibility — to release the inner WS / HTTP
        session promptly, wrap the iterator in ``contextlib.aclosing``::

            async with aclosing(aggregator.watch(symbol, tf)) as s:
                async for candle in s:
                    ...

        Without ``aclosing`` Python only finalises the inner
        generators at GC time, which can leave sockets open for
        seconds in a busy event loop.

        State machine per outer-loop iteration:
          * ``yielded_anything`` — did the inner ``async for`` stream
            produce at least one candle?
          * ``had_error`` — did the inner stream raise a transient
            connection error (vs. ending cleanly)?
          * ``attempt`` — consecutive failed reconnects without
            *any* successful candle in between. Reset on success.
        """
        tf_delta = parse_timeframe(timeframe)
        gap_threshold = tf_delta * 2  # 2x rule per design doc
        last_ts = None
        attempt = 0

        while True:
            yielded_anything = False
            had_error = False
            # ``watch_ohlcv`` is an async generator; the Protocol's
            # ``async def`` signature confuses mypy into thinking we
            # need to await the call. The runtime returns the iterator
            # synchronously — see ADR-0005 / connector spec §6. Suppress
            # narrowly; a follow-up pass tightens the Protocol to use
            # ``def -> AsyncIterator``.
            stream = self.adapter.watch_ohlcv(symbol, timeframe)
            try:
                async for candle in stream:  # type: ignore[attr-defined]
                    if last_ts is not None and candle.ts > last_ts + gap_threshold:
                        self.metrics.gaps_detected += 1
                        backfill = await self.adapter.fetch_ohlcv(
                            symbol, timeframe,
                            since=last_ts,
                            limit=self.backfill_limit,
                        )
                        for filled in backfill:
                            if filled.ts > last_ts:
                                last_ts = filled.ts
                                self.metrics.candles_emitted += 1
                                self.metrics.gaps_filled += 1
                                yielded_anything = True
                                yield filled
                    if last_ts is None or candle.ts > last_ts:
                        last_ts = candle.ts
                        self.metrics.candles_emitted += 1
                        yielded_anything = True
                        yield candle
            except (TimeoutError, ConnectionError):
                had_error = True
            finally:
                # Promptly close the inner async generator so its
                # underlying socket / HTTP session is released even if
                # the consumer breaks mid-iteration. CPython's GC would
                # call ``aclose()`` eventually, but production-grade
                # connectors (ccxt.pro WS) hold real resources.
                aclose = getattr(stream, "aclose", None)
                if aclose is not None:
                    await aclose()

            if yielded_anything:
                attempt = 0

            # A clean stream-end after successful reads is a normal
            # re-subscribe — the WS server didn't fail, the test
            # script just exhausted. Loop back without a backoff
            # sleep so we don't accumulate phantom reconnects.
            if not had_error and yielded_anything:
                continue

            if attempt >= self.max_reconnect_attempts:
                raise WSReconnectExhaustedError(
                    f"giving up after {attempt} consecutive "
                    f"reconnects on {symbol} {timeframe}"
                )

            delay = min(
                self.backoff_initial_seconds * (2 ** attempt),
                self.backoff_max_seconds,
            )
            self.metrics.reconnects += 1
            await self.sleep(delay)
            attempt += 1


__all__ = [
    "WSAggregator",
    "WSAggregatorMetrics",
    "WSReconnectExhaustedError",
    "parse_timeframe",
]
