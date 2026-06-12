"""Backtest service — trigger a historical simulation and persist it.

This is the **backtest-run vertical** behind the dashboard's "重新回测"
button. It mirrors the live-runtime endpoint's fidelity (PR #54 /
``strategies_runtime.py``):

  * Real candles pulled from the public, credential-less
    ``BinanceAdapter(testnet=True).fetch_ohlcv`` (same source the live
    runtime replays).
  * The real event-driven ``BacktestEngine`` (ADR-0009) computes real
    metrics — Sharpe / Sortino / PnL / max-drawdown.
  * A real ``Backtest`` row is persisted with the metrics + state.

What is intentionally stubbed (the SAME limitation the live-runtime
endpoint documents): the strategy *logic*. Loading user-authored
strategy code and compiling it into the ``on_tick`` callable needs the
sandbox compile path, which is a separate PR. Until then the run uses a
deterministic buy-and-hold *harness* strategy — a meaningful baseline
(it tracks the asset over the window) rather than fabricated numbers.

v1 runs **synchronously** inside the request. Backtests over a few
hundred candles are sub-second CPU work; the live-runtime start endpoint
already does a blocking ``fetch_ohlcv`` inline. The ``QUEUED`` /
``RUNNING`` states on :class:`BacktestState` exist for a future Celery
path; the sync path persists the terminal ``DONE`` / ``FAILED`` state.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Protocol, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.backtest.models import Backtest, BacktestState
from app.domain.market_data import Candle
from app.domain.strategy.models import Strategy, StrategyStatus, StrategyVersion
from app.strategy_engine.backtest.engine import BacktestEngine, StrategyContext
from app.strategy_engine.backtest.models import BacktestMetrics
from app.strategy_engine.dsl.loader import StrategyCompileError, compile_strategy

if TYPE_CHECKING:
    from app.connectors.protocol import OrderIntent
    from app.strategy_engine.backtest.engine import StrategyFn

logger = logging.getLogger("backtest_service")

# Defaults — kept conservative so a default request always succeeds.
DEFAULT_CANDLE_LIMIT = 500
MAX_CANDLE_LIMIT = 1000
MIN_CANDLES = 3  # strategy warm-up needs >= 3 history bars
DEFAULT_INITIAL_CAPITAL = Decimal("1000")

# Fee / slippage models persisted alongside the run for provenance.
# These mirror the engine's defaults (ConstantBpsFee / ConstantBpsSlippage).
_FEE_MODEL = {"type": "constant_bps", "maker_bps": 10.0, "taker_bps": 10.0}
_SLIPPAGE_MODEL = {"type": "constant_bps", "bps": 5.0}

# Well-known name for the per-user auto-provisioned harness strategy.
# Prefixed with ``__`` so a future strategies-list endpoint can filter
# it out of the user-facing library.
_HARNESS_STRATEGY_NAME = "__backtest_harness__"
_HARNESS_CODE = (
    "# Auto-provisioned backtest harness (buy-and-hold baseline).\n"
    "# Replaced by the user's compiled strategy once the sandbox\n"
    "# code-loading path lands (see strategies_runtime.py).\n"
    "def on_tick(ctx, candle):\n"
    "    if ctx.position().qty > 0 or len(ctx.history) < 3:\n"
    "        return None\n"
    "    return ctx.order_intent(side='buy', qty=0.0, type='market')\n"
)


class CandleFetcher(Protocol):
    """Minimal slice of ``ExchangeAdapter`` the service needs.

    Lets tests inject a fake (no network) while production passes a real
    ``BinanceAdapter``. ``close`` is optional — only awaited for adapters
    the service constructs itself.
    """

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = ...,
        limit: int = ...,
    ) -> list[Candle]: ...


class BacktestError(ValueError):
    """Bad request — invalid params or too-few candles. Maps to 422."""


class BacktestDataUnavailableError(RuntimeError):
    """Upstream candle fetch failed. Maps to 502."""


class BacktestNotFoundError(LookupError):
    """No backtest with that id for this user. Maps to 404."""


def make_harness_strategy(initial_capital: Decimal) -> StrategyFn:
    """Buy-and-hold harness: warm up 3 bars, buy ~half the book once, idle.

    Sized from ``initial_capital`` so the single MARKET buy is always
    affordable regardless of the asset's price. Captured in a closure so
    each run gets a fresh ``fired`` flag.
    """

    state = {"fired": False}
    half_capital = initial_capital * Decimal("0.5")

    def on_tick(ctx: StrategyContext, candle: Candle) -> OrderIntent | None:
        if state["fired"] or len(ctx.history) < MIN_CANDLES:
            return None
        close = Decimal(str(candle.close))
        if close <= 0:
            return None
        state["fired"] = True
        qty = half_capital / close
        return ctx.order_intent(side="buy", qty=qty, type="market")

    return on_tick


def _metrics_to_dict(metrics: BacktestMetrics) -> dict[str, object]:
    """JSON-safe projection of BacktestMetrics (Decimals → str)."""
    return {
        "total_trades": metrics.total_trades,
        "win_rate": metrics.win_rate,
        "pnl_pct": metrics.pnl_pct,
        "pnl_abs": str(metrics.pnl_abs),
        "sharpe": metrics.sharpe,
        "sortino": metrics.sortino,
        "max_drawdown_pct": metrics.max_drawdown_pct,
        "final_equity": str(metrics.final_equity),
    }


class BacktestService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_and_run(
        self,
        *,
        user_id: UUID,
        symbol: str,
        timeframe: str,
        strategy_version_id: UUID | None = None,
        initial_capital: str | None = None,
        limit: int = DEFAULT_CANDLE_LIMIT,
        adapter: CandleFetcher | None = None,
    ) -> Backtest:
        """Fetch candles, run the engine, and persist a Backtest row.

        Raises ``BacktestError`` for bad params, ``BacktestDataUnavailableError``
        if the candle fetch fails upstream.
        """
        capital = self._parse_capital(initial_capital)
        limit = max(MIN_CANDLES, min(int(limit), MAX_CANDLE_LIMIT))

        candles = await self._fetch_candles(symbol, timeframe, limit, adapter)
        if len(candles) < MIN_CANDLES:
            raise BacktestError(
                f"got {len(candles)} candles, need >= {MIN_CANDLES} for strategy warm-up"
            )

        if strategy_version_id is None:
            # No version selected (dashboard "重新回测" by symbol): fall back
            # to the buy-and-hold harness baseline.
            strategy_version_id = await self._resolve_harness_version(user_id)
            strategy_fn = make_harness_strategy(capital)
        else:
            # Compile the user's actual strategy code into the on_tick callable.
            code = await self._load_user_version_code(user_id, strategy_version_id)
            try:
                strategy_fn = compile_strategy(code)
            except StrategyCompileError as exc:
                raise BacktestError(
                    f"strategy version {strategy_version_id} failed to compile: {exc}"
                ) from exc

        state, metrics, trades_count, error_message = self._run_engine(
            candles, symbol, timeframe, capital, strategy_fn
        )

        backtest = Backtest(
            strategy_version_id=strategy_version_id,
            state=state,
            symbol=symbol,
            timeframe=timeframe,
            period_start=candles[0].ts,
            period_end=candles[-1].ts,
            initial_capital=str(capital),
            fee_model=dict(_FEE_MODEL),
            slippage_model=dict(_SLIPPAGE_MODEL),
            metrics=metrics,
            trades_count=trades_count,
            error_message=error_message,
        )
        self._session.add(backtest)
        await self._session.commit()
        await self._session.refresh(backtest)
        return backtest

    async def list_for_user(
        self, *, user_id: UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[Backtest], int]:
        """Most-recent-first backtests across the user's strategies."""
        base = (
            select(Backtest)
            .join(StrategyVersion, StrategyVersion.id == Backtest.strategy_version_id)
            .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
            .where(Strategy.user_id == user_id)
        )
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        result = await self._session.execute(
            base.order_by(Backtest.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)

    async def get_for_user(self, *, user_id: UUID, backtest_id: UUID) -> Backtest:
        result = await self._session.execute(
            select(Backtest)
            .join(StrategyVersion, StrategyVersion.id == Backtest.strategy_version_id)
            .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
            .where(Backtest.id == backtest_id, Strategy.user_id == user_id)
        )
        backtest = result.scalar_one_or_none()
        if backtest is None:
            raise BacktestNotFoundError(str(backtest_id))
        return backtest

    # ── Internals ────────────────────────────────────────────────

    @staticmethod
    def _parse_capital(initial_capital: str | None) -> Decimal:
        if initial_capital is None:
            return DEFAULT_INITIAL_CAPITAL
        try:
            capital = Decimal(initial_capital)
        except (InvalidOperation, TypeError) as exc:
            raise BacktestError(f"invalid initial_capital: {initial_capital!r}") from exc
        if capital <= 0:
            raise BacktestError("initial_capital must be positive")
        return capital

    async def _fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        adapter: CandleFetcher | None,
    ) -> list[Candle]:
        owned = adapter is None
        if adapter is None:
            # Imported lazily so the service module doesn't pull ccxt at
            # import time (keeps unit tests that inject a fake adapter light).
            from app.connectors.binance import BinanceAdapter

            adapter = BinanceAdapter(testnet=True)
        try:
            return await adapter.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception as exc:  # noqa: BLE001 — normalize to a narrow service error
            logger.warning("backtest candle fetch failed symbol=%s: %s", symbol, exc)
            raise BacktestDataUnavailableError(
                f"candle fetch failed: {type(exc).__name__}"
            ) from exc
        finally:
            if owned:
                close = getattr(adapter, "close", None)
                if close is not None:
                    await close()

    def _run_engine(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
        capital: Decimal,
        strategy_fn: StrategyFn,
    ) -> tuple[BacktestState, dict[str, object], int, str | None]:
        """Run the engine; never raises — a failure becomes a FAILED row."""
        try:
            engine = BacktestEngine(
                strategy_fn=strategy_fn,
                initial_capital=capital,
            )
            result = engine.run(candles, symbol, timeframe)
            return (
                BacktestState.DONE,
                _metrics_to_dict(result.metrics),
                result.metrics.total_trades,
                None,
            )
        except Exception as exc:  # noqa: BLE001 — persist as FAILED, don't 500
            logger.exception("backtest engine run failed symbol=%s", symbol)
            return BacktestState.FAILED, {}, 0, str(exc)[:2000]

    async def _load_user_version_code(self, user_id: UUID, version_id: UUID) -> str:
        """Load a strategy version's source, scoped to the owning user.

        The ``user_id`` join is the authorization boundary — a user can only
        backtest their own strategy versions. Missing / not-owned / empty
        code all raise ``BacktestError`` (422) rather than leaking a 404 that
        distinguishes "exists but not yours" from "doesn't exist".
        """
        code = await self._session.scalar(
            select(StrategyVersion.code)
            .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
            .where(StrategyVersion.id == version_id, Strategy.user_id == user_id)
        )
        if not code:
            raise BacktestError(f"strategy version {version_id} not found")
        return cast(str, code)

    async def _resolve_harness_version(self, user_id: UUID) -> UUID:
        """Find-or-create the per-user harness StrategyVersion.

        Satisfies the NOT NULL ``backtests.strategy_version_id`` FK without
        a schema migration. Idempotent: subsequent runs reuse the same row.
        """
        existing = await self._session.scalar(
            select(StrategyVersion.id)
            .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
            .where(
                Strategy.user_id == user_id,
                Strategy.name == _HARNESS_STRATEGY_NAME,
            )
            .limit(1)
        )
        if existing is not None:
            return cast(UUID, existing)

        strategy = Strategy(
            user_id=user_id,
            name=_HARNESS_STRATEGY_NAME,
            status=StrategyStatus.DRAFT,
        )
        self._session.add(strategy)
        await self._session.flush()
        version = StrategyVersion(
            strategy_id=strategy.id,
            version="0.1.0",
            code=_HARNESS_CODE,
            ast_hash=hashlib.sha256(_HARNESS_CODE.encode("utf-8")).hexdigest(),
            generation_meta={"harness": True},
        )
        self._session.add(version)
        await self._session.flush()
        return cast(UUID, version.id)
