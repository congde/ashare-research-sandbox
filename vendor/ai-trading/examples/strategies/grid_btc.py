"""Example strategy — BTC grid 18000-25000.

Mirrors the strategy card in docs/implementation/03-detailed-design/08-frontend.md
and `frontend-design-demo.html`. Pure restricted DSL — passes
`validate_strategy_code()` and runs in both backtest and live runtime.
"""

from __future__ import annotations

from decimal import Decimal

from ai_trading.api import fetch_ohlcv, log, order_intent, position

GRID_LOW = Decimal("18000")
GRID_HIGH = Decimal("25000")
GRID_COUNT = 20


def on_tick(ctx, candle):  # noqa: ANN001 — DSL contract
    """Called every candle. Returns an OrderIntent or None."""
    grids = [
        GRID_LOW + (GRID_HIGH - GRID_LOW) * Decimal(i) / Decimal(GRID_COUNT)
        for i in range(GRID_COUNT + 1)
    ]
    pos = position(ctx.symbol)
    price = candle.close

    # Find the active grid bucket.
    for i in range(len(grids) - 1):
        if grids[i] <= price < grids[i + 1]:
            target_qty = Decimal("0.01") * Decimal(GRID_COUNT - i)
            delta = target_qty - pos.qty

            if delta > Decimal("0.0001"):
                log(f"grid buy at {price} for level {i}")
                return order_intent(
                    side="buy", qty=delta, type="limit", price=grids[i]
                )

            if delta < Decimal("-0.0001"):
                log(f"grid sell at {price} for level {i}")
                return order_intent(
                    side="sell", qty=-delta, type="limit", price=grids[i + 1]
                )

    return None
