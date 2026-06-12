# -*- coding: utf-8 -*-
"""入场门禁 ①–③：多周期结构 + LLM 因子 + 量化；④ 可执行见 executable_gate。"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from web.api.signal_schema import SignalOutput, TradePlan

# 硬门禁四维（llm_mtf）；rule_primary 仍为三维
GATE_DIMENSION_KEYS = ("structure", "flow", "quant", "executable")
GATE_DIMENSION_KEYS_RULE = ("structure", "flow", "executable")
GATE_MODEL_LLM_MTF = "llm_mtf+llm_factors+quant+executable"
GATE_MODEL_RULE = "rule_structure+quant_flow+executable"
_REQUIRED_TF_LABELS: Tuple[str, ...] = ("15m", "1h", "4h", "1d")

# 与 analysis.js / signal_analyzer 同源
_MTF_SPECS: Tuple[Tuple[str, str], ...] = (
    ("4hour", "4h"),
    ("1day", "1d"),
    ("1hour", "1h"),
    ("15min", "15m"),
)
_TREND_CN = {
    "bullish": "多头趋势",
    "bearish": "空头趋势",
    "weak_bullish": "短线偏多",
    "weak_bearish": "短线偏空",
    "neutral": "中性",
}

_DIM_CN_GATE = {
    "structure": "多周期（分析页）",
    "flow": "LLM 因子（技术+盘面）",
    "quant": "量化确认",
    "executable": "可执行",
    "technical": "技术（展示）",
    "positioning": "盘面（展示）",
    "onchain": "筹码/链上",
    "consensus": "共识/新闻",
}

def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "0", "no", "off", "")


def resolve_entry_gate_options() -> Dict[str, Any]:
    min_rr = float(os.getenv("LIVE_ENTRY_GATE_MIN_RR") or 1.5)
    min_confidence = float(os.getenv("LIVE_ENTRY_GATE_MIN_CONFIDENCE") or 50)
    require_backtest_ok = _coerce_bool(os.getenv("LIVE_ENTRY_GATE_REQUIRE_BACKTEST_OK"), True)
    funding_cap = float(os.getenv("LIVE_ENTRY_GATE_FUNDING_CAP") or 0.0008)
    hybrid_arena = str(os.getenv("LIVE_HYBRID_ARENA_MATCH_MODE") or "gate_only").strip().lower()
    mode = str(os.getenv("LIVE_ENTRY_GATE_MODE") or "llm_mtf").strip().lower()
    min_tf_aligned = int(os.getenv("LIVE_ENTRY_GATE_MIN_TF_ALIGNED") or 4)
    quant_veto = _coerce_bool(os.getenv("LIVE_ENTRY_GATE_QUANT_VETO"), True)

    try:
        from web.config import config

        if getattr(config, "live_entry_gate_min_rr", None) is not None:
            min_rr = float(config.live_entry_gate_min_rr)
        if getattr(config, "live_entry_gate_min_confidence", None) is not None:
            min_confidence = float(config.live_entry_gate_min_confidence)
        if getattr(config, "live_entry_gate_require_backtest_ok", None) is not None:
            require_backtest_ok = _coerce_bool(
                config.live_entry_gate_require_backtest_ok, require_backtest_ok
            )
        if getattr(config, "live_entry_gate_funding_cap", None) is not None:
            funding_cap = float(config.live_entry_gate_funding_cap)
        if getattr(config, "hybrid_arena_match_mode", None):
            hybrid_arena = str(config.hybrid_arena_match_mode).strip().lower()
        if getattr(config, "live_entry_gate_mode", None):
            mode = str(config.live_entry_gate_mode).strip().lower()
        if getattr(config, "live_entry_gate_min_tf_aligned", None) is not None:
            min_tf_aligned = int(config.live_entry_gate_min_tf_aligned)
        if getattr(config, "live_entry_gate_quant_veto", None) is not None:
            quant_veto = _coerce_bool(config.live_entry_gate_quant_veto, quant_veto)
    except Exception:
        pass

    return {
        "mode": mode if mode in ("llm_mtf", "rule_primary") else "llm_mtf",
        "min_rr": max(0.5, min_rr),
        "min_confidence": max(0.0, min(100.0, min_confidence)),
        "require_backtest_ok": require_backtest_ok,
        "funding_cap": max(0.0, funding_cap),
        "hybrid_arena_match_mode": hybrid_arena or "gate_only",
        "min_tf_aligned": max(2, min(4, min_tf_aligned)),
        "quant_veto": quant_veto,
    }


def _trend_to_direction(trend: str) -> str:
    t = str(trend or "").strip().lower()
    if not t or t == "neutral":
        return "neutral"
    if "bull" in t:
        return "bullish"
    if "bear" in t:
        return "bearish"
    return "neutral"


def collect_timeframe_directions(market_data: Dict[str, Any]) -> Dict[str, str]:
    """与 LLM 信号分析页 kline 标签同源：15m/1h/4h/1d trend → bullish|bearish|neutral。"""
    kline = market_data.get("kline") if isinstance(market_data, dict) else {}
    if not isinstance(kline, dict):
        kline = {}
    out: Dict[str, str] = {}
    for tf_key, lbl in _MTF_SPECS:
        sig = kline.get(tf_key) if isinstance(kline.get(tf_key), dict) else {}
        raw_trend = str(sig.get("trend") or "")
        out[lbl] = _trend_to_direction(raw_trend)
    return out


def _format_tf_snapshot(tf_dirs: Dict[str, str]) -> str:
    parts: List[str] = []
    for _, lbl in _MTF_SPECS:
        d = tf_dirs.get(lbl, "neutral")
        if d == "neutral":
            continue
        trend_key = "bullish" if d == "bullish" else "bearish"
        parts.append(f"{lbl}:{_TREND_CN.get(trend_key, d)}")
    return " · ".join(parts) if parts else "无周期趋势"


def resolve_mtf_structure_direction(
    market_data: Dict[str, Any],
    result: SignalOutput,
    gate_opts: Dict[str, Any],
) -> Tuple[str, str, Dict[str, Any]]:
    """G1：15m+1h+4h+1d 四周期同向 + LLM 为 BUY/SELL + 置信度达标。"""
    tf_dirs = collect_timeframe_directions(market_data)
    min_aligned = int(gate_opts.get("min_tf_aligned") or len(_REQUIRED_TF_LABELS))

    meta: Dict[str, Any] = {
        "timeframeDirections": tf_dirs,
        "alignedTimeframes": [],
        "opposingTimeframes": [],
    }

    missing: List[str] = []
    for lbl in _REQUIRED_TF_LABELS:
        if tf_dirs.get(lbl, "neutral") not in ("bullish", "bearish"):
            missing.append(lbl)
    if missing:
        return (
            "neutral",
            f"四周期须均有趋势，未满足: {','.join(missing)}（{_format_tf_snapshot(tf_dirs)}）",
            meta,
        )

    directions = {tf_dirs[lbl] for lbl in _REQUIRED_TF_LABELS}
    if len(directions) != 1:
        conflict = " · ".join(
            f"{lbl}={'多' if tf_dirs[lbl] == 'bullish' else '空'}" for lbl in _REQUIRED_TF_LABELS
        )
        return "neutral", f"四周期方向不一致: {conflict}", meta

    direction = directions.pop()
    meta["alignedTimeframes"] = list(_REQUIRED_TF_LABELS)

    signal = str(result.signal or "NEUTRAL").upper()
    if direction == "bullish" and signal != "BUY":
        return "neutral", f"四周期偏多，但 LLM 综合信号为 {signal}（实盘需 BUY）", meta
    if direction == "bearish" and signal != "SELL":
        return "neutral", f"四周期偏空，但 LLM 综合信号为 {signal}（实盘需 SELL）", meta

    conf = float(result.confidence or 0)
    min_conf = float(gate_opts.get("min_confidence") or 50)
    if conf < min_conf:
        return "neutral", f"LLM 置信度 {conf:.0f}% < 门槛 {min_conf:.0f}%", meta

    if len(meta["alignedTimeframes"]) < min_aligned:
        return "neutral", f"同向周期不足（需≥{min_aligned}）", meta

    return (
        direction,
        f"四周期同向 + LLM {signal}（{_format_tf_snapshot(tf_dirs)}）",
        meta,
    )


def resolve_llm_flow_direction(
    result: SignalOutput,
    *,
    expected_direction: str,
) -> Tuple[str, str]:
    """G1 延续：LLM 技术/盘面/倾向不得两侧都反对四周期方向。"""
    tech = resolve_technical_gate_direction(result)
    pos = resolve_positioning_gate_direction(result)
    bias = _direction_from_text(getattr(result.analysis, "bias", None) or "")

    def _opposes(d: str) -> bool:
        return d in ("bullish", "bearish") and d != expected_direction

    opposes = [name for name, d in (("技术", tech), ("盘面", pos), ("倾向", bias)) if _opposes(d)]
    if len(opposes) >= 2:
        return "neutral", f"LLM {'/'.join(opposes)} 与四周期方向冲突"

    supporters = [d for d in (tech, pos, bias) if d == expected_direction]
    if supporters:
        note = f"LLM 因子支持{('做多' if expected_direction == 'bullish' else '做空')}"
    elif tech == "neutral" and pos == "neutral":
        note = "LLM 技术/盘面中性，以四周期+综合信号为准"
    else:
        return "neutral", f"LLM 因子未确认方向（技术={tech}，盘面={pos}）"

    return expected_direction, note


def resolve_quant_gate_confirm(
    expected_direction: str,
    quant_factors: Dict[str, Any],
    *,
    quant_min_aggregate: float,
    gate_opts: Dict[str, Any],
) -> Tuple[bool, str, str, str]:
    """G2 量化软否决 → (通过, 维度方向, quantStatus, note)。"""
    from web.api.quant_factors_bridge import quant_gate_direction

    if not gate_opts.get("quant_veto", True):
        return True, expected_direction, "skipped", "量化软否决已关闭"

    quant = quant_factors if isinstance(quant_factors, dict) else {}
    if not quant.get("available"):
        return True, expected_direction, "skipped", "量化不可用，未参与门禁"

    q_dir, q_note = quant_gate_direction(quant, min_aggregate=quant_min_aggregate)
    agg = abs(_num(quant.get("aggregateScore"), 0.0))
    expected_side = "buy" if expected_direction == "bullish" else "sell"
    side = quant.get("side")

    if q_dir == expected_direction or side == expected_side:
        return True, expected_direction, "confirm", q_note
    if q_dir == "neutral" or not side:
        return True, expected_direction, "neutral", q_note or f"量化中性区（±{quant_min_aggregate}）"
    if agg >= quant_min_aggregate:
        return False, "neutral", "veto", f"量化否决: {q_note}"
    return True, expected_direction, "neutral", q_note


def _num(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return default if n != n else n
    except (TypeError, ValueError):
        return default


def _signal_bias(signal: str) -> str:
    s = str(signal or "").upper()
    if s in {"BUY", "WEAK_BUY"}:
        return "bullish"
    if s in {"SELL", "WEAK_SELL"}:
        return "bearish"
    return "neutral"


def _direction_from_factor(block: Any) -> str:
    value = str(getattr(block, "direction", "") or "").strip().lower()
    if value in {"bullish", "bearish", "neutral"}:
        return value
    if "多" in value:
        return "bullish"
    if "空" in value:
        return "bearish"
    if "中" in value:
        return "neutral"
    return "neutral"


def _direction_from_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"bullish", "bearish", "neutral"}:
        return text
    if "多" in text:
        return "bullish"
    if "空" in text:
        return "bearish"
    if "中" in text:
        return "neutral"
    return "neutral"


def resolve_technical_gate_direction(result: SignalOutput) -> str:
    """LLM 技术块方向（展示/交叉验证）。"""
    refs = result.debug.sourceRefs or {}
    if refs.get("gateTechnicalFromLlm"):
        d = str(refs.get("gateTechnicalDirection") or "").lower()
        if d in ("bullish", "bearish"):
            return d
    d = _direction_from_factor(result.factors.technical)
    if d in ("bullish", "bearish"):
        return d
    bias = _direction_from_text(getattr(result.analysis, "bias", None) or "")
    if bias in ("bullish", "bearish"):
        return bias
    sig = _signal_bias(result.signal)
    return sig if sig in ("bullish", "bearish") else "neutral"


def resolve_positioning_gate_direction(result: SignalOutput) -> str:
    refs = result.debug.sourceRefs or {}
    if refs.get("gatePositioningFromLlm"):
        d = str(refs.get("gatePositioningDirection") or "").lower()
        if d in ("bullish", "bearish"):
            return d
    d = _direction_from_factor(result.factors.positioning)
    return d if d in ("bullish", "bearish", "neutral") else "neutral"


def _resolve_structure_direction(
    market_data: Dict[str, Any],
    result: SignalOutput,
) -> Tuple[str, str]:
    """规则价量结构：多周期趋势 + K 线得分；与 LLM 技术块交叉验证。"""
    from web.api.signal_analyzer import score_kline, score_multi_tf_alignment

    data = market_data if isinstance(market_data, dict) else {}
    mtf_score, mtf_reasons = score_multi_tf_alignment(data)
    k_score, k_reasons = score_kline(data)
    combined = mtf_score + k_score * 0.35
    hints = (mtf_reasons + k_reasons)[:3]

    llm_tech = resolve_technical_gate_direction(result)
    if combined >= 4:
        direction = "bullish"
    elif combined <= -4:
        direction = "bearish"
    else:
        direction = "neutral"

    if direction in ("bullish", "bearish") and llm_tech in ("bullish", "bearish"):
        if llm_tech != direction:
            return (
                "neutral",
                f"规则结构={direction} 与 LLM 技术={llm_tech} 冲突",
            )

    deriv = data.get("derivatives") or {}
    fr = deriv.get("fundingRate") or deriv.get("funding") or {}
    if isinstance(fr, dict):
        rate = _num(fr.get("fundingRate") or fr.get("rate"), 0.0)
        opts = resolve_entry_gate_options()
        cap = opts["funding_cap"]
        if direction == "bullish" and rate > cap:
            return "neutral", f"资金费率 {rate:.4%} 偏高，不利做多"
        if direction == "bearish" and rate < -cap:
            return "neutral", f"资金费率 {rate:.4%} 偏低，不利做空"

    hint = hints[0] if hints else "多周期价量结构"
    return direction, hint


def _resolve_flow_direction(
    result: SignalOutput,
    *,
    quant_factors: Dict[str, Any],
    quant_min_aggregate: float,
    require_quant: bool,
) -> Tuple[str, str]:
    """资金维：量化综合分 + 盘面/情绪同向。"""
    from web.api.quant_factors_bridge import quant_gate_direction

    pos_dir = resolve_positioning_gate_direction(result)
    quant = quant_factors if isinstance(quant_factors, dict) else {}
    q_dir, quant_note = quant_gate_direction(quant, min_aggregate=quant_min_aggregate)

    if require_quant and not quant.get("available"):
        return "neutral", quant_note or "量化因子不可用"

    if require_quant:
        if q_dir == "neutral" or pos_dir == "neutral":
            return "neutral", quant_note or "量化或盘面为中性"
        if q_dir != pos_dir:
            return (
                "neutral",
                f"量化={q_dir} 与 盘面={pos_dir} 不一致",
            )
        return q_dir, f"量化+盘面同向（{quant_note or pos_dir}）"

    if pos_dir in ("bullish", "bearish"):
        return pos_dir, "量化已关闭，以盘面/情绪为准"
    return "neutral", "盘面/情绪中性"


def evaluate_entry_gate_alignment(
    result: SignalOutput,
    *,
    market_data: Optional[Dict[str, Any]] = None,
    news_meta: Optional[Dict[str, Any]] = None,
    quant_factors: Optional[Dict[str, Any]] = None,
    quant_min_aggregate: Optional[float] = None,
    require_quant_in_gate: bool = True,
) -> Dict[str, Any]:
    """入场门禁对齐；返回 fiveSignalAlignment 兼容结构。"""
    from web.api.quant_factors_bridge import quant_gate_direction, resolve_quant_factors_options

    data = market_data if isinstance(market_data, dict) else {}
    meta = news_meta if isinstance(news_meta, dict) else {}
    gate_hours = int(meta.get("gateHours") or 12)
    q_opts = resolve_quant_factors_options()
    min_agg = float(
        quant_min_aggregate if quant_min_aggregate is not None else q_opts["min_aggregate"]
    )
    gate_opts = resolve_entry_gate_options()
    mode = gate_opts["mode"]
    quant = quant_factors if isinstance(quant_factors, dict) else {}
    require_quant = bool(
        mode == "rule_primary" and q_opts["enabled"] and require_quant_in_gate
    )
    mtf_meta: Dict[str, Any] = {}
    quant_status = "skipped"
    quant_confirm = True

    gate_keys: List[str] = (
        list(GATE_DIMENSION_KEYS) if mode == "llm_mtf" else list(GATE_DIMENSION_KEYS_RULE)
    )
    gate_model = GATE_MODEL_LLM_MTF if mode == "llm_mtf" else GATE_MODEL_RULE

    q_dir_display = "neutral"
    quant_note = ""

    if mode == "llm_mtf":
        s_dir, s_note, mtf_meta = resolve_mtf_structure_direction(data, result, gate_opts)
        f_dir, f_note = (
            ("neutral", "四周期未通过，跳过 LLM 因子校验")
            if s_dir == "neutral"
            else resolve_llm_flow_direction(result, expected_direction=s_dir)
        )
        if s_dir == "neutral":
            quant_ok, q_dim, quant_status, quant_note = False, "neutral", "skipped", ""
        else:
            quant_ok, q_dim, quant_status, quant_note = resolve_quant_gate_confirm(
                s_dir,
                quant,
                quant_min_aggregate=min_agg,
                gate_opts=gate_opts,
            )
            q_dir_display = q_dim if quant_ok else "neutral"
    else:
        s_dir, s_note = _resolve_structure_direction(data, result)
        f_dir, f_note = _resolve_flow_direction(
            result,
            quant_factors=quant,
            quant_min_aggregate=min_agg,
            require_quant=require_quant,
        )
        quant_ok = f_dir != "neutral" or s_dir == "neutral"
        q_dir_display, quant_note = (
            quant_gate_direction(quant, min_aggregate=min_agg)
            if quant.get("available") or require_quant
            else ("neutral", "")
        )

    from web.api.executable_gate import evaluate_executable_gate

    exec_ok, exec_note = evaluate_executable_gate(
        result,
        data,
        min_rr=gate_opts["min_rr"],
        require_backtest_ok=gate_opts["require_backtest_ok"],
    )
    exec_dir = "bullish" if exec_ok else "neutral"

    dimensions: Dict[str, str] = {
        "structure": s_dir,
        "flow": f_dir,
        "executable": exec_dir,
        "technical": resolve_technical_gate_direction(result),
        "positioning": resolve_positioning_gate_direction(result),
        "onchain": _direction_from_factor(result.factors.onchain),
    }
    if mode == "llm_mtf":
        dimensions["quant"] = q_dir_display
    elif quant.get("available") or require_quant:
        dimensions["quant"], quant_note = quant_gate_direction(quant, min_aggregate=min_agg)

    notes = {
        "structure": s_note,
        "flow": f_note,
        "executable": exec_note,
        "quant": quant_note,
    }

    base_extra: Dict[str, Any] = {
        "dimensions": dimensions,
        "gateDimensions": gate_keys,
        "gateModel": gate_model,
        "gateMode": mode,
        "gateNotes": notes,
        "structureNote": s_note,
        "flowNote": f_note,
        "executableNote": exec_note,
        "quantNote": quant_note,
        "quantStatus": quant_status,
        "quantConfirm": quant_confirm if mode != "llm_mtf" else quant_ok,
        "technicalFromLlm": bool((result.debug.sourceRefs or {}).get("gateTechnicalFromLlm")),
        "positioningFromLlm": bool((result.debug.sourceRefs or {}).get("gatePositioningFromLlm")),
        "consensusDisplayOnly": True,
        "onchainDisplayOnly": True,
        "referenceOnlyKeys": ["onchain", "consensus", "technical", "positioning"],
        "newsGateHours": gate_hours,
        "newsFreshCount": int(meta.get("freshCount") or 0),
        "newsTotalCount": int(meta.get("totalCount") or 0),
        "minRiskReward": gate_opts["min_rr"],
        **mtf_meta,
    }

    def _fail(reason: str, *, failed_gate: str, direction: str = "neutral") -> Dict[str, Any]:
        return {
            "aligned": False,
            "direction": direction,
            "side": None,
            "reason": reason,
            **base_extra,
            "failedGate": failed_gate,
        }

    if mode == "llm_mtf":
        if s_dir == "neutral":
            return _fail(s_note, failed_gate="structure")
        if f_dir == "neutral":
            return _fail(f_note, failed_gate="flow", direction=s_dir)
        if not quant_ok:
            return _fail(quant_note, failed_gate="quant", direction=s_dir)

    gate_core = [dimensions[k] for k in ("structure", "flow") if k in dimensions]
    if mode == "llm_mtf":
        gate_core = [s_dir, f_dir]

    if not exec_ok:
        return _fail(exec_note, failed_gate="executable", direction=gate_core[0] if gate_core else "neutral")

    if mode != "llm_mtf":
        if any(d == "neutral" for d in gate_core):
            fail_reason = s_note if s_dir == "neutral" else f_note
            return _fail(fail_reason or "门禁维度中性", failed_gate="structure")
        if len(set(gate_core)) != 1:
            return _fail("结构/资金方向不一致", failed_gate="flow")

    direction = gate_core[0]
    side = "buy" if direction == "bullish" else "sell"

    return {
        "aligned": True,
        "direction": direction,
        "side": side,
        "reason": "四周期、LLM 与量化一致，计划可执行，允许合约入场",
        **base_extra,
    }


def evaluate_five_signal_alignment(
    result: SignalOutput,
    *,
    news_meta: Optional[Dict[str, Any]] = None,
    quant_factors: Optional[Dict[str, Any]] = None,
    quant_min_aggregate: Optional[float] = None,
    require_quant_in_gate: bool = True,
    market_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """兼容旧名；请使用 evaluate_entry_gate_alignment。"""
    return evaluate_entry_gate_alignment(
        result,
        market_data=market_data,
        news_meta=news_meta,
        quant_factors=quant_factors,
        quant_min_aggregate=quant_min_aggregate,
        require_quant_in_gate=require_quant_in_gate,
    )


def format_alignment_dimensions_cn(alignment: Dict[str, Any]) -> str:
    dims = alignment.get("dimensions") or {}
    gate_keys = alignment.get("gateDimensions") or list(GATE_DIMENSION_KEYS)
    _DIR_LABEL = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}
    parts = []
    for key in gate_keys:
        raw = dims.get(key)
        if not raw:
            continue
        parts.append(f"{_DIM_CN_GATE.get(key, key)}{_DIR_LABEL.get(str(raw).lower(), raw)}")
    return " · ".join(parts)
