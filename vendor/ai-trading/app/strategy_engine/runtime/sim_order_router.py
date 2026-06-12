"""Simulated order router — paper trading for dry-run mode.

Same slippage / fee model semantics as the backtest engine, so a
dry-run that uses ``SimOrderRouter`` produces fills directly comparable
to a backtest run on the same data. **This is the dry-run truth
contract**: paper-mode PNL must match backtest PNL up to noise from
real-time tick arrival differences (the backtest sees one
synchronous candle stream; dry-run sees the same bars but routed
through async dispatch).

What this router does:

  * MARKET orders → fill at slipped close immediately, same as
    backtest engine's ``_fill_at_price``
  * LIMIT IOC/FOK → fill at limit price if candle's range crosses,
    else reject; never queued (same as backtest)
  * LIMIT GTC / STOP — explicitly REJECTED in this simple v1
    simulated router. Reason: the simulated pending-order book lives
    in the backtest engine, not here; integrating it cleanly into
    the live runtime is a separate concern (S7-2).

When the live runtime adds GTC LIMIT / STOP support, the strategy
runtime will manage the pending-order book directly (mirroring real
venues, which hold the resting order at the exchange), and the
SimOrderRouter will fill against THAT pending book.

For v1 dry-run with MARKET-only or IOC LIMIT strategies (the textbook
SKILL.md examples), this is sufficient.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.connectors.protocol import OrderIntent, OrderSide, OrderType, TimeInForce
from app.domain.market_data import Candle
from app.strategy_engine.backtest.models import (
    ConstantBpsFee,
    ConstantBpsSlippage,
    FeeModel,
    SlippageModel,
)
from app.strategy_engine.runtime.protocol import FillReport, OrderRouter


class SimOrderRouter(OrderRouter):
    """Same fill semantics as the backtest engine's MARKET / IOC LIMIT
    paths. GTC LIMIT / STOP not supported in v1 — see module docstring.

    Stateless w.r.t. the runtime — fee and slippage models are
    constructed once and reused across all submissions. To customise
    (e.g. tighter fees on a high-volume strategy), pass alternative
    instances at construction.
    """

    def __init__(
        self,
        *,
        fee_model: FeeModel | None = None,
        slippage_model: SlippageModel | None = None,
    ) -> None:
        self._fee_model = fee_model or ConstantBpsFee()
        self._slippage_model = slippage_model or ConstantBpsSlippage()

    async def submit(
        self, intent: OrderIntent, *, candle: Candle
    ) -> FillReport:
        """Try to fill ``intent`` against the given ``candle``.

        Branch by type:

          * MARKET → fill at slipped close, record fee
          * LIMIT IOC/FOK → fill at limit price IFF candle crosses
          * LIMIT GTC → REJECT (would need pending-order book)
          * STOP / STOP_LIMIT → REJECT (same reason)
        """
        ts = candle.ts

        if intent.type == OrderType.MARKET:
            fill_price = self._slippage_model.fill_price(intent, candle)
            return self._build_fill(intent, candle, fill_price, ts)

        if intent.type == OrderType.LIMIT and intent.time_in_force in {
            TimeInForce.IOC,
            TimeInForce.FOK,
        }:
            if intent.price is not None and _limit_crossable(intent, candle):
                return self._build_fill(intent, candle, intent.price, ts)
            return FillReport(
                intent=intent,
                state="cancelled",
                submitted_at=ts,
                error="IOC/FOK limit did not cross same-bar range",
            )

        # GTC LIMIT, STOP, STOP_LIMIT — not supported in this router.
        # When the runtime grows its own pending-order book (S7-2),
        # those orders will be held there and re-attempted on each
        # subsequent candle, then routed back through this router for
        # the actual fill.
        return FillReport(
            intent=intent,
            state="rejected",
            submitted_at=ts,
            error=(
                f"SimOrderRouter v1 does not support "
                f"{intent.type.value}/{intent.time_in_force.value}; "
                f"only MARKET and LIMIT IOC/FOK are implemented"
            ),
        )

    def _build_fill(
        self,
        intent: OrderIntent,
        candle: Candle,
        fill_price: Decimal,
        ts: datetime,
    ) -> FillReport:
        """Construct a ``filled`` FillReport with fee computed via the
        fee model. ``fee_currency`` defaults to the quote asset
        (parse from ``symbol`` — same convention as the backtest
        engine's Trade record). Real adapters override this with
        venue-reported fee currency."""
        fee = self._fee_model.calc(intent, fill_price)
        return FillReport(
            intent=intent,
            state="filled",
            fill_price=fill_price,
            fill_qty=intent.qty,
            fee=fee,
            fee_currency=_quote_currency(intent.symbol),
            submitted_at=ts,
            filled_at=ts,
        )


# ── Local helpers (duplicated from engine for now) ───────────────


def _limit_crossable(intent: OrderIntent, candle: Candle) -> bool:
    """A LIMIT BUY fills if the candle's low <= limit price.
    A LIMIT SELL fills if the candle's high >= limit price.

    Duplicated from ``BacktestEngine._limit_crossable``. When the
    pending-order book moves into the runtime (S7-2), this helper
    moves with it and the duplication ends.
    """
    if intent.price is None:
        return False
    if intent.side == OrderSide.BUY:
        return bool(candle.low <= intent.price)
    return bool(candle.high >= intent.price)


def _quote_currency(symbol: str) -> str:
    """Parse ``BASE/QUOTE`` → ``QUOTE``. ccxt-style symbols. When
    the symbol doesn't carry a slash (rare), default to ``"USDT"`` —
    the common case for crypto and consistent with the backtest
    engine's implicit assumption."""
    if "/" in symbol:
        return symbol.split("/", 1)[1]
    return "USDT"
