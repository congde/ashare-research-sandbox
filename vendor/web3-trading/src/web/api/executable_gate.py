# -*- coding: utf-8 -*-
"""
④ 可执行维 — 单一真相源。

职责划分：
- trade_plan_executor：价位结构校验、多空盈亏比计算
- executable_gate（本模块）：准备度推断、 enrich 收尾、门禁 ④ 判定
- entry_gate：①②③ 结构/因子/量化 + 调用本模块做 ④
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from web.api.signal_schema import SignalOutput

# 门禁仅认 ready / 可执行
EXECUTION_READY_VALUES = frozenset({"ready", "可执行"})

# LLM 显式返回的准备度（含中文展示值）
_EXPLICIT_READINESS = frozenset({
    "ready", "watch_pullback", "wait_breakout", "avoid",
    "可执行", "等待回踩", "等待突破确认", "暂不参与",
})

_UNSET_READINESS = frozenset({"", "wait", "继续观察"})


def is_execution_ready(readiness: Any) -> bool:
    text = str(readiness or "").strip().lower()
    if text in EXECUTION_READY_VALUES:
        return True
    raw = str(readiness or "")
    return "ready" in raw or "可执行" in raw


def infer_execution_readiness(readiness: Any, signal: str) -> str:
    """LLM 未写 preparation 时按信号补默认；显式值原样保留。"""
    text = str(readiness or "").strip().lower()
    if text in _EXPLICIT_READINESS:
        return str(readiness).strip()
    if text and text not in _UNSET_READINESS:
        return str(readiness).strip()
    if signal in {"BUY", "SELL"}:
        return "ready"
    if signal in {"WEAK_BUY", "WEAK_SELL"}:
        return "watch_pullback"
    return "wait"


def _mark_price(data: Dict[str, Any]) -> float:
    from web.api.realtime_market_bridge import resolve_live_mark_price

    return resolve_live_mark_price(data)


def _plan_dict(result: SignalOutput) -> Dict[str, float]:
    from web.api.trade_plan_executor import normalize_trade_plan

    tp = result.tradePlan
    if not tp:
        return {}
    raw = tp.model_dump() if hasattr(tp, "model_dump") else tp
    return normalize_trade_plan(raw)


def _location_blocks_side(
    side: str,
    plan: Dict[str, float],
    data: Dict[str, Any],
) -> Tuple[bool, str]:
    from web.api.trade_plan_executor import (
        assess_short_term_sell_timing,
        is_long_entry_near_resistance,
        is_short_entry_near_support,
    )

    mark = _mark_price(data)
    kline = data.get("kline")
    if side == "sell":
        timing, note = assess_short_term_sell_timing(mark, plan, kline_data=kline)
        if timing == "ready":
            return False, ""
        if timing == "watch_pullback":
            return True, note
        return is_short_entry_near_support(mark, plan, kline_data=kline)
    if side == "buy":
        return is_long_entry_near_resistance(mark, plan, kline_data=kline)
    return False, ""


def populate_risk_rewards(result: SignalOutput, *, conservative: bool) -> Dict[str, Dict[str, float]]:
    """写入 execution 做多/做空 RR；riskReward1/2 跟随信号方向。"""
    from web.api.trade_plan_executor import (
        calc_dual_trade_plan_risk_rewards,
        gate_side_from_signal,
        pick_risk_reward_for_side,
    )

    empty = {
        "buy": {"rr1": 0.0, "rr2": 0.0, "rr_gate": 0.0},
        "sell": {"rr1": 0.0, "rr2": 0.0, "rr_gate": 0.0},
    }
    plan = _plan_dict(result)
    if not plan or plan.get("stop", 0) <= 0:
        return empty

    dual = calc_dual_trade_plan_risk_rewards(plan, conservative=conservative)
    buy, sell = dual.get("buy") or {}, dual.get("sell") or {}
    ex = result.analysis.execution
    ex.longRiskReward1 = float(buy.get("rr1") or 0)
    ex.longRiskReward2 = float(buy.get("rr2") or 0)
    ex.shortRiskReward1 = float(sell.get("rr1") or 0)
    ex.shortRiskReward2 = float(sell.get("rr2") or 0)

    side = gate_side_from_signal(result.signal)
    rr1, rr2, _ = pick_risk_reward_for_side(dual, side)
    if rr1 > 0:
        ex.riskReward1 = rr1
    if rr2 > 0:
        ex.riskReward2 = rr2

    result.debug.sourceRefs = {
        **(result.debug.sourceRefs or {}),
        "riskRewardDual": dual,
        "riskRewardSide": side or "",
    }
    return dual


def finalize_signal_execution(result: SignalOutput, data: Dict[str, Any]) -> None:
    """
    LLM enrich 末尾唯一入口（在 unanimous 强化信号之后、localize 之前）：

    1. 按信号补全 preparation 默认值
    2. 做空：1m/5m/15m 短周期 timing（贴支撑反弹 → watch_pullback；破位 → ready）
    3. 贴支撑/贴阻力兜底（与短周期 timing 共用 assess_short_term_sell_timing）
    4. 计算做多/做空两套 RR，riskReward1/2 取信号方向
    """
    from web.api.trade_plan_executor import gate_side_from_signal

    result.analysis.executionReadiness = infer_execution_readiness(
        result.analysis.executionReadiness,
        result.signal,
    )

    side = gate_side_from_signal(result.signal)
    plan = _plan_dict(result)
    if side and plan:
        from web.api.trade_plan_executor import assess_short_term_sell_timing

        mark = _mark_price(data)
        timing_note = ""
        if side == "sell" and str(result.signal or "").upper() in {"SELL", "WEAK_SELL"}:
            timing, timing_note = assess_short_term_sell_timing(
                mark, plan, kline_data=data.get("kline")
            )
            if timing == "watch_pullback":
                result.analysis.executionReadiness = "watch_pullback"
            elif timing == "ready":
                result.analysis.executionReadiness = "ready"

        blocked, loc_note = _location_blocks_side(side, plan, data)
        note = ""
        if blocked:
            result.analysis.executionReadiness = "watch_pullback"
            note = loc_note
        elif timing_note and side == "sell":
            note = timing_note

        if note:
            action = (result.analysis.execution.action or "").strip()
            if note not in action:
                result.analysis.execution.action = (action + "；" if action else "") + note
            if note not in result.reasons:
                result.reasons.insert(0, note)

    populate_risk_rewards(result, conservative=False)


def _backtest_blocks_entry(market_data: Dict[str, Any]) -> Tuple[bool, str]:
    bt = market_data.get("strategyBacktests") if isinstance(market_data, dict) else {}
    if not isinstance(bt, dict) or not bt.get("available"):
        return False, ""
    strategies = bt.get("strategies") or bt.get("results") or []
    if not isinstance(strategies, list) or len(strategies) < 3:
        return False, ""
    losing = 0
    for row in strategies:
        if not isinstance(row, dict):
            continue
        try:
            ret = float(row.get("totalReturnPct") or row.get("returnPct") or 0)
        except (TypeError, ValueError):
            ret = 0.0
        if ret < 0:
            losing += 1
    if losing > len(strategies) * 0.6:
        return True, f"策略回测 {losing}/{len(strategies)} 亏损，禁止激进开仓"
    return False, ""


def _format_gate_note(
    *,
    side: str,
    dual: Dict[str, Dict[str, float]],
    rr1: float,
    rr2: float,
    rr_gate: float,
    passed: bool,
) -> str:
    buy = dual.get("buy") or {}
    sell = dual.get("sell") or {}
    label = "做空" if side == "sell" else "做多"
    t2 = f" T2={rr2:.2f}" if rr2 > 0 else ""
    ref = f"（参照 多={buy.get('rr_gate', 0):.2f} 空={sell.get('rr_gate', 0):.2f}）"
    if passed:
        return f"ready · {label} R:R={rr_gate:.2f}（T1={rr1:.2f}{t2}）{ref}"
    return f"{label} R:R={rr_gate:.2f}（T1={rr1:.2f}{t2}）{ref}"


def evaluate_executable_gate(
    result: SignalOutput,
    market_data: Dict[str, Any],
    *,
    min_rr: float,
    require_backtest_ok: bool,
) -> Tuple[bool, str]:
    """
    门禁 ④ 顺序判定（与 finalize 使用同一套规则）：

    1. 执行准备度 = ready
    2. 交易计划完整
    3. 信号能映射合约方向 buy/sell
    4. 计划价位符合该方向（止损/目标位置）
    5. 非贴支撑做空 / 贴阻力做多
    6. 采用该方向盈亏比 ≥ min_rr（同时计算多空两套，按方向取用）
    7. 回测否决（可选）
    """
    from web.api.trade_plan_executor import (
        gate_side_from_signal,
        pick_risk_reward_for_side,
        validate_trade_plan_shape,
    )

    readiness = str(result.analysis.executionReadiness or "wait").lower()
    if not is_execution_ready(readiness):
        return False, f"执行准备度={readiness}（需 ready）"

    plan = _plan_dict(result)
    if not plan or plan.get("entryLow", 0) <= 0 or plan.get("stop", 0) <= 0:
        return False, "缺少可执行交易计划（入场区间/止损）"

    side = gate_side_from_signal(result.signal)
    if not side:
        return False, "信号方向未定（需 BUY/SELL），无法选取盈亏比"

    ok, shape_reason = validate_trade_plan_shape(plan, side)
    if not ok:
        return False, shape_reason

    blocked, loc_note = _location_blocks_side(side, plan, market_data)
    if blocked:
        return False, loc_note

    dual = populate_risk_rewards(result, conservative=True)
    rr1, rr2, rr_gate = pick_risk_reward_for_side(dual, side)
    if rr_gate < min_rr:
        return False, _format_gate_note(
            side=side, dual=dual, rr1=rr1, rr2=rr2, rr_gate=rr_gate, passed=False,
        ) + f" < 门槛 {min_rr}"

    if require_backtest_ok:
        veto, veto_note = _backtest_blocks_entry(market_data)
        if veto:
            return False, veto_note

    return True, _format_gate_note(
        side=side, dual=dual, rr1=rr1, rr2=rr2, rr_gate=rr_gate, passed=True,
    )


# 兼容旧 import
_is_execution_ready = is_execution_ready
