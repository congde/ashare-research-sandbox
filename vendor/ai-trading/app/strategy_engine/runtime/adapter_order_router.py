"""Real-exchange OrderRouter — wraps an ExchangeAdapter.

Sprint-S7-2 deliverable. Translates the runtime's universal
``OrderIntent`` → ``FillReport`` contract into the platform's
``ExchangeAdapter.create_order(intent) -> Order`` call.

Why a separate router class (not call the adapter directly):

  * The runtime speaks ``FillReport`` (its own dataclass with simple
    fill-only fields). The adapter speaks ``Order`` (a richer state
    machine that the strategy doesn't need). The router is the
    translation boundary.

  * Error normalisation lives here. The adapter raises a narrow
    ``AdapterError`` taxonomy; the router converts each kind into a
    structured FillReport with state="rejected" so the runtime keeps
    running for the next candle.

  * Polling for fills is a router concern. ``adapter.create_order``
    typically returns state="submitted" — for v1.0 we do **NOT**
    poll: a submitted MARKET order is treated as filled, with the
    Order's reported ``fill_price`` / ``fill_qty`` / ``fee`` shipping
    straight into the FillReport. LIMIT orders explicitly aren't
    supported in v1 (parked to S7-3) because async polling for fill
    state needs the order-state-machine wiring that doesn't exist yet.

Why no retries here:

  * The adapter already wraps ``_call_ccxt`` with the project's
    ``CircuitBreaker`` + ``retry_with_backoff`` (see
    ``app.connectors.binance`` ``_call_ccxt``). Layering another retry
    here would multiply attempts and burn rate-limit budget.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.connectors.protocol import (
    AdapterError,
    ExchangeAdapter,
    ExchangeRejectError,
    ExchangeUnavailableError,
    OrderIntent,
    OrderType,
    RateLimitError,
)
from app.domain.market_data import Candle
from app.strategy_engine.runtime.protocol import FillReport, OrderRouter

logger = logging.getLogger("adapter_order_router")


class AdapterOrderRouter(OrderRouter):
    """Routes OrderIntents through an :class:`ExchangeAdapter`.

    v1.0 scope:

      * MARKET orders only. Submit → treat the adapter's response as
        the fill. The adapter's ``Order`` is expected to carry
        ``fill_price``, ``fill_qty``, ``fee`` for filled markets.
        When the adapter reports state="submitted" but missing
        fill metadata (testnet quirk), we surface the order as
        ``rejected`` with explanatory error rather than emitting a
        FillReport claiming a fill that didn't happen.

      * LIMIT (any TIF) → rejected at this layer with
        "v1: LIMIT not supported in live runtime". Strategies that
        need LIMIT must run in dry-run (``SimOrderRouter``) until
        S7-3 wires the order state machine + fill polling.

      * STOP / STOP_LIMIT → same as LIMIT (parked).

    Inject the adapter at construction. One router per (strategy,
    exchange) — concurrent submissions across symbols are fine
    because the adapter's ``KeyPool`` / ``RateLimiter`` middleware
    handles fan-out.
    """

    def __init__(self, adapter: ExchangeAdapter) -> None:
        self._adapter = adapter

    async def submit(
        self, intent: OrderIntent, *, candle: Candle
    ) -> FillReport:
        """Submit ``intent`` to the wrapped adapter.

        ``candle`` is part of the OrderRouter Protocol but ignored
        here — the real exchange decides the fill price from its own
        order book, not the candle the strategy was looking at.
        Kept in the signature so the same runtime code path works
        for sim and real routers.
        """
        ts_now = datetime.now(UTC)

        # Type gate. Surface "not supported" loud and clear instead
        # of letting the adapter return a confusing error.
        if intent.type != OrderType.MARKET:
            return FillReport(
                intent=intent,
                state="rejected",
                submitted_at=ts_now,
                error=(
                    f"AdapterOrderRouter v1 supports MARKET orders only; "
                    f"got {intent.type.value} (use SimOrderRouter in dry-run "
                    "for LIMIT / STOP semantics)"
                ),
            )

        try:
            order = await self._adapter.create_order(intent)
        except RateLimitError as exc:
            logger.warning("Adapter rate-limited; rejecting fill: %s", exc)
            return FillReport(
                intent=intent,
                state="rejected",
                submitted_at=ts_now,
                error=f"rate_limit: {exc}",
            )
        except ExchangeRejectError as exc:
            # Venue rejected the order — typically invalid params,
            # insufficient balance, symbol halted. Surface as a
            # rejected FillReport so the strategy can recover.
            logger.info("Exchange rejected order: %s", exc)
            return FillReport(
                intent=intent,
                state="rejected",
                submitted_at=ts_now,
                error=f"exchange_reject: {exc}",
            )
        except ExchangeUnavailableError as exc:
            # 5xx / network / circuit breaker open. Strategy might
            # retry next bar — same wire shape as the other reject
            # paths to keep handling uniform.
            logger.warning("Exchange unavailable: %s", exc)
            return FillReport(
                intent=intent,
                state="rejected",
                submitted_at=ts_now,
                error=f"exchange_unavailable: {exc}",
            )
        except AdapterError as exc:
            # Catch-all for adapter-taxonomy errors not enumerated
            # above. ``except AdapterError`` is intentional: lets ccxt
            # exceptions that leaked past ``_raise_mapped_error``
            # bubble (we WANT to see those in audit logs as bugs).
            logger.exception("Adapter error during submit")
            return FillReport(
                intent=intent,
                state="rejected",
                submitted_at=ts_now,
                error=f"adapter_error: {type(exc).__name__}: {exc}",
            )

        return _order_to_fill(order, intent, ts_now)


# ── Order → FillReport mapping ───────────────────────────────────


# Adapter Order.state values that count as "the order is done and
# carries a definitive fill price". For testnet MARKET orders the
# adapter typically reports ``"filled"`` (Binance) or
# ``"submitted"`` with completed fill metadata (some testnets).
_FILLED_STATES = frozenset({"filled", "partial"})


def _order_to_fill(
    order: object, intent: OrderIntent, submit_ts: datetime
) -> FillReport:
    """Map adapter :class:`Order` → runtime :class:`FillReport`.

    Defensive against partial adapters that may not populate every
    field. The contract this enforces:

      * state="filled" requires fill_price + fill_qty
      * state="submitted" with no fill metadata → rejected with
        explanation (the runtime would otherwise carry an unfillable
        intent forward without knowing it)

    Takes ``order`` as ``object`` so we can defensively read attrs
    without coupling to the exact Order dataclass — keeps the test
    fakes light.
    """
    state = getattr(order, "state", "submitted")
    fill_price = getattr(order, "fill_price", None)
    fill_qty = getattr(order, "fill_qty", None)
    fee = getattr(order, "fee", None)
    fee_currency = getattr(order, "fee_currency", None)
    submitted_at = getattr(order, "submitted_at", None) or submit_ts
    filled_at = getattr(order, "filled_at", None)

    if state in _FILLED_STATES and fill_price is not None and fill_qty and fill_qty > 0:
        return FillReport(
            intent=intent,
            state="filled",
            fill_price=fill_price,
            fill_qty=fill_qty,
            fee=fee,
            fee_currency=fee_currency,
            submitted_at=submitted_at,
            filled_at=filled_at,
        )

    if state == "cancelled":
        return FillReport(
            intent=intent,
            state="cancelled",
            submitted_at=submitted_at,
            error="exchange reported cancelled",
        )

    # Any other state — "submitted" with no fill metadata, "rejected",
    # something unrecognised — surface as rejected so the runtime
    # doesn't claim a fill that didn't happen. Real venues should fill
    # MARKET orders within the same response; if not, this branch
    # fires and the strategy author sees a clear signal.
    return FillReport(
        intent=intent,
        state="rejected",
        submitted_at=submitted_at,
        error=(
            f"adapter returned state={state!r} without fill metadata "
            f"(fill_price={fill_price}, fill_qty={fill_qty}); "
            "MARKET orders are expected to fill same-response in v1"
        ),
    )
