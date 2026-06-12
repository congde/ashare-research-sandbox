# -*- coding: utf-8 -*-
"""
Pre-debate strategy backtest bundle for LLM signal / TradingAgents.

Fetches K-line once, runs every registered backtest strategy on the same candles,
and returns a compact summary for LLM context injection.
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import partial
from typing import Any, Dict, List, Optional

from backtest.engine import run_backtest
from backtest.metrics import compute_metrics
from backtest.models import BacktestConfig
from backtest.registry import get_strategy, list_strategies

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 300
_DEFAULT_KLINE = "1hour"
_MAX_RECENT_TRADES = 3


def _backtest_config_from_kwargs(kwargs: Dict[str, Any]) -> BacktestConfig:
    return BacktestConfig(
        min_context=60,
        stop_loss_pct=float(kwargs.get("stop_loss_pct", 3.0)),
        take_profit_pct=float(kwargs.get("take_profit_pct", 5.0)),
        trailing_stop_pct=float(kwargs.get("trailing_stop_pct", 0.0)),
        max_hold_bars=int(kwargs.get("max_hold_bars", 0)),
        kline_type=str(kwargs.get("kline_type", _DEFAULT_KLINE)),
    )


def _compact_strategy_result(
    strategy_name: str,
    display_name: str,
    result: Any,
) -> Dict[str, Any]:
    trades = list(getattr(result, "trades", None) or [])
    recent = trades[-_MAX_RECENT_TRADES:] if trades else []
    last_signal = None
    cs = list(getattr(result, "candle_signals", None) or [])
    if cs:
        last_signal = cs[-1]

    return {
        "name": strategy_name,
        "displayName": display_name,
        "ok": True,
        "totalCandles": result.total_candles,
        "totalTrades": result.total_trades,
        "winRate": result.win_rate,
        "totalReturnPct": result.total_return_pct,
        "maxDrawdownPct": result.max_drawdown_pct,
        "sharpeRatio": result.sharpe_ratio,
        "sortinoRatio": getattr(result, "sortino_ratio", 0.0),
        "profitFactor": getattr(result, "profit_factor", 0.0),
        "avgTradePct": getattr(result, "avg_trade_pct", 0.0),
        "bestTradePct": getattr(result, "best_trade_pct", 0.0),
        "worstTradePct": getattr(result, "worst_trade_pct", 0.0),
        "recentTrades": recent,
        "lastCandleSignal": last_signal,
    }


def _run_one_strategy_sync(
    candles: List[Dict[str, Any]],
    strategy_name: str,
    *,
    symbol: str,
    bt_config: BacktestConfig,
) -> Dict[str, Any]:
    strategy = get_strategy(strategy_name)
    display_name = strategy.display_name
    try:
        params = dict(strategy.default_params())
        trades, _equity, candle_signals = run_backtest(candles, strategy, params, bt_config)
        result = compute_metrics(
            trades=trades,
            equity_curve=[],
            candles=candles,
            symbol=symbol,
            kline_type=bt_config.kline_type,
            strategy_name=display_name,
        )
        result.candle_signals = candle_signals
        return _compact_strategy_result(strategy_name, display_name, result)
    except Exception as exc:
        logger.warning("signal backtest %s failed: %s", strategy_name, exc)
        return {
            "name": strategy_name,
            "displayName": display_name,
            "ok": False,
            "error": str(exc)[:200],
        }


async def _fetch_candles(
    pair: str,
    kline_type: str,
    limit: int,
) -> List[Dict[str, Any]]:
    from web.api.dashboard_service import kucoin_get, normalize_candle

    data = await kucoin_get(f"/api/v1/market/candles?symbol={pair}&type={kline_type}")
    raw = (data.get("data") or [])[:limit]
    candles = sorted(
        [c for c in (normalize_candle(r) for r in raw) if c],
        key=lambda x: x["tsSec"],
    )
    return candles


async def run_all_strategy_backtests(
    pair: str,
    *,
    kline_type: str = _DEFAULT_KLINE,
    limit: int = _DEFAULT_LIMIT,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    trailing_stop_pct: float = 0.0,
    max_hold_bars: int = 0,
) -> Dict[str, Any]:
    """
    Run every registered strategy on the same historical window.

    Returns a bundle dict suitable for ``aggregated["strategyBacktests"]``.
    """
    t0 = time.time()
    pair = (pair or "BTC-USDT").strip().upper()
    limit = max(60, min(1500, int(limit)))
    kline_type = kline_type or _DEFAULT_KLINE

    kwargs = {
        "kline_type": kline_type,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "trailing_stop_pct": trailing_stop_pct,
        "max_hold_bars": max_hold_bars,
    }
    bt_config = _backtest_config_from_kwargs(kwargs)

    try:
        candles = await _fetch_candles(pair, kline_type, limit)
    except Exception as exc:
        logger.warning("signal backtest candle fetch failed for %s: %s", pair, exc)
        return {
            "available": False,
            "symbol": pair,
            "klineType": kline_type,
            "limit": limit,
            "params": kwargs,
            "error": str(exc)[:300],
            "strategies": [],
            "latencyMs": int((time.time() - t0) * 1000),
        }

    if len(candles) < 60:
        return {
            "available": False,
            "symbol": pair,
            "klineType": kline_type,
            "limit": limit,
            "totalCandles": len(candles),
            "params": kwargs,
            "error": f"K线不足: 需要至少60根, 仅 {len(candles)} 根",
            "strategies": [],
            "latencyMs": int((time.time() - t0) * 1000),
        }

    names = [s["name"] for s in list_strategies()]
    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(
            None,
            partial(
                _run_one_strategy_sync,
                candles,
                name,
                symbol=pair,
                bt_config=bt_config,
            ),
        )
        for name in names
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    strategies: List[Dict[str, Any]] = []
    for name, item in zip(names, results):
        if isinstance(item, Exception):
            strategies.append({
                "name": name,
                "displayName": name,
                "ok": False,
                "error": str(item)[:200],
            })
        else:
            strategies.append(item)

    ok_count = sum(1 for s in strategies if s.get("ok"))
    latency_ms = int((time.time() - t0) * 1000)
    logger.info(
        "signal backtest bundle %s: %d/%d strategies ok in %dms (%s %d bars)",
        pair, ok_count, len(strategies), latency_ms, kline_type, len(candles),
    )

    return {
        "available": ok_count > 0,
        "symbol": pair,
        "klineType": kline_type,
        "limit": limit,
        "totalCandles": len(candles),
        "params": kwargs,
        "strategies": strategies,
        "successCount": ok_count,
        "totalCount": len(strategies),
        "latencyMs": latency_ms,
    }


def format_backtest_debate_context(bundle: Optional[Dict[str, Any]]) -> str:
    """Text block injected into TradingAgents ``fundamentals_report`` before debate."""
    return format_backtest_for_llm(bundle)


def format_backtest_for_llm(bundle: Optional[Dict[str, Any]]) -> str:
    """Compact markdown-ish text for LLM user message / TA pre-context."""
    if not bundle or not bundle.get("available"):
        err = (bundle or {}).get("error", "")
        return "暂无 (策略回测未执行或失败)" + (f" — {err}" if err else "")

    params = bundle.get("params") or {}
    lines = [
        f"交易对: {bundle.get('symbol', '?')}",
        f"K线: {bundle.get('klineType', '?')} × {bundle.get('totalCandles', 0)} 根 "
        f"(limit={bundle.get('limit', '?')})",
        f"风控参数: 止损 {params.get('stop_loss_pct', '?')}% / "
        f"止盈 {params.get('take_profit_pct', '?')}%",
        f"成功策略: {bundle.get('successCount', 0)}/{bundle.get('totalCount', 0)}",
        "说明: 以下为样本内历史回测，存在过拟合与前瞻偏差风险，不可当作未来收益保证。",
        "",
    ]

    ranked = sorted(
        [s for s in (bundle.get("strategies") or []) if s.get("ok")],
        key=lambda x: float(x.get("totalReturnPct") or 0),
        reverse=True,
    )
    failed = [s for s in (bundle.get("strategies") or []) if not s.get("ok")]

    for s in ranked:
        lines.append(
            f"【{s.get('displayName', s.get('name'))}】"
            f" 收益 {s.get('totalReturnPct', 0):+.2f}% | "
            f"胜率 {s.get('winRate', 0):.1f}% | "
            f"交易 {s.get('totalTrades', 0)} 笔 | "
            f"最大回撤 -{s.get('maxDrawdownPct', 0):.2f}% | "
            f"夏普 {s.get('sharpeRatio', 0):.2f}"
        )
        last_sig = s.get("lastCandleSignal")
        if isinstance(last_sig, dict) and last_sig.get("action"):
            lines.append(
                f"  最新K线信号: {last_sig.get('action')} score={last_sig.get('score', 0)}"
            )
        recent = s.get("recentTrades") or []
        if recent:
            t0 = recent[-1]
            lines.append(
                f"  最近平仓: {t0.get('direction', '?')} "
                f"盈亏 {t0.get('pnlPct', 0):+.2f}% ({t0.get('exitReason', '')})"
            )

    if failed:
        lines.append("")
        lines.append("未完成的策略:")
        for s in failed[:5]:
            lines.append(f"- {s.get('displayName', s.get('name'))}: {s.get('error', 'unknown')[:80]}")
        if len(failed) > 5:
            lines.append(f"- … 另有 {len(failed) - 5} 个失败")

    return "\n".join(lines)


def resolve_signal_backtest_options() -> Dict[str, Any]:
    """Read backtest injection knobs from web.config (with safe defaults)."""
    try:
        from web.config import config

        enabled = getattr(config, "llm_signal_backtest_enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() not in ("false", "0", "no", "off")
        return {
            "enabled": bool(enabled),
            "kline_type": str(
                getattr(config, "llm_signal_backtest_kline_type", None) or _DEFAULT_KLINE
            ),
            "limit": int(getattr(config, "llm_signal_backtest_limit", None) or _DEFAULT_LIMIT),
            "stop_loss_pct": float(
                getattr(config, "llm_signal_backtest_stop_loss", None) or 3.0
            ),
            "take_profit_pct": float(
                getattr(config, "llm_signal_backtest_take_profit", None) or 5.0
            ),
            "trailing_stop_pct": float(
                getattr(config, "llm_signal_backtest_trailing_stop", None) or 0.0
            ),
            "max_hold_bars": int(
                getattr(config, "llm_signal_backtest_max_hold_bars", None) or 0
            ),
        }
    except Exception:
        return {
            "enabled": True,
            "kline_type": _DEFAULT_KLINE,
            "limit": _DEFAULT_LIMIT,
            "stop_loss_pct": 3.0,
            "take_profit_pct": 5.0,
            "trailing_stop_pct": 0.0,
            "max_hold_bars": 0,
        }
