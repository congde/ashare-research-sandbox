"""WSCandleSource — adapt :class:`WSAggregator` into the runtime's
:class:`CandleSource` protocol.

``WSAggregator.watch()`` yields candles forever (positional args); the
runtime's ``CandleSource`` wants ``stream(*, symbol, timeframe)``. This thin
adapter bridges the two, with two extra jobs:

  * **Warm-up prefix.** Optionally yield a historical candle list first so a
    strategy's indicators (SMA, breakout lookback, ...) have enough
    ``ctx.history`` *before* the first live bar — otherwise a freshly
    subscribed live feed would starve the warm-up guard forever.

  * **Adapter lifecycle.** It owns the underlying ``ExchangeAdapter`` and
    closes it when the stream finalises (normal end, or ``aclose()`` when the
    runtime is cancelled on operator stop) so a stopped runner doesn't leak
    the WS / HTTP session.

v1 limitation (documented, not a bug): a multi-bar gap *between* the warm-up
tail and the first live bar is NOT backfilled — ``WSAggregator`` starts its
own gap watermark fresh. Subscription latency is normally < 1 bar, and the
warm-up↔live boundary duplicate is deduped here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.connectors.protocol import ExchangeAdapter
    from app.connectors.ws_aggregator import WSAggregator
    from app.domain.market_data import Candle


class WSCandleSource:
    """Live ``CandleSource``: optional warm-up prefix, then the
    ``WSAggregator`` real-time stream. Closes the owned adapter on finalise.
    """

    def __init__(
        self,
        *,
        aggregator: WSAggregator,
        adapter: ExchangeAdapter,
        warmup_candles: Sequence[Candle] = (),
    ) -> None:
        self._aggregator = aggregator
        self._adapter = adapter
        self._warmup = tuple(warmup_candles)

    async def stream(self, *, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        """Yield warm-up candles, then live candles. Closes the adapter in
        ``finally`` — runs on normal exhaustion and on ``aclose()`` (which the
        runtime calls when its task is cancelled on stop)."""
        last_ts = None
        try:
            for candle in self._warmup:
                last_ts = candle.ts
                yield candle
            async for candle in self._aggregator.watch(symbol, timeframe):
                # Dedup the warm-up↔live boundary: the first live bar can
                # repeat the warm-up tail's ts. Strictly-increasing ts is the
                # CandleSource contract.
                if last_ts is None or candle.ts > last_ts:
                    last_ts = candle.ts
                    yield candle
        finally:
            close = getattr(self._adapter, "close", None)
            if close is not None:
                await close()


__all__ = ["WSCandleSource"]
