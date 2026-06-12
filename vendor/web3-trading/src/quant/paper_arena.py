# -*- coding: utf-8 -*-
"""Dashboard 策略模拟实盘 Arena。

这里不是交易所撮合器，只做可控假设下的 paper trading：规则策略按最新已闭合
K 线生成信号，虚拟账户按固定滑点/手续费全额成交，结果和真实 live ledger 分开。
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from backtest.indicators import compute_all_indicators
from backtest.models import BacktestConfig, Trade
from backtest.registry import get_strategy, list_strategies
from backtest.risk.position import check_exit, close_position, update_peak_price


_TIMEFRAME_SECONDS = {
    "15min": 15 * 60,
    "1hour": 60 * 60,
    "4hour": 4 * 60 * 60,
    "1day": 24 * 60 * 60,
}
_PAPER_SESSION_DIR = Path("data/paper_arena")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except (TypeError, ValueError):
        return default


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "BTC-USDT").strip().upper().replace("/", "-")
    return normalized if "-" in normalized else f"{normalized}-USDT"


def _normalize_strategy_names(names: Iterable[str] | None) -> List[str]:
    known = {item["name"] for item in list_strategies()}
    result: List[str] = []
    for name in names or []:
        value = str(name).strip()
        if value in known and value not in result:
            result.append(value)
    return result or ["technical_signal", "ma_crossover", "rsi_mean_reversion", "macd", "buy_and_hold"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_path(session_id: str) -> Path:
    safe_id = "".join(ch for ch in str(session_id) if ch.isalnum() or ch in {"-", "_"})
    if not safe_id:
        raise ValueError("session_id 不能为空")
    return _PAPER_SESSION_DIR / f"{safe_id}.json"


def _load_session(session_id: str) -> Dict[str, Any]:
    import json

    path = _session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"模拟盘会话不存在: {session_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_session(session: Dict[str, Any]) -> None:
    import json

    _PAPER_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    path = _session_path(str(session.get("session_id") or ""))
    session["updated_at"] = _now_iso()
    path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")


def _closed_candles(candles: List[Dict[str, Any]], kline_type: str) -> List[Dict[str, Any]]:
    timeframe = _TIMEFRAME_SECONDS.get(kline_type, 60 * 60)
    now_ts = int(time.time())
    return [candle for candle in candles if int(candle.get("tsSec") or 0) + timeframe <= now_ts]


def _build_config(
    *,
    kline_type: str,
    stop_loss_pct: float,
    take_profit_pct: float,
    trailing_stop_pct: float,
    max_hold_bars: int,
    commission_pct: float,
    slippage_pct: float,
) -> BacktestConfig:
    return BacktestConfig(
        min_context=60,
        stop_loss_pct=max(0.1, float(stop_loss_pct or 3.0)),
        take_profit_pct=max(0.1, float(take_profit_pct or 5.0)),
        trailing_stop_pct=max(0.0, float(trailing_stop_pct or 0.0)),
        max_hold_bars=max(0, int(max_hold_bars or 0)),
        commission_pct=max(0.0, float(commission_pct or 0.0)),
        slippage_pct=max(0.0, float(slippage_pct or 0.0)),
        kline_type=kline_type,
    )


def _open_position_payload(position: Optional[Dict[str, Any]], mark_price: float) -> Optional[Dict[str, Any]]:
    if not position:
        return None
    entry_price = _num(position.get("entry_price"))
    notional = _num(position.get("notional_usd"))
    direction = str(position.get("direction") or "LONG")
    if entry_price <= 0 or mark_price <= 0:
        unrealized = 0.0
    elif direction == "LONG":
        unrealized = notional * (mark_price - entry_price) / entry_price
    else:
        unrealized = notional * (entry_price - mark_price) / entry_price
    return {
        "direction": direction,
        "entry_time": position.get("entry_time"),
        "entry_price": round(entry_price, 8),
        "notional_usd": round(notional, 8),
        "mark_price": round(mark_price, 8),
        "unrealized_usd": round(unrealized, 8),
    }


def _session_results(session: Dict[str, Any], mark_price: float) -> Dict[str, Any]:
    initial_cash = _num(session.get("initial_cash"), 10000.0)
    results = []
    for name in session.get("strategies") or []:
        account = (session.get("accounts") or {}).get(name) or {}
        metrics = _ratio_metrics(account.get("equity_curve") or [], account.get("trades") or [], initial_cash)
        results.append({
            "name": account.get("name") or name,
            "displayName": account.get("displayName") or name,
            "metrics": metrics,
            "equity_curve": account.get("equity_curve") or [],
            "trades": account.get("trades") or [],
            "signals": account.get("signals") or [],
            "open_position": _open_position_payload(account.get("position"), mark_price),
        })
    leaderboard = sorted(
        [{"name": item["name"], "displayName": item["displayName"], **item["metrics"], "open_position": item.get("open_position")} for item in results],
        key=lambda row: _num(row.get("total_return_pct")),
        reverse=True,
    )
    for idx, row in enumerate(leaderboard, start=1):
        row["rank"] = idx
    return {"leaderboard": leaderboard, "results": results}


def _advance_account_on_candle(
    *,
    account: Dict[str, Any],
    strategy_name: str,
    candles: List[Dict[str, Any]],
    candle_idx: int,
    step_idx: int,
    indicators: Any,
    config: BacktestConfig,
    allocation_pct: float,
    allow_short: bool,
) -> None:
    strategy = get_strategy(strategy_name)
    params = dict(strategy.default_params())
    strategy.prepare(candles, params)
    candle = candles[candle_idx]
    price = _num(candle.get("close"))
    signal = strategy.generate_signal(candles, candle_idx, params, indicators)
    action = str(signal.action or "WAIT")
    score = _num(signal.score)
    account.setdefault("signals", []).append({"time": candle["tsSec"], "price": price, "action": action, "score": round(score, 6)})
    if len(account["signals"]) > 500:
        account["signals"] = account["signals"][-500:]

    position_state = account.get("position")
    if position_state:
        trade = Trade(
            entry_idx=int(position_state.get("entry_step") or 0),
            entry_price=_num(position_state.get("entry_price")),
            entry_ts=int(position_state.get("entry_time") or 0),
            direction=str(position_state.get("direction") or "LONG"),
            peak_price=_num(position_state.get("peak_price") or position_state.get("entry_price")),
        )
        update_peak_price(trade, price)
        position_state["peak_price"] = trade.peak_price
        should_exit, reason, _ = check_exit(trade, price, score, step_idx, config)
        if should_exit:
            closed = close_position(trade, price, step_idx, candle["tsSec"], reason, config.commission_pct, config.slippage_pct)
            pnl_usd = _num(position_state.get("notional_usd")) * closed.pnl_pct / 100
            account["cash_equity"] = _num(account.get("cash_equity"), 0.0) + pnl_usd
            account.setdefault("trades", []).append({
                "time": candle["tsSec"],
                "action": "exit",
                "direction": closed.direction,
                "price": round(price, 8),
                "pnl_pct": round(closed.pnl_pct, 6),
                "pnl_usd": round(pnl_usd, 8),
                "reason": reason,
            })
            account["position"] = None

    if account.get("position") is None and price > 0 and _num(account.get("cash_equity")) > 0:
        entry_threshold = _num(params.get("entry_threshold"), 25.0)
        direction = ""
        if action == "LONG" and score >= entry_threshold:
            direction = "LONG"
        elif action == "SHORT" and score <= -entry_threshold and allow_short:
            direction = "SHORT"
        if direction:
            entry_price = price * (1 + config.slippage_pct / 100) if direction == "LONG" else price * (1 - config.slippage_pct / 100)
            notional = max(0.0, _num(account.get("cash_equity")) * allocation_pct)
            account["position"] = {
                "direction": direction,
                "entry_step": step_idx,
                "entry_time": candle["tsSec"],
                "entry_price": entry_price,
                "peak_price": entry_price,
                "notional_usd": notional,
            }
            account.setdefault("trades", []).append({
                "time": candle["tsSec"],
                "action": "entry",
                "direction": direction,
                "price": round(entry_price, 8),
                "notional_usd": round(notional, 8),
                "reason": action,
            })

    marked_equity = _equity_with_mark(_num(account.get("cash_equity")), _PaperPosition(
        trade=Trade(
            entry_idx=int((account.get("position") or {}).get("entry_step") or 0),
            entry_price=_num((account.get("position") or {}).get("entry_price")),
            entry_ts=int((account.get("position") or {}).get("entry_time") or 0),
            direction=str((account.get("position") or {}).get("direction") or "LONG"),
        ),
        notional=_num((account.get("position") or {}).get("notional_usd")),
    ) if account.get("position") else None, price)
    peak_equity = max(_num(account.get("peak_equity"), marked_equity), marked_equity)
    account["peak_equity"] = peak_equity
    account.setdefault("equity_curve", []).append({
        "time": candle["tsSec"],
        "value": round(marked_equity, 8),
        "price": round(price, 8),
        "drawdown": round((peak_equity - marked_equity) / peak_equity * 100, 6) if peak_equity > 0 else 0.0,
        "inPosition": account.get("position") is not None,
    })
    if len(account["equity_curve"]) > 2000:
        account["equity_curve"] = account["equity_curve"][-2000:]
    if len(account.get("trades") or []) > 1000:
        account["trades"] = account["trades"][-1000:]


async def fetch_kucoin_candles(symbol: str, kline_type: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch up to `limit` candles, paging backwards when KuCoin caps one response."""
    from web.api.dashboard_service import kucoin_get, normalize_candle

    normalized_symbol = _normalize_symbol(symbol)
    timeframe = _TIMEFRAME_SECONDS.get(kline_type, 60 * 60)
    target = max(80, min(int(limit or 300), 5000))
    seen: Dict[int, Dict[str, Any]] = {}
    end_at = int(time.time())

    for _ in range(max(1, math.ceil(target / 1400) + 1)):
        start_at = max(0, end_at - timeframe * 1500)
        data = await kucoin_get(
            "/api/v1/market/candles",
            params={"symbol": normalized_symbol, "type": kline_type, "startAt": start_at, "endAt": end_at},
        )
        rows = data.get("data") or []
        candles = [candle for candle in (normalize_candle(row) for row in rows) if candle]
        if not candles:
            break
        for candle in candles:
            seen[int(candle["tsSec"])] = candle
        oldest = min(int(candle["tsSec"]) for candle in candles)
        if len(seen) >= target or oldest <= 0:
            break
        end_at = oldest - 1

    candles = sorted(seen.values(), key=lambda item: item["tsSec"])
    if len(candles) < 60:
        data = await kucoin_get(f"/api/v1/market/candles?symbol={normalized_symbol}&type={kline_type}")
        rows = data.get("data") or []
        candles = sorted([c for c in (normalize_candle(row) for row in rows[:target]) if c], key=lambda item: item["tsSec"])
    return candles[-target:]


@dataclass
class _PaperPosition:
    trade: Trade
    notional: float


def _equity_with_mark(account_equity: float, position: Optional[_PaperPosition], price: float) -> float:
    if not position or position.trade.entry_price <= 0:
        return account_equity
    if position.trade.direction == "LONG":
        pnl_pct = (price - position.trade.entry_price) / position.trade.entry_price * 100
    else:
        pnl_pct = (position.trade.entry_price - price) / position.trade.entry_price * 100
    return account_equity + position.notional * pnl_pct / 100


def _max_drawdown_pct(values: List[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            drawdown = max(drawdown, (peak - value) / peak * 100)
    return drawdown


def _ratio_metrics(curve: List[Dict[str, Any]], trades: List[Dict[str, Any]], initial_cash: float) -> Dict[str, Any]:
    values = [_num(item.get("value")) for item in curve]
    final_equity = values[-1] if values else initial_cash
    returns = []
    for prev, cur in zip(values, values[1:]):
        if prev > 0:
            returns.append(cur / prev - 1)
    avg_ret = sum(returns) / len(returns) if returns else 0.0
    variance = sum((item - avg_ret) ** 2 for item in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    downside = [item for item in returns if item < 0]
    downside_var = sum(item ** 2 for item in downside) / len(downside) if downside else 0.0
    scale = math.sqrt(365) if len(returns) > 1 else 1.0
    sharpe = avg_ret / math.sqrt(variance) * scale if variance > 0 else 0.0
    sortino = avg_ret / math.sqrt(downside_var) * scale if downside_var > 0 else 0.0
    max_dd = _max_drawdown_pct(values)
    total_return = (final_equity / initial_cash - 1) * 100 if initial_cash > 0 else 0.0
    calmar = total_return / max_dd if max_dd > 0 else 0.0
    entries = [trade for trade in trades if trade.get("action") == "entry"]
    closed = [trade for trade in trades if trade.get("action") == "exit"]
    wins = [trade for trade in closed if _num(trade.get("pnl_pct")) > 0]
    losses = [trade for trade in closed if _num(trade.get("pnl_pct")) < 0]
    gross_profit = sum(_num(trade.get("pnl_usd")) for trade in wins)
    gross_loss = abs(sum(_num(trade.get("pnl_usd")) for trade in losses))
    return {
        "final_equity": round(final_equity, 8),
        "total_return_pct": round(total_return, 6),
        "max_drawdown_pct": round(max_dd, 6),
        "sharpe_ratio": round(sharpe, 6),
        "sortino_ratio": round(sortino, 6),
        "calmar_ratio": round(calmar, 6),
        "entry_trades": len(entries),
        "closed_trades": len(closed),
        "total_trades": len(closed),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 4) if closed else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss > 0 else (round(gross_profit, 6) if gross_profit > 0 else 0.0),
    }


def _simulate_strategy(
    *,
    candles: List[Dict[str, Any]],
    strategy_name: str,
    initial_cash: float,
    config: BacktestConfig,
    allocation_pct: float,
    allow_short: bool,
) -> Dict[str, Any]:
    strategy = get_strategy(strategy_name)
    params = dict(strategy.default_params())
    indicators = compute_all_indicators(candles)
    strategy.prepare(candles, params)
    entry_threshold = _num(params.get("entry_threshold"), 25.0)
    account_equity = initial_cash
    peak_equity = initial_cash
    position: Optional[_PaperPosition] = None
    curve: List[Dict[str, Any]] = []
    trades: List[Dict[str, Any]] = []
    signals: List[Dict[str, Any]] = []
    start_idx = min(max(config.min_context, 1), max(len(candles) - 1, 1))

    for idx in range(start_idx, len(candles)):
        candle = candles[idx]
        price = _num(candle.get("close"))
        signal = strategy.generate_signal(candles, idx, params, indicators)
        action = str(signal.action or "WAIT")
        score = _num(signal.score)
        signals.append({"time": candle["tsSec"], "price": price, "action": action, "score": round(score, 6)})

        if position is not None:
            update_peak_price(position.trade, price)
            should_exit, reason, _ = check_exit(position.trade, price, score, idx, config)
            if should_exit:
                closed = close_position(position.trade, price, idx, candle["tsSec"], reason, config.commission_pct, config.slippage_pct)
                pnl_usd = position.notional * closed.pnl_pct / 100
                account_equity += pnl_usd
                trades.append({
                    "time": candle["tsSec"],
                    "action": "exit",
                    "direction": closed.direction,
                    "price": round(price, 8),
                    "pnl_pct": round(closed.pnl_pct, 6),
                    "pnl_usd": round(pnl_usd, 8),
                    "reason": reason,
                })
                position = None

        if position is None and price > 0 and account_equity > 0:
            direction = ""
            if action == "LONG" and score >= entry_threshold:
                direction = "LONG"
            elif action == "SHORT" and score <= -entry_threshold and allow_short:
                direction = "SHORT"
            if direction:
                if direction == "LONG":
                    entry_price = price * (1 + config.slippage_pct / 100)
                else:
                    entry_price = price * (1 - config.slippage_pct / 100)
                notional = max(0.0, account_equity * allocation_pct)
                position = _PaperPosition(
                    trade=Trade(entry_idx=idx, entry_price=entry_price, entry_ts=candle["tsSec"], direction=direction, peak_price=entry_price),
                    notional=notional,
                )
                trades.append({
                    "time": candle["tsSec"],
                    "action": "entry",
                    "direction": direction,
                    "price": round(entry_price, 8),
                    "notional_usd": round(notional, 8),
                    "reason": action,
                })

        marked_equity = _equity_with_mark(account_equity, position, price)
        peak_equity = max(peak_equity, marked_equity)
        curve.append({
            "time": candle["tsSec"],
            "value": round(marked_equity, 8),
            "price": round(price, 8),
            "drawdown": round((peak_equity - marked_equity) / peak_equity * 100, 6) if peak_equity > 0 else 0.0,
            "inPosition": position is not None,
        })

    metrics = _ratio_metrics(curve, trades, initial_cash)
    open_position = None
    if position is not None and candles:
        last_price = _num(candles[-1].get("close"))
        open_position = {
            "direction": position.trade.direction,
            "entry_time": position.trade.entry_ts,
            "entry_price": round(position.trade.entry_price, 8),
            "notional_usd": round(position.notional, 8),
            "mark_price": round(last_price, 8),
            "unrealized_usd": round(_equity_with_mark(0, position, last_price), 8),
        }
    return {
        "name": strategy.name,
        "displayName": strategy.display_name,
        "metrics": metrics,
        "equity_curve": curve,
        "trades": trades,
        "signals": signals,
        "open_position": open_position,
    }


async def run_strategy_paper_arena(
    *,
    symbol: str,
    kline_type: str,
    limit: int,
    strategies: Iterable[str] | None,
    initial_cash: float,
    allocation_pct: float,
    slippage_pct: float,
    commission_pct: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    trailing_stop_pct: float,
    max_hold_bars: int,
    allow_short: bool,
    market_type: str = "spot",
) -> Dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_type = kline_type if kline_type in _TIMEFRAME_SECONDS else "1hour"
    candle_limit = max(80, min(int(limit or 500), 5000))
    cash = max(1.0, float(initial_cash or 10000))
    allocation = max(0.01, min(float(allocation_pct or 1.0), 1.0))
    names = _normalize_strategy_names(strategies)
    candles = await fetch_kucoin_candles(normalized_symbol, normalized_type, candle_limit)
    if len(candles) < 60:
        raise ValueError(f"K线数据不足: 需要至少 60 根, 当前 {len(candles)} 根")

    config = BacktestConfig(
        min_context=60,
        stop_loss_pct=max(0.1, float(stop_loss_pct or 3.0)),
        take_profit_pct=max(0.1, float(take_profit_pct or 5.0)),
        trailing_stop_pct=max(0.0, float(trailing_stop_pct or 0.0)),
        max_hold_bars=max(0, int(max_hold_bars or 0)),
        commission_pct=max(0.0, float(commission_pct or 0.0)),
        slippage_pct=max(0.0, float(slippage_pct or 0.0)),
        kline_type=normalized_type,
    )
    effective_allow_short = bool(allow_short)
    results = [
        _simulate_strategy(
            candles=candles,
            strategy_name=name,
            initial_cash=cash,
            config=config,
            allocation_pct=allocation,
            allow_short=effective_allow_short,
        )
        for name in names
    ]
    leaderboard = sorted(
        [
            {
                "name": item["name"],
                "displayName": item["displayName"],
                **item["metrics"],
                "open_position": item.get("open_position"),
            }
            for item in results
        ],
        key=lambda row: _num(row.get("total_return_pct")),
        reverse=True,
    )
    for idx, row in enumerate(leaderboard, start=1):
        row["rank"] = idx
    return {
        "symbol": normalized_symbol,
        "type": normalized_type,
        "market_type": market_type,
        "candles": len(candles),
        "from_ts": candles[0]["tsSec"],
        "to_ts": candles[-1]["tsSec"],
        "assumptions": {
            "fill": "按 K 线收盘价全额成交",
            "slippage_pct": config.slippage_pct,
            "commission_pct": config.commission_pct,
            "initial_cash": cash,
            "allocation_pct": allocation,
            "allow_short": effective_allow_short,
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
            "trailing_stop_pct": config.trailing_stop_pct,
            "max_hold_bars": config.max_hold_bars,
        },
        "leaderboard": leaderboard,
        "results": results,
    }


async def reset_strategy_paper_session(
    *,
    symbol: str,
    kline_type: str,
    strategies: Iterable[str] | None,
    initial_cash: float,
    allocation_pct: float,
    slippage_pct: float,
    commission_pct: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    trailing_stop_pct: float,
    max_hold_bars: int,
    allow_short: bool,
    market_type: str = "spot",
    warmup_limit: int = 300,
    process_now: bool = True,
) -> Dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_type = kline_type if kline_type in _TIMEFRAME_SECONDS else "1hour"
    names = _normalize_strategy_names(strategies)
    cash = max(1.0, float(initial_cash or 10000))
    allocation = max(0.01, min(float(allocation_pct or 1.0), 1.0))
    market = str(market_type or "spot").lower()
    effective_allow_short = bool(allow_short)
    config = _build_config(
        kline_type=normalized_type,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct,
        max_hold_bars=max_hold_bars,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
    )
    accounts = {}
    for name in names:
        strategy = get_strategy(name)
        accounts[name] = {
            "name": strategy.name,
            "displayName": strategy.display_name,
            "cash_equity": cash,
            "peak_equity": cash,
            "position": None,
            "equity_curve": [],
            "trades": [],
            "signals": [],
        }
    session = {
        "session_id": f"paper-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "mode": "live_session",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "symbol": normalized_symbol,
        "type": normalized_type,
        "market_type": market,
        "strategies": names,
        "initial_cash": cash,
        "allocation_pct": allocation,
        "allow_short": effective_allow_short,
        "warmup_limit": max(80, min(int(warmup_limit or 300), 1000)),
        "last_processed_ts": 0,
        "processed_bars": 0,
        "config": {
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
            "trailing_stop_pct": config.trailing_stop_pct,
            "max_hold_bars": config.max_hold_bars,
            "commission_pct": config.commission_pct,
            "slippage_pct": config.slippage_pct,
        },
        "assumptions": {
            "fill": "只处理最新已闭合K线，按收盘价全额模拟成交",
            "slippage_pct": config.slippage_pct,
            "commission_pct": config.commission_pct,
            "initial_cash": cash,
            "allocation_pct": allocation,
            "allow_short": effective_allow_short,
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
            "trailing_stop_pct": config.trailing_stop_pct,
            "max_hold_bars": config.max_hold_bars,
        },
        "accounts": accounts,
    }
    _save_session(session)
    if process_now:
        return await advance_strategy_paper_session(session["session_id"])
    return await get_strategy_paper_session(session["session_id"])


async def advance_strategy_paper_session(session_id: str, warmup_limit: Optional[int] = None) -> Dict[str, Any]:
    session = _load_session(session_id)
    kline_type = str(session.get("type") or "1hour")
    warmup = max(80, min(int(warmup_limit or session.get("warmup_limit") or 300), 1000))
    candles = await fetch_kucoin_candles(str(session.get("symbol") or "BTC-USDT"), kline_type, warmup)
    if len(candles) < 60:
        raise ValueError(f"K线数据不足: 需要至少 60 根, 当前 {len(candles)} 根")
    closed = _closed_candles(candles, kline_type)
    if not closed:
        raise ValueError("还没有可处理的已闭合K线")
    last_processed_ts = int(session.get("last_processed_ts") or 0)
    if last_processed_ts > 0:
        candidates = [candle for candle in closed if int(candle.get("tsSec") or 0) > last_processed_ts]
    else:
        candidates = [closed[-1]]
    candidates = candidates[-200:]
    latest = closed[-1]
    mark_price = _num(latest.get("close"))
    processed_now = 0
    skipped_reason = ""

    if candidates:
        config_row = session.get("config") or {}
        config = _build_config(
            kline_type=kline_type,
            stop_loss_pct=_num(config_row.get("stop_loss_pct"), 3.0),
            take_profit_pct=_num(config_row.get("take_profit_pct"), 5.0),
            trailing_stop_pct=_num(config_row.get("trailing_stop_pct"), 0.0),
            max_hold_bars=int(_num(config_row.get("max_hold_bars"), 0)),
            commission_pct=_num(config_row.get("commission_pct"), 0.1),
            slippage_pct=_num(config_row.get("slippage_pct"), 0.05),
        )
        indicators = compute_all_indicators(candles)
        candle_index = {int(candle.get("tsSec") or 0): idx for idx, candle in enumerate(candles)}
        for candle in candidates:
            ts = int(candle.get("tsSec") or 0)
            candle_idx = candle_index.get(ts)
            if candle_idx is None or candle_idx < config.min_context:
                continue
            step_idx = int(session.get("processed_bars") or 0) + 1
            for name in session.get("strategies") or []:
                account = (session.get("accounts") or {}).get(name)
                if not account:
                    continue
                _advance_account_on_candle(
                    account=account,
                    strategy_name=name,
                    candles=candles,
                    candle_idx=candle_idx,
                    step_idx=step_idx,
                    indicators=indicators,
                    config=config,
                    allocation_pct=_num(session.get("allocation_pct"), 1.0),
                    allow_short=bool(session.get("allow_short")),
                )
            session["last_processed_ts"] = ts
            session["processed_bars"] = step_idx
            processed_now += 1
        _save_session(session)
    else:
        skipped_reason = "latest_candle_already_processed"

    payload = _session_results(session, mark_price)
    return {
        "mode": "live_session",
        "session_id": session.get("session_id"),
        "symbol": session.get("symbol"),
        "type": kline_type,
        "market_type": session.get("market_type"),
        "status": "processed" if processed_now else "waiting",
        "processed_now": processed_now,
        "processed_bars": session.get("processed_bars") or 0,
        "last_processed_ts": session.get("last_processed_ts") or 0,
        "latest_candle": {
            "time": latest.get("tsSec"),
            "close": mark_price,
            "is_processed": int(latest.get("tsSec") or 0) <= int(session.get("last_processed_ts") or 0),
        },
        "warmup_candles": len(candles),
        "skipped_reason": skipped_reason,
        "assumptions": session.get("assumptions") or {},
        **payload,
    }


async def get_strategy_paper_session(session_id: str) -> Dict[str, Any]:
    session = _load_session(session_id)
    mark_price = 0.0
    try:
        candles = await fetch_kucoin_candles(str(session.get("symbol") or "BTC-USDT"), str(session.get("type") or "1hour"), 80)
        closed = _closed_candles(candles, str(session.get("type") or "1hour"))
        if closed:
            mark_price = _num(closed[-1].get("close"))
    except Exception:
        mark_price = 0.0
    payload = _session_results(session, mark_price)
    return {
        "mode": "live_session",
        "session_id": session.get("session_id"),
        "symbol": session.get("symbol"),
        "type": session.get("type"),
        "market_type": session.get("market_type"),
        "status": "loaded",
        "processed_now": 0,
        "processed_bars": session.get("processed_bars") or 0,
        "last_processed_ts": session.get("last_processed_ts") or 0,
        "warmup_candles": session.get("warmup_limit") or 0,
        "assumptions": session.get("assumptions") or {},
        **payload,
    }