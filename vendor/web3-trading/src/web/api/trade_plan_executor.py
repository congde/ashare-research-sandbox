# -*- coding: utf-8 -*-
"""Enforce LLM / rule-engine tradePlan on live futures entries and exits."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if number != number:
            return default
        return number
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "0", "no", "off", "")


def resolve_trade_plan_options() -> Dict[str, Any]:
    strict = _coerce_bool(os.getenv("LIVE_TRADE_PLAN_STRICT"), True)
    tolerance_pct = float(os.getenv("LIVE_TRADE_PLAN_ENTRY_TOLERANCE_PCT") or 0.15)
    enforce_stop = _coerce_bool(os.getenv("LIVE_TRADE_PLAN_ENFORCE_STOP"), True)
    enforce_targets = _coerce_bool(os.getenv("LIVE_TRADE_PLAN_ENFORCE_TARGETS"), True)

    try:
        from web.config import config

        if getattr(config, "live_trade_plan_strict", None) is not None:
            strict = _coerce_bool(config.live_trade_plan_strict, strict)
        if getattr(config, "live_trade_plan_entry_tolerance_pct", None) is not None:
            tolerance_pct = float(config.live_trade_plan_entry_tolerance_pct)
        if getattr(config, "live_trade_plan_enforce_stop", None) is not None:
            enforce_stop = _coerce_bool(config.live_trade_plan_enforce_stop, enforce_stop)
        if getattr(config, "live_trade_plan_enforce_targets", None) is not None:
            enforce_targets = _coerce_bool(config.live_trade_plan_enforce_targets, enforce_targets)
    except Exception:
        pass

    return {
        "strict": strict,
        "entry_tolerance_pct": max(0.0, min(2.0, tolerance_pct)),
        "enforce_stop": enforce_stop,
        "enforce_targets": enforce_targets,
    }


def normalize_trade_plan(raw: Any) -> Dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    keys = ("support", "resistance", "entryLow", "entryHigh", "stop", "target1", "target2")
    return {key: _num(raw.get(key)) for key in keys}


def gate_side_from_signal(signal: str) -> Optional[str]:
    """Map LLM signal to futures entry side for plan validation."""
    sig = str(signal or "").upper()
    if sig in {"BUY", "WEAK_BUY"}:
        return "buy"
    if sig in {"SELL", "WEAK_SELL"}:
        return "sell"
    return None


def calc_directional_risk_reward(
    entry: float,
    stop: float,
    target: float,
    side: Optional[str],
    *,
    reward_entry: Optional[float] = None,
) -> float:
    """Risk/reward for futures long or short; 0 when geometry disagrees with side."""
    if entry <= 0 or stop <= 0 or target <= 0:
        return 0.0
    reward_at = reward_entry if reward_entry is not None and reward_entry > 0 else entry
    s = str(side or "").lower()
    if s == "sell":
        if stop <= entry or target >= reward_at:
            return 0.0
        risk = stop - entry
        reward = reward_at - target
    elif s == "buy":
        if stop >= entry or target <= reward_at:
            return 0.0
        risk = entry - stop
        reward = target - reward_at
    else:
        risk = abs(entry - stop)
        reward = abs(target - entry)
    if risk <= 0 or reward <= 0:
        return 0.0
    return round(reward / risk, 2)


def _entry_prices_for_rr(
    plan: Dict[str, float],
    side: Optional[str],
    *,
    conservative: bool,
) -> Tuple[float, float]:
    """Return (risk_entry, reward_entry). Conservative = worst-case band for gate."""
    entry_low = _num(plan.get("entryLow"))
    entry_high = _num(plan.get("entryHigh"))
    if entry_low <= 0 or entry_high <= 0:
        mid = entry_low or entry_high
        return mid, mid
    if not conservative:
        mid = (entry_low + entry_high) / 2.0
        return mid, mid
    s = str(side or "").lower()
    if s == "sell":
        return entry_low, entry_high
    if s == "buy":
        return entry_high, entry_low
    mid = (entry_low + entry_high) / 2.0
    return mid, mid


def calc_trade_plan_risk_rewards(
    plan: Dict[str, float],
    side: Optional[str],
    *,
    conservative: bool = False,
) -> Tuple[float, float, float]:
    """Return (rr1, rr2, rr_gate). Gate uses best valid target R:R (max of T1/T2)."""
    stop = _num(plan.get("stop"))
    t1 = _num(plan.get("target1"))
    t2 = _num(plan.get("target2"))
    risk_entry, reward_entry = _entry_prices_for_rr(plan, side, conservative=conservative)
    rr1 = (
        calc_directional_risk_reward(risk_entry, stop, t1, side, reward_entry=reward_entry)
        if t1 > 0
        else 0.0
    )
    rr2 = (
        calc_directional_risk_reward(risk_entry, stop, t2, side, reward_entry=reward_entry)
        if t2 > 0
        else 0.0
    )
    valid = [r for r in (rr1, rr2) if r > 0]
    rr_gate = max(valid) if valid else 0.0
    return rr1, rr2, rr_gate


def calc_dual_trade_plan_risk_rewards(
    plan: Dict[str, float],
    *,
    conservative: bool = False,
) -> Dict[str, Dict[str, float]]:
    """Compute long & short R:R from the same plan; pick one by confirmed side later."""
    buy = calc_trade_plan_risk_rewards(plan, "buy", conservative=conservative)
    sell = calc_trade_plan_risk_rewards(plan, "sell", conservative=conservative)
    return {
        "buy": {"rr1": buy[0], "rr2": buy[1], "rr_gate": buy[2]},
        "sell": {"rr1": sell[0], "rr2": sell[1], "rr_gate": sell[2]},
    }


def pick_risk_reward_for_side(
    dual: Dict[str, Dict[str, float]],
    side: Optional[str],
) -> Tuple[float, float, float]:
    """Return (rr1, rr2, rr_gate) for the confirmed futures side (buy/sell)."""
    block = dual.get(str(side or "").lower()) or {}
    return (
        _num(block.get("rr1")),
        _num(block.get("rr2")),
        _num(block.get("rr_gate")),
    )


def resolve_short_term_timing_options() -> Dict[str, Any]:
    enabled = _coerce_bool(os.getenv("LIVE_SHORT_TERM_TIMING_ENABLED"), True)
    try:
        from web.config import config

        if getattr(config, "live_short_term_timing_enabled", None) is not None:
            enabled = _coerce_bool(config.live_short_term_timing_enabled, enabled)
    except Exception:
        pass
    return {"enabled": enabled}


def _kline_range_pos(kline_data: Any, *, include_short_tf: bool = False) -> Optional[float]:
    if not isinstance(kline_data, dict):
        return None
    if include_short_tf:
        positions: list[float] = []
        for key in ("1min", "5min", "15min", "1hour", "4hour"):
            block = kline_data.get(key) or {}
            if isinstance(block, dict) and block.get("rangePos") is not None:
                try:
                    positions.append(float(block["rangePos"]))
                except (TypeError, ValueError):
                    continue
        return min(positions) if positions else None
    for key in ("1hour", "4hour", "15min"):
        block = kline_data.get(key) or {}
        if isinstance(block, dict) and block.get("rangePos") is not None:
            try:
                return float(block["rangePos"])
            except (TypeError, ValueError):
                continue
    return None


def _consecutive_candle_run(recent: Any, *, bullish: bool, min_count: int = 2) -> bool:
    if not isinstance(recent, list) or len(recent) < min_count:
        return False
    count = 0
    for candle in reversed(recent):
        if not isinstance(candle, dict):
            break
        try:
            close = float(candle.get("c", candle.get("close", 0)))
            open_ = float(candle.get("o", candle.get("open", 0)))
        except (TypeError, ValueError):
            break
        if bullish and close > open_:
            count += 1
        elif not bullish and close < open_:
            count += 1
        else:
            break
    return count >= min_count


def _short_tf_bullish_signal(block: Dict[str, Any]) -> Optional[str]:
    trend = str(block.get("trend") or "").lower()
    if trend in ("bullish", "weak_bullish"):
        return "趋势偏多"
    recent = block.get("recentCandles") or []
    if _consecutive_candle_run(recent, bullish=True):
        return "连续阳线"
    try:
        rsi = float(block.get("rsi")) if block.get("rsi") is not None else None
        macd_hist = float(block.get("macdHistogram")) if block.get("macdHistogram") is not None else None
    except (TypeError, ValueError):
        rsi = macd_hist = None
    if rsi is not None and 30 < rsi < 52 and macd_hist is not None and macd_hist > 0:
        return "RSI修复+MACD柱正"
    return None


def _short_tf_breakdown_signal(block: Dict[str, Any]) -> Optional[str]:
    trend = str(block.get("trend") or "").lower()
    if trend in ("bearish", "weak_bearish") and str(block.get("breakout") or "") == "bearish":
        return "空头突破"
    recent = block.get("recentCandles") or []
    if _consecutive_candle_run(recent, bullish=False):
        return "连续阴线"
    if len(recent) >= 3:
        try:
            first_close = float(recent[-3].get("c", recent[-3].get("close", 0)))
            last_close = float(recent[-1].get("c", recent[-1].get("close", 0)))
        except (TypeError, ValueError, KeyError, IndexError):
            first_close = last_close = 0.0
        if first_close > 0 and (last_close - first_close) / first_close <= -0.0025:
            return "短线动量偏空"
    return None


def assess_short_term_sell_timing(
    mark: float,
    plan: Dict[str, float],
    *,
    kline_data: Any = None,
) -> Tuple[str, str]:
    """1m/5m/15m 做空入场时机：贴支撑+反弹 → watch_pullback；破位动能 → ready。"""
    if not resolve_short_term_timing_options().get("enabled"):
        return "", ""
    if mark <= 0:
        return "", ""

    near_support, support_note = is_short_entry_near_support(
        mark,
        plan,
        kline_data=kline_data,
        include_short_tf_range=True,
    )
    kline = kline_data if isinstance(kline_data, dict) else {}

    if not near_support:
        for tf, lbl in (("5min", "5m"), ("1min", "1m")):
            block = kline.get(tf) or {}
            if not isinstance(block, dict):
                continue
            sig = _short_tf_breakdown_signal(block)
            if sig:
                return "ready", f"{lbl}{sig}，跌破追空可执行"
        return "", ""

    bounce: list[str] = []
    for tf, lbl in (("1min", "1m"), ("5min", "5m"), ("15min", "15m")):
        block = kline.get(tf) or {}
        if not isinstance(block, dict):
            continue
        sig = _short_tf_bullish_signal(block)
        if sig:
            bounce.append(f"{lbl}{sig}")

    breakdown: list[str] = []
    for tf, lbl in (("1min", "1m"), ("5min", "5m")):
        block = kline.get(tf) or {}
        if isinstance(block, dict) and _short_tf_breakdown_signal(block):
            breakdown.append(lbl)

    if breakdown and not bounce:
        return "ready", f"贴支撑但 {'/'.join(breakdown)} 动能下破，可破位追空"
    if bounce:
        detail = " · ".join(bounce)
        return "watch_pullback", f"贴支撑且短线反弹（{detail}），等待阻力再空"
    return "watch_pullback", support_note or "贴支撑不宜市价追空，等待反弹至阻力再空"


def _dist_pct_to_level(mark: float, level: float) -> Optional[float]:
    if mark <= 0 or level <= 0:
        return None
    return abs(mark - level) / mark * 100.0


def is_short_entry_near_support(
    mark: float,
    plan: Dict[str, float],
    *,
    kline_data: Any = None,
    max_dist_pct: float = 2.0,
    max_range_pos: float = 25.0,
    include_short_tf_range: bool = False,
) -> Tuple[bool, str]:
    """True when price/plan sits on support — poor R:R zone for opening shorts."""
    if mark <= 0:
        return False, ""
    support = _num(plan.get("support"))
    entry_low = _num(plan.get("entryLow"))
    anchor = support if support > 0 else entry_low
    dist = _dist_pct_to_level(mark, anchor) if anchor > 0 else None
    range_pos = _kline_range_pos(kline_data, include_short_tf=include_short_tf_range)
    near = (
        (dist is not None and dist <= max_dist_pct)
        or (range_pos is not None and range_pos <= max_range_pos)
    )
    if not near:
        return False, ""
    parts = []
    if dist is not None and dist <= max_dist_pct:
        parts.append(f"距支撑 {anchor:.4g} 仅 {dist:.2f}%")
    if range_pos is not None and range_pos <= max_range_pos:
        parts.append(f"区间位置 {range_pos:.0f}%")
    detail = " · ".join(parts) if parts else "贴近支撑"
    return True, f"贴支撑不宜做空（{detail}），等待反弹至阻力再空"


def is_long_entry_near_resistance(
    mark: float,
    plan: Dict[str, float],
    *,
    kline_data: Any = None,
    max_dist_pct: float = 2.0,
    min_range_pos: float = 75.0,
) -> Tuple[bool, str]:
    """True when price/plan sits on resistance — poor zone for opening longs."""
    if mark <= 0:
        return False, ""
    resistance = _num(plan.get("resistance"))
    entry_high = _num(plan.get("entryHigh"))
    anchor = resistance if resistance > 0 else entry_high
    dist = _dist_pct_to_level(mark, anchor) if anchor > 0 else None
    range_pos = _kline_range_pos(kline_data)
    near = (
        (dist is not None and dist <= max_dist_pct)
        or (range_pos is not None and range_pos >= min_range_pos)
    )
    if not near:
        return False, ""
    parts = []
    if dist is not None and dist <= max_dist_pct:
        parts.append(f"距阻力 {anchor:.4g} 仅 {dist:.2f}%")
    if range_pos is not None and range_pos >= min_range_pos:
        parts.append(f"区间位置 {range_pos:.0f}%")
    detail = " · ".join(parts) if parts else "贴近阻力"
    return True, f"贴阻力不宜做多（{detail}），等待回踩至支撑再多"


def validate_trade_plan_shape(plan: Dict[str, float], side: str) -> Tuple[bool, str]:
    """Validate plan prices are internally consistent for long/short."""
    entry_low = plan.get("entryLow") or 0
    entry_high = plan.get("entryHigh") or 0
    stop = plan.get("stop") or 0

    if entry_low <= 0 or entry_high <= 0:
        return False, "交易计划缺少有效入场区间 (entryLow/entryHigh)"
    if entry_low > entry_high:
        return False, "交易计划入场区间无效 (entryLow > entryHigh)"
    if stop <= 0:
        return False, "交易计划缺少有效止损位 (stop)"

    if side == "buy":
        if stop >= entry_low:
            return False, f"做多止损 {stop} 应低于入场下限 {entry_low}"
        t1 = plan.get("target1") or 0
        if t1 > 0 and t1 <= entry_high:
            return False, f"做多目标一 {t1} 应高于入场上限 {entry_high}"
    elif side == "sell":
        if stop <= entry_high:
            return False, f"做空止损 {stop} 应高于入场上限 {entry_high}"
        t1 = plan.get("target1") or 0
        if t1 > 0 and t1 >= entry_low:
            return False, f"做空目标一 {t1} 应低于入场下限 {entry_low}"
    return True, ""


def _band(low: float, high: float, tolerance_pct: float) -> Tuple[float, float]:
    if tolerance_pct <= 0:
        return low, high
    pad = (high - low) * (tolerance_pct / 100.0) if high > low else high * (tolerance_pct / 100.0)
    return low - pad, high + pad


def evaluate_trade_plan_entry(
    plan: Dict[str, float],
    side: str,
    mark_price: float,
    *,
    tolerance_pct: float = 0.15,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Return (allowed, reason, meta) for opening a position."""
    if mark_price <= 0:
        return False, "无法读取合约标记价格", {}

    ok, reason = validate_trade_plan_shape(plan, side)
    if not ok:
        return False, reason, {}

    low = plan["entryLow"]
    high = plan["entryHigh"]
    band_low, band_high = _band(low, high, tolerance_pct)

    if mark_price < band_low:
        return (
            False,
            f"现价 {mark_price:.4g} 低于入场区间 {low:.4g}~{high:.4g}（容差 {tolerance_pct}%），等待回踩",
            {"markPrice": mark_price, "entryLow": low, "entryHigh": high},
        )
    if mark_price > band_high:
        return (
            False,
            f"现价 {mark_price:.4g} 高于入场区间 {low:.4g}~{high:.4g}（容差 {tolerance_pct}%），等待回落",
            {"markPrice": mark_price, "entryLow": low, "entryHigh": high},
        )

    limit_price = (low + high) / 2.0
    if side == "buy":
        limit_price = min(mark_price, high)
    else:
        limit_price = max(mark_price, low)

    return True, (
        f"价格在入场区间 {low:.4g}~{high:.4g} 内，止损 {plan['stop']:.4g}，"
        f"目标 {plan.get('target1') or 0:.4g}/{plan.get('target2') or 0:.4g}"
    ), {
        "markPrice": mark_price,
        "entryLow": low,
        "entryHigh": high,
        "stop": plan["stop"],
        "target1": plan.get("target1"),
        "target2": plan.get("target2"),
        "limitPrice": round(limit_price, 8),
        # 入场区间已校验；实盘用市价确保成交，避免限价悬空
        "orderType": "market",
    }


def is_trade_plan_stop_hit(
    position: Dict[str, Any],
    plan: Dict[str, float],
) -> Tuple[bool, str]:
    mark = _num(position.get("markPrice"))
    stop = _num(plan.get("stop"))
    if mark <= 0 or stop <= 0:
        return False, ""

    pos_side = str(position.get("side") or "").lower()
    if pos_side == "long" and mark <= stop:
        return True, f"现价 {mark:.4g} 触及交易计划止损 {stop:.4g}"
    if pos_side == "short" and mark >= stop:
        return True, f"现价 {mark:.4g} 触及交易计划止损 {stop:.4g}"
    return False, ""


def is_trade_plan_target_hit(
    position: Dict[str, Any],
    plan: Dict[str, float],
    *,
    which: str = "target1",
) -> Tuple[bool, str]:
    mark = _num(position.get("markPrice"))
    target = _num(plan.get(which))
    if mark <= 0 or target <= 0:
        return False, ""

    pos_side = str(position.get("side") or "").lower()
    if pos_side == "long" and mark >= target:
        return True, f"现价 {mark:.4g} 达到交易计划{which} {target:.4g}"
    if pos_side == "short" and mark <= target:
        return True, f"现价 {mark:.4g} 达到交易计划{which} {target:.4g}"
    return False, ""


def evaluate_trade_plan_exit(
    position: Dict[str, Any],
    plan: Optional[Dict[str, float]],
    *,
    enforce_stop: bool,
    enforce_targets: bool,
) -> Tuple[bool, str, str]:
    """Return (should_close, reason, action_tag)."""
    if not plan:
        return False, "", ""

    if enforce_stop:
        hit, reason = is_trade_plan_stop_hit(position, plan)
        if hit:
            return True, reason, "plan_stop"

    if enforce_targets:
        for key in ("target1", "target2"):
            hit, reason = is_trade_plan_target_hit(position, plan, which=key)
            if hit:
                return True, reason, "plan_target"

    return False, "", ""
