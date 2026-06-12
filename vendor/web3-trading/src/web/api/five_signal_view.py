# -*- coding: utf-8 -*-
"""入场门禁展示：多周期 + LLM 因子 + 量化 + 可执行（四步）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from web.api.entry_gate import (
    GATE_DIMENSION_KEYS,
    _DIM_CN_GATE,
    format_alignment_dimensions_cn,
)

_GATE_SIGNAL_META = (
    ("structure", "多周期"),
    ("flow", "LLM因子"),
    ("quant", "量化"),
    ("executable", "可执行"),
)
_DIR_LABEL = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}


def _append_signal_item(
    items: List[Dict[str, Any]],
    *,
    key: str,
    name: str,
    direction: str,
    score: Optional[float],
    hint: str,
    data_status: str,
    participates_in_gate: bool,
) -> None:
    items.append({
        "key": key,
        "name": name,
        "direction": direction,
        "label": _DIR_LABEL.get(direction, direction),
        "score": score,
        "hint": hint,
        "dataStatus": data_status,
        "participatesInGate": participates_in_gate,
        "displayOnly": not participates_in_gate,
    })


def build_entry_gate_list(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """入场门禁四步（兼容字段名 fiveSignals）。"""
    alignment = analysis.get("fiveSignalAlignment") or analysis.get("entryGateAlignment") or {}
    dims = alignment.get("dimensions") or {}
    gate_keys = set(alignment.get("gateDimensions") or list(GATE_DIMENSION_KEYS))
    gate_notes = alignment.get("gateNotes") or {}
    quant = analysis.get("quantFactors") or {}
    dq = analysis.get("dataQuality") or {}
    source_status = dq.get("sourceStatus") or dq.get("source_status") or {}
    src_hint = {"missing": "数据源未返回", "partial": "数据不完整"}
    key_source = {
        "structure": "kline",
        "flow": "quantFactors",
        "executable": "tradePlan",
        "technical": "kline",
        "quant": "quantFactors",
        "positioning": "valuescan",
        "onchain": "valuescanChain",
        "consensus": "news",
    }
    items: List[Dict[str, Any]] = []

    for key, name in _GATE_SIGNAL_META:
        if key not in gate_keys:
            continue
        direction = str(dims.get(key) or "neutral").lower()
        score = None
        hint = str(gate_notes.get(key) or alignment.get(f"{key}Note") or "")[:80]
        if key == "executable":
            if direction == "bullish":
                hint = hint or "计划与准备度可执行"
            else:
                hint = hint or alignment.get("executableNote") or "未满足可执行条件"
        elif key == "flow":
            hint = hint or str(alignment.get("flowNote") or "")[:80]
        elif key == "quant":
            if quant.get("available"):
                try:
                    score = round(float(quant.get("aggregateScore") or 0) * 100, 1)
                except (TypeError, ValueError):
                    score = None
            status = str(alignment.get("quantStatus") or "")
            if status in ("confirm", "neutral", "skipped", "veto") and not hint:
                status_cn = {
                    "confirm": "已确认",
                    "neutral": "中性区",
                    "skipped": "未参与",
                    "veto": "已否决",
                }.get(status, status)
                hint = status_cn
            hint = hint or str(alignment.get("quantNote") or "量化管线")[:80]
        elif key == "structure":
            tf_dirs = alignment.get("timeframeDirections") or {}
            if isinstance(tf_dirs, dict) and tf_dirs:
                parts = []
                for lbl in ("15m", "1h", "4h", "1d"):
                    d = str(tf_dirs.get(lbl) or "neutral").lower()
                    if d == "neutral":
                        continue
                    cn = {"bullish": "多", "bearish": "空"}.get(d, d)
                    parts.append(f"{lbl}:{cn}")
                if parts:
                    hint = hint or " · ".join(parts)
            hint = hint or str(alignment.get("structureNote") or "K 线多周期趋势")[:80]
        if not hint:
            st = str(source_status.get(key_source.get(key, key)) or "").lower()
            if st in src_hint:
                hint = src_hint[st]
        _append_signal_item(
            items,
            key=key,
            name=name,
            direction=direction,
            score=score,
            hint=hint,
            data_status=str(source_status.get(key_source.get(key, key)) or ""),
            participates_in_gate=True,
        )

    return items


def build_five_signals_list(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """兼容旧 API 名称。"""
    return build_entry_gate_list(analysis)


def analysis_view_from_signal_result(
    result: Any,
    aggregated: Dict[str, Any],
    alignment: Dict[str, Any],
) -> Dict[str, Any]:
    analysis_dump = result.analysis.model_dump() if result.analysis else {}
    return {
        "symbol": aggregated.get("symbol"),
        "signal": result.signal,
        "confidence": result.confidence,
        "bias": analysis_dump.get("bias"),
        "consensus": analysis_dump.get("consensus") or {},
        "factors": result.factors.model_dump() if result.factors else {},
        "quantFactors": aggregated.get("quantFactors") or {},
        "fiveSignalAlignment": alignment,
        "entryGateAlignment": alignment,
        "dataQuality": result.dataQuality.model_dump() if result.dataQuality else {},
        "newsCount": len(aggregated.get("news") or []),
        "newsMeta": aggregated.get("newsMeta") or {},
        "news": aggregated.get("news"),
        "onchain": aggregated.get("onchain"),
        "onchainMetrics": aggregated.get("onchainMetrics"),
        "valuescan": aggregated.get("valuescan"),
        "valuescanChain": aggregated.get("valuescanChain"),
        "executionReadiness": analysis_dump.get("executionReadiness"),
        "tradePlan": result.tradePlan.model_dump() if result.tradePlan else {},
        "strategyBacktests": aggregated.get("strategyBacktests") or {},
    }
