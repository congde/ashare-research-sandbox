"""Unit tests for :class:`WSCandleSource` — the WSAggregator → CandleSource
adapter. Decoupled from the real WSAggregator via a fake (the aggregator has
its own reconnect/gap-fill tests).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.domain.market_data import Candle
from app.strategy_engine.runtime.ws_candle_source import WSCandleSource


def _candle(i: int, close: float = 100.0) -> Candle:
    return Candle(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        ts=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=i),
        open=Decimal(str(close)),
        high=Decimal(str(close)),
        low=Decimal(str(close)),
        close=Decimal(str(close)),
        volume=Decimal("1"),
    )


class _FakeAggregator:
    """Stands in for WSAggregator.watch — yields a finite list (a real WS
    stream is infinite, but a finite fake lets us assert termination)."""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    async def watch(self, symbol: str, timeframe: str):
        for c in self._candles:
            yield c


class _FakeAdapter:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


async def _drain(src: WSCandleSource) -> list[Candle]:
    out: list[Candle] = []
    async for c in src.stream(symbol="BTC/USDT", timeframe="1m"):
        out.append(c)
    return out


async def test_warmup_then_live_stream_and_closes_adapter() -> None:
    warmup = [_candle(0), _candle(1)]
    live = [_candle(2), _candle(3)]
    adapter = _FakeAdapter()
    src = WSCandleSource(aggregator=_FakeAggregator(live), adapter=adapter, warmup_candles=warmup)
    out = await _drain(src)
    assert [c.ts for c in out] == [c.ts for c in (*warmup, *live)]
    assert adapter.closed  # adapter released after stream end


async def test_dedup_warmup_live_boundary() -> None:
    warmup = [_candle(0), _candle(1)]
    live = [_candle(1), _candle(2)]  # first live bar repeats warmup tail
    adapter = _FakeAdapter()
    src = WSCandleSource(aggregator=_FakeAggregator(live), adapter=adapter, warmup_candles=warmup)
    out = await _drain(src)
    assert [c.ts for c in out] == [_candle(0).ts, _candle(1).ts, _candle(2).ts]


async def test_pure_live_no_warmup() -> None:
    adapter = _FakeAdapter()
    src = WSCandleSource(aggregator=_FakeAggregator([_candle(0), _candle(1)]), adapter=adapter)
    out = await _drain(src)
    assert len(out) == 2


async def test_adapter_closed_on_aclose_midstream() -> None:
    """Runtime aclose()s the generator on cancel — adapter must close."""
    adapter = _FakeAdapter()
    src = WSCandleSource(
        aggregator=_FakeAggregator([_candle(i) for i in range(10)]),
        adapter=adapter,
    )
    gen = src.stream(symbol="BTC/USDT", timeframe="1m")
    first = await gen.__anext__()
    assert first.ts == _candle(0).ts
    await gen.aclose()  # simulate runtime cancellation cleanup
    assert adapter.closed
