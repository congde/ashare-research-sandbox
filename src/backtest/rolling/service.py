"""Teaching backtest service — web3-trading rolling engine on fixed/offline candles."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from backtest.audit.cpcv import run_cpcv_audit
from backtest.audit.dsr import audit_sharpe
from backtest.audit.pbo import probability_of_backtest_overfitting
from backtest.audit.robustness import run_parameter_sensitivity
from backtest.cost_presets import PRESETS, cost_assumptions, infer_funding_rate_pct, resolve_cost_options
from backtest.runner import load_prices
from backtest.rolling.diagnostics import compute_trade_diagnostics
from backtest.rolling.engine import run_backtest
from backtest.rolling.hooks import build_risk_hook_manager
from backtest.rolling.metrics import compute_metrics
from backtest.rolling.models import BacktestConfig
from backtest.rolling.registry import get_strategy, list_strategies
from backtest.trials import get_ledger
from config.web3_trading import primary_market_symbol
from dashboard.fixtures import load_offline
from paths import DATA_DIR

TEACHING_SYMBOL = "WEB3-DEMO/USDT"
TEACHING_KLINE = "1day"
MIN_CONTEXT = 20


def list_backtest_strategies() -> list[dict[str, str]]:
    return list_strategies()


def list_cost_presets() -> list[dict[str, str]]:
    return [{"name": key, "label": value["label"]} for key, value in PRESETS.items()]


def _resolve_cost(
    *,
    preset: str | None = None,
    slippage_bps: float | None = None,
    dynamic_slippage: bool | None = None,
    funding_rate_pct: float | None = None,
    commission_pct: float | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inferred = infer_funding_rate_pct(meta)
    effective_funding = funding_rate_pct if funding_rate_pct is not None else inferred
    return resolve_cost_options(
        preset=preset,
        slippage_bps=slippage_bps,
        dynamic_slippage=dynamic_slippage,
        funding_rate_pct=effective_funding,
        commission_pct=commission_pct,
    )


def _build_config(
    *,
    stop_loss_pct: float,
    take_profit_pct: float,
    trailing_stop_pct: float = 0.0,
    max_hold_bars: int = 0,
    kline_type: str,
    cost: dict[str, Any],
    start_from: int = 0,
) -> BacktestConfig:
    return BacktestConfig(
        min_context=MIN_CONTEXT,
        stop_loss_pct=max(0.5, min(20.0, stop_loss_pct)),
        take_profit_pct=max(0.5, min(50.0, take_profit_pct)),
        trailing_stop_pct=max(0.0, min(20.0, trailing_stop_pct)),
        max_hold_bars=max(0, min(500, max_hold_bars)),
        commission_pct=float(cost.get("commission_pct", 0.1)),
        slippage_pct=float(cost.get("slippage_pct", 0.0)),
        dynamic_slippage=bool(cost.get("dynamic_slippage", False)),
        dynamic_slippage_factor=float(cost.get("dynamic_slippage_factor", 0.5)),
        funding_rate_pct=float(cost.get("funding_rate_pct", 0.0)),
        start_from=start_from,
        kline_type=kline_type,
    )


def _base_assumptions(cost: dict[str, Any]) -> list[str]:
    return [
        "Rolling-window engine adapted from vendor/web3-trading/src/backtest/.",
        "Uses fixed teaching sample or offline dashboard candles — no live orders.",
        *cost_assumptions(cost),
        "Historical sample performance cannot predict future returns.",
    ]


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


def load_candles(
    *,
    symbol: str | None = None,
    limit: int = 120,
    refresh: bool = False,
) -> tuple[str, str, list[dict[str, Any]], dict[str, Any]]:
    pair = (symbol or primary_market_symbol() or TEACHING_SYMBOL).strip().upper()
    if pair in {TEACHING_SYMBOL, "WEB3-DEMO-USDT"}:
        prices = load_prices(DATA_DIR / "prices.csv")
        candles = _prices_to_candles(prices)
        meta = {"source": "data/prices.csv", "refresh": refresh}
        return TEACHING_SYMBOL, TEACHING_KLINE, candles[:limit], meta

    cached = load_offline("market_candles")
    raw = cached.get("candles") or []
    if raw:
        candles = _normalize_fixture_candles(raw)
        kline_type = str(cached.get("type") or TEACHING_KLINE)
        meta = {"source": "data/dashboard/market_candles.json", "refresh": refresh}
        return pair, kline_type, candles[:limit], meta

    prices = load_prices(DATA_DIR / "prices.csv")
    meta = {"source": "data/prices.csv", "refresh": refresh, "fallback": True}
    return TEACHING_SYMBOL, TEACHING_KLINE, _prices_to_candles(prices)[:limit], meta


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
    refresh: bool = False,
    strategy_params: dict[str, Any] | None = None,
    cost_preset: str | None = "teaching",
    slippage_bps: float | None = None,
    dynamic_slippage: bool | None = None,
    funding_rate_pct: float | None = None,
    commission_pct: float | None = None,
) -> dict[str, Any]:
    pair, resolved_kline, candles, meta = load_candles(
        symbol=symbol,
        limit=max(60, min(1500, limit)),
        refresh=refresh,
    )
    if len(candles) < MIN_CONTEXT + 5:
        raise ValueError(
            f"K线数据不足: 需要至少 {MIN_CONTEXT + 5} 根, 当前 {len(candles)} 根"
        )

    strategy = get_strategy(strategy_name)
    params = dict(strategy.default_params())
    if strategy_params:
        params.update(strategy_params)
    overrides = strategy.backtest_config_overrides(params)
    effective_max_hold = int(overrides.get("max_hold_bars", max_hold_bars))
    cost = _resolve_cost(
        preset=cost_preset,
        slippage_bps=slippage_bps,
        dynamic_slippage=dynamic_slippage,
        funding_rate_pct=funding_rate_pct,
        commission_pct=commission_pct,
        meta=meta,
    )
    config = _build_config(
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct,
        max_hold_bars=effective_max_hold,
        kline_type=kline_type or resolved_kline,
        cost=cost,
    )

    hook_manager = None
    if params.get("enable_risk_hooks"):
        hook_manager = build_risk_hook_manager(
            max_consecutive_losses=int(params.get("max_consecutive_losses", 3)),
            enable_regime_filter=bool(params.get("enable_regime_filter", True)),
        )

    trades, equity_curve, candle_signals = run_backtest(
        candles, strategy, params, config, hook_manager
    )
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
    payload.update(
        compute_trade_diagnostics(
            trades=trades,
            candles=candles,
            total_return_pct=float(payload.get("total_return_pct", 0.0)),
            max_drawdown_pct=float(payload.get("max_drawdown_pct", 0.0)),
        )
    )
    payload["ok"] = True
    payload["engine"] = "web3-trading/rolling-window"
    payload["stop_loss_pct"] = config.stop_loss_pct
    payload["take_profit_pct"] = config.take_profit_pct
    payload["trailing_stop_pct"] = config.trailing_stop_pct
    payload["max_hold_bars"] = config.max_hold_bars
    payload["strategy_key"] = strategy.name
    payload["cost_preset"] = cost.get("preset", "teaching")
    payload["slippage_pct"] = config.slippage_pct
    payload["dynamic_slippage"] = config.dynamic_slippage
    payload["funding_rate_pct"] = config.funding_rate_pct
    payload["commission_pct"] = config.commission_pct
    payload["equity_curve"] = _thin_series(payload.get("equity_curve") or [])
    payload["candle_signals"] = _thin_series(payload.get("candle_signals") or [])
    payload["assumptions"] = _base_assumptions(cost)

    get_ledger().record(
        source="execute_backtest",
        strategy_key=strategy.name,
        sharpe_ratio=float(payload.get("sharpe_ratio", 0.0)),
        total_return_pct=float(payload.get("total_return_pct", 0.0)),
        params=params,
        total_trades=int(payload.get("total_trades", 0)),
    )
    return payload


COMPARE_STRATEGY_KEYS = (
    "ma_crossover",
    "boll_mean_reversion",
    "rsi_mean_reversion",
    "macd",
    "ml_temporal",
    "buy_and_hold",
)


def compare_strategies(
    *,
    symbol: str | None = None,
    limit: int = 120,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    cost_preset: str | None = "teaching",
    slippage_bps: float | None = None,
    dynamic_slippage: bool | None = None,
    funding_rate_pct: float | None = None,
) -> dict[str, Any]:
    """Run a fixed teaching set of strategies on the same candle window."""
    pair, kline_type, candles, _meta = load_candles(symbol=symbol, limit=max(60, min(1500, limit)))
    if len(candles) < MIN_CONTEXT + 5:
        raise ValueError(
            f"K线数据不足: 需要至少 {MIN_CONTEXT + 5} 根, 当前 {len(candles)} 根"
        )

    rows: list[dict[str, Any]] = []
    for key in COMPARE_STRATEGY_KEYS:
        payload = execute_backtest(
            strategy_name=key,
            symbol=symbol,
            kline_type=kline_type,
            limit=limit,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            cost_preset=cost_preset,
            slippage_bps=slippage_bps,
            dynamic_slippage=dynamic_slippage,
            funding_rate_pct=funding_rate_pct,
        )
        rows.append(
            {
                "strategy_key": key,
                "strategy": payload.get("strategy") or key,
                "total_return_pct": payload.get("total_return_pct", 0.0),
                "max_drawdown_pct": payload.get("max_drawdown_pct", 0.0),
                "sharpe_ratio": payload.get("sharpe_ratio", 0.0),
                "calmar_ratio": payload.get("calmar_ratio", 0.0),
                "win_rate": payload.get("win_rate", 0.0),
                "total_trades": payload.get("total_trades", 0),
            }
        )

    leader = max(rows, key=lambda item: item["total_return_pct"])
    laggard = min(rows, key=lambda item: item["total_return_pct"])

    return {
        "ok": True,
        "engine": "web3-trading/rolling-window",
        "symbol": pair,
        "kline_type": kline_type,
        "total_candles": len(candles),
        "strategies": rows,
        "leader": leader["strategy_key"],
        "laggard": laggard["strategy_key"],
        "assumptions": [
            "Multi-strategy comparison uses the same offline candle window.",
            "Includes Qbot-ported ma_crossover, boll_mean_reversion, macd_crossover, adx_macd_trend.",
            "Historical sample performance cannot predict future returns.",
        ],
    }


def compare_windows(
    *,
    strategy_name: str = "ma_crossover",
    num_windows: int = 3,
    symbol: str | None = None,
    limit: int = 120,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    cost_preset: str | None = "teaching",
    slippage_bps: float | None = None,
    dynamic_slippage: bool | None = None,
    funding_rate_pct: float | None = None,
) -> dict[str, Any]:
    """Split the sample into consecutive windows and rerun one strategy."""
    pair, kline_type, candles, meta = load_candles(symbol=symbol, limit=max(60, min(1500, limit)))
    if len(candles) < MIN_CONTEXT + 5:
        raise ValueError(
            f"K线数据不足: 需要至少 {MIN_CONTEXT + 5} 根, 当前 {len(candles)} 根"
        )

    windows_count = max(2, min(6, num_windows))
    chunk = max(MIN_CONTEXT + 5, len(candles) // windows_count)
    strategy = get_strategy(strategy_name)
    params = dict(strategy.default_params())
    cost = _resolve_cost(
        preset=cost_preset,
        slippage_bps=slippage_bps,
        dynamic_slippage=dynamic_slippage,
        funding_rate_pct=funding_rate_pct,
        meta=meta,
    )
    config = _build_config(
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        kline_type=kline_type,
        cost=cost,
    )

    window_rows: list[dict[str, Any]] = []
    for idx in range(windows_count):
        start = idx * chunk
        end = len(candles) if idx == windows_count - 1 else min(len(candles), (idx + 1) * chunk)
        slice_candles = candles[start:end]
        if len(slice_candles) < MIN_CONTEXT + 5:
            continue
        trades, equity_curve, _signals = run_backtest(slice_candles, strategy, params, config)
        metrics = compute_metrics(
            trades=trades,
            equity_curve=equity_curve,
            candles=slice_candles,
            symbol=pair,
            kline_type=kline_type,
            strategy_name=strategy.display_name,
        )
        window_rows.append(
            {
                "window": idx + 1,
                "start_idx": start,
                "end_idx": end - 1,
                "candles": len(slice_candles),
                "total_return_pct": metrics.total_return_pct,
                "max_drawdown_pct": metrics.max_drawdown_pct,
                "total_trades": metrics.total_trades,
            }
        )

    returns = [row["total_return_pct"] for row in window_rows]
    stable = (
        len(returns) >= 2
        and max(returns) - min(returns) <= max(5.0, abs(max(returns, key=abs)) * 0.5)
    )
    positive_windows = sum(1 for value in returns if value > 0)
    windows_payload = [
        {
            **row,
            "bars": row["candles"],
        }
        for row in window_rows
    ]

    return {
        "ok": True,
        "strategy_key": strategy_name,
        "strategy": strategy.display_name,
        "symbol": pair,
        "kline_type": kline_type,
        "num_windows": len(window_rows),
        "positive_windows": positive_windows,
        "windows": windows_payload,
        "stable": stable,
        "assumptions": [
            "Window split is chronological — not walk-forward optimization.",
            "Uses fixed teaching candles; no parameter re-fit per window.",
            "For train/validate param search use walk_forward_optimize service instead.",
        ],
    }


def run_walk_forward(
    *,
    strategy_name: str = "ma_crossover",
    num_windows: int = 3,
    symbol: str | None = None,
    limit: int = 120,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    cost_preset: str | None = "teaching",
    slippage_bps: float | None = None,
    dynamic_slippage: bool | None = None,
    funding_rate_pct: float | None = None,
) -> dict[str, Any]:
    """Walk-forward param search: fit on train, score on OOS per window."""
    from backtest.rolling.optimization.walk_forward import walk_forward_optimize

    pair, kline_type, candles, meta = load_candles(symbol=symbol, limit=max(80, min(1500, limit)))
    if len(candles) < MIN_CONTEXT + 30:
        raise ValueError(
            f"K线数据不足: walk-forward 需要至少 {MIN_CONTEXT + 30} 根, 当前 {len(candles)} 根"
        )

    strategy = get_strategy(strategy_name)
    cost = _resolve_cost(
        preset=cost_preset,
        slippage_bps=slippage_bps,
        dynamic_slippage=dynamic_slippage,
        funding_rate_pct=funding_rate_pct,
        meta=meta,
    )
    result = walk_forward_optimize(
        candles,
        strategy,
        num_windows=max(2, min(5, num_windows)),
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        commission_pct=float(cost.get("commission_pct", 0.1)),
        slippage_pct=float(cost.get("slippage_pct", 0.0)),
        dynamic_slippage=bool(cost.get("dynamic_slippage", False)),
        dynamic_slippage_factor=float(cost.get("dynamic_slippage_factor", 0.5)),
        funding_rate_pct=float(cost.get("funding_rate_pct", 0.0)),
        kline_type=kline_type,
        min_context=MIN_CONTEXT,
    )

    ledger = get_ledger()
    trial_summary = ledger.summary(strategy_key=strategy_name)
    num_trials = max(result.num_trials, trial_summary["num_trials"])
    dsr_payload = audit_sharpe(
        [],
        result.out_of_sample_sharpe,
        num_trials=num_trials,
        sharpe_variance=float(trial_summary.get("sharpe_variance", 1.0)),
        kline_type=kline_type,
    )

    is_oos_gap = round(result.in_sample_sharpe - result.out_of_sample_sharpe, 2)
    overfit_warning = is_oos_gap > 1.0 or not dsr_payload.get("is_significant", False)
    return {
        "ok": True,
        "strategy_key": strategy_name,
        "symbol": pair,
        "kline_type": kline_type,
        "source": meta.get("source"),
        "cost_preset": cost.get("preset", "teaching"),
        "best_params": result.best_params,
        "in_sample_sharpe": result.in_sample_sharpe,
        "out_of_sample_sharpe": result.out_of_sample_sharpe,
        "out_of_sample_return_pct": result.out_of_sample_return,
        "is_oos_sharpe_gap": is_oos_gap,
        "num_windows": result.num_windows,
        "num_trials": num_trials,
        "dsr": dsr_payload.get("dsr", 0.0),
        "psr": dsr_payload.get("psr", 0.0),
        "dsr_significant": bool(dsr_payload.get("is_significant", False)),
        "expected_max_sharpe": dsr_payload.get("expected_max_sharpe", 0.0),
        "windows": result.window_results,
        "overfit_warning": overfit_warning,
        "assumptions": [
            "Params chosen by max in-sample Sharpe per window; OOS uses start_from train_end.",
            "Grid search capped at 500 combos with early-stop on weak half-train Sharpe.",
            *cost_assumptions(cost),
            "DSR corrects OOS Sharpe for number of trials recorded in the ledger.",
        ],
    }


def get_trial_audit(*, strategy_key: str | None = None) -> dict[str, Any]:
    ledger = get_ledger()
    ledger.load_disk()
    summary = ledger.summary(strategy_key=strategy_key)
    return {"ok": True, **summary}


def run_robustness_audit(
    *,
    strategy_name: str = "ma_crossover",
    symbol: str | None = None,
    limit: int = 120,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    cost_preset: str | None = "teaching",
    slippage_bps: float | None = None,
    dynamic_slippage: bool | None = None,
    funding_rate_pct: float | None = None,
) -> dict[str, Any]:
    pair, kline_type, candles, meta = load_candles(symbol=symbol, limit=max(60, min(1500, limit)))
    if len(candles) < MIN_CONTEXT + 5:
        raise ValueError(
            f"K线数据不足: 需要至少 {MIN_CONTEXT + 5} 根, 当前 {len(candles)} 根"
        )
    strategy = get_strategy(strategy_name)
    cost = _resolve_cost(
        preset=cost_preset,
        slippage_bps=slippage_bps,
        dynamic_slippage=dynamic_slippage,
        funding_rate_pct=funding_rate_pct,
        meta=meta,
    )
    config = _build_config(
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        kline_type=kline_type,
        cost=cost,
    )
    sensitivity = run_parameter_sensitivity(candles, strategy, config=config)
    pbo = probability_of_backtest_overfitting(candles, strategy, config=config)
    return {
        "ok": True,
        "strategy_key": strategy_name,
        "strategy": strategy.display_name,
        "symbol": pair,
        "kline_type": kline_type,
        "cost_preset": cost.get("preset", "teaching"),
        "parameter_sensitivity": sensitivity,
        "pbo": pbo,
        "verdict": "pass" if sensitivity["stable"] and not pbo["overfit_risk"] else "warn",
        "assumptions": [
            "Parameter sensitivity perturbs numeric defaults by ±20%.",
            "PBO uses block CSCV with capped candidate grid.",
            *cost_assumptions(cost),
        ],
    }


def run_cpcv_service(
    *,
    strategy_name: str = "ma_crossover",
    symbol: str | None = None,
    limit: int = 120,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    cost_preset: str | None = "teaching",
    slippage_bps: float | None = None,
    dynamic_slippage: bool | None = None,
    funding_rate_pct: float | None = None,
) -> dict[str, Any]:
    pair, kline_type, candles, meta = load_candles(symbol=symbol, limit=max(80, min(1500, limit)))
    if len(candles) < MIN_CONTEXT + 30:
        raise ValueError(
            f"K线数据不足: CPCV 需要至少 {MIN_CONTEXT + 30} 根, 当前 {len(candles)} 根"
        )
    strategy = get_strategy(strategy_name)
    cost = _resolve_cost(
        preset=cost_preset,
        slippage_bps=slippage_bps,
        dynamic_slippage=dynamic_slippage,
        funding_rate_pct=funding_rate_pct,
        meta=meta,
    )
    config = _build_config(
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        kline_type=kline_type,
        cost=cost,
    )
    cpcv = run_cpcv_audit(candles, strategy, config=config)
    return {
        "ok": True,
        "strategy_key": strategy_name,
        "strategy": strategy.display_name,
        "symbol": pair,
        "kline_type": kline_type,
        "cost_preset": cost.get("preset", "teaching"),
        "cpcv": cpcv,
        "assumptions": [
            "Teaching-scale CPCV with embargo bars between OOS groups.",
            "Not a full purged label overlap removal — bar-level signals only.",
            *cost_assumptions(cost),
        ],
    }
