"""Teaching backtest service — web3-trading rolling engine on fixed/offline candles."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from backtest.runner import load_prices
from backtest.rolling.engine import run_backtest
from backtest.rolling.metrics import compute_metrics
from backtest.rolling.models import BacktestConfig
from backtest.rolling.registry import get_strategy, list_strategies
from config.web3_trading import primary_market_symbol
from dashboard.fixtures import load_offline
from paths import DATA_DIR

TEACHING_SYMBOL = "WEB3-DEMO/USDT"
TEACHING_KLINE = "1day"
MIN_CONTEXT = 20


def list_backtest_strategies() -> list[dict[str, str]]:
    return list_strategies()


def _prices_to_candles(prices: list[Any]) -> list[dict[str, Any]]:
    candles: list[dict[str, Any]] = []
    for item in prices:
        close = float(item.close)
        ts = datetime.strptime(item.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        ts_sec = int(ts.timestamp())
        candles.append(
            {
                "tsSec": ts_sec,
                "date": item.date,
                "open": close,
                "close": close,
                "high": round(close * 1.002, 6),
                "low": round(close * 0.998, 6),
                "volume": 1.0,
                "turnover": close,
            }
        )
    return candles


def _normalize_fixture_candles(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candles: list[dict[str, Any]] = []
    for item in raw:
        close = float(item.get("close") or 0)
        if close <= 0:
            continue
        ts_sec = int(item.get("tsSec") or 0)
        if not ts_sec and item.get("date"):
            ts = datetime.strptime(str(item["date"]), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            ts_sec = int(ts.timestamp())
        candles.append(
            {
                "tsSec": ts_sec,
                "date": item.get("date") or datetime.fromtimestamp(ts_sec, tz=timezone.utc).strftime("%Y-%m-%d"),
                "open": float(item.get("open") or close),
                "close": close,
                "high": float(item.get("high") or close),
                "low": float(item.get("low") or close),
                "volume": float(item.get("volume") or 1.0),
                "turnover": float(item.get("turnover") or close),
            }
        )
    return sorted(candles, key=lambda row: row["tsSec"])


def load_candles(*, symbol: str | None = None, limit: int = 120) -> tuple[str, str, list[dict[str, Any]]]:
    pair = (symbol or primary_market_symbol() or TEACHING_SYMBOL).strip().upper()
    if pair in {TEACHING_SYMBOL, "WEB3-DEMO-USDT"}:
        prices = load_prices(DATA_DIR / "prices.csv")
        candles = _prices_to_candles(prices)
        return TEACHING_SYMBOL, TEACHING_KLINE, candles[:limit]

    cached = load_offline("market_candles")
    raw = cached.get("candles") or []
    if raw:
        candles = _normalize_fixture_candles(raw)
        kline_type = str(cached.get("type") or TEACHING_KLINE)
        return pair, kline_type, candles[:limit]

    prices = load_prices(DATA_DIR / "prices.csv")
    return TEACHING_SYMBOL, TEACHING_KLINE, _prices_to_candles(prices)[:limit]


def _thin_series(items: list[dict[str, Any]], max_points: int = 500) -> list[dict[str, Any]]:
    if len(items) <= max_points:
        return items
    step = max(1, len(items) // max_points)
    thinned = items[::step]
    if items[-1] not in thinned:
        thinned.append(items[-1])
    return thinned


def execute_backtest(
    *,
    strategy_name: str = "technical_signal",
    symbol: str | None = None,
    kline_type: str | None = None,
    limit: int = 120,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    trailing_stop_pct: float = 0.0,
    max_hold_bars: int = 0,
) -> dict[str, Any]:
    pair, resolved_kline, candles = load_candles(symbol=symbol, limit=max(60, min(1500, limit)))
    if len(candles) < MIN_CONTEXT + 5:
        raise ValueError(
            f"K线数据不足: 需要至少 {MIN_CONTEXT + 5} 根, 当前 {len(candles)} 根"
        )

    strategy = get_strategy(strategy_name)
    params = dict(strategy.default_params())
    config = BacktestConfig(
        min_context=MIN_CONTEXT,
        stop_loss_pct=max(0.5, min(20.0, stop_loss_pct)),
        take_profit_pct=max(0.5, min(50.0, take_profit_pct)),
        trailing_stop_pct=max(0.0, min(20.0, trailing_stop_pct)),
        max_hold_bars=max(0, min(500, max_hold_bars)),
        commission_pct=0.1,
        kline_type=kline_type or resolved_kline,
    )

    trades, equity_curve, candle_signals = run_backtest(candles, strategy, params, config)
    result = compute_metrics(
        trades=trades,
        equity_curve=equity_curve,
        candles=candles,
        symbol=pair,
        kline_type=config.kline_type,
        strategy_name=strategy.display_name,
    )
    result.candle_signals = candle_signals

    payload = asdict(result)
    payload["ok"] = True
    payload["engine"] = "web3-trading/rolling-window"
    payload["stop_loss_pct"] = config.stop_loss_pct
    payload["take_profit_pct"] = config.take_profit_pct
    payload["trailing_stop_pct"] = config.trailing_stop_pct
    payload["max_hold_bars"] = config.max_hold_bars
    payload["strategy_key"] = strategy.name
    payload["equity_curve"] = _thin_series(payload.get("equity_curve") or [])
    payload["candle_signals"] = _thin_series(payload.get("candle_signals") or [])
    payload["assumptions"] = [
        "Rolling-window engine adapted from vendor/web3-trading/src/backtest/.",
        "Uses fixed teaching sample or offline dashboard candles — no live orders.",
        "Default commission 0.1% per side; slippage disabled in teaching mode.",
        "Historical sample performance cannot predict future returns.",
    ]
    return payload
