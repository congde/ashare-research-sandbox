# -*- coding: utf-8 -*-
"""Bridge src/factors FactorPipeline into live trading / LLM signal flows."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 45.0
_DEFAULT_MIN_AGGREGATE = 0.12
_MAX_TOP_FACTORS = 12
_MAX_TRACE_LINES = 3

_pipeline = None
_pipeline_lock = asyncio.Lock()
_resolve_lock = asyncio.Lock()


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "0", "no", "off", "")


def resolve_quant_factors_options() -> Dict[str, Any]:
    """Read quant factor knobs from web.config and env (LIVE_QUANT_*)."""
    enabled = _coerce_bool(os.getenv("LIVE_QUANT_FACTORS_ENABLED"), True)
    market = str(os.getenv("LIVE_QUANT_FACTORS_MARKET") or "contract").strip().lower()
    timeout_s = float(os.getenv("LIVE_QUANT_FACTORS_TIMEOUT_S") or _DEFAULT_TIMEOUT_S)
    min_aggregate = float(os.getenv("LIVE_QUANT_FACTORS_MIN_AGGREGATE") or _DEFAULT_MIN_AGGREGATE)
    require_align = _coerce_bool(os.getenv("LIVE_QUANT_FACTORS_REQUIRE_ALIGN"), False)

    try:
        from web.config import config

        if getattr(config, "live_quant_factors_enabled", None) is not None:
            enabled = _coerce_bool(config.live_quant_factors_enabled, enabled)
        if getattr(config, "live_quant_factors_market", None):
            market = str(config.live_quant_factors_market).strip().lower()
        if getattr(config, "live_quant_factors_timeout_s", None) is not None:
            timeout_s = float(config.live_quant_factors_timeout_s)
        if getattr(config, "live_quant_factors_min_aggregate", None) is not None:
            min_aggregate = float(config.live_quant_factors_min_aggregate)
        if getattr(config, "live_quant_factors_require_align", None) is not None:
            require_align = _coerce_bool(config.live_quant_factors_require_align, require_align)
    except Exception:
        pass

    return {
        "enabled": enabled,
        "market": market if market in {"spot", "contract"} else "contract",
        "timeout_s": max(5.0, timeout_s),
        "min_aggregate": max(0.01, min(1.0, min_aggregate)),
        "require_align": require_align,
    }


def _direction_label(direction: Any) -> str:
    raw = str(direction or "").lower()
    if "bull" in raw:
        return "偏多"
    if "bear" in raw:
        return "偏空"
    if raw in {"neutral", "inconclusive", ""}:
        return "中性"
    return raw


def _side_from_aggregate(aggregate_score: float, *, min_aggregate: float) -> Optional[str]:
    if aggregate_score >= min_aggregate:
        return "buy"
    if aggregate_score <= -min_aggregate:
        return "sell"
    return None


def compact_factor_result(result: Any) -> Dict[str, Any]:
    trace = getattr(result, "trace", None)
    evidence = []
    if trace is not None:
        for link in (getattr(trace, "evidence_chain", None) or [])[:_MAX_TRACE_LINES]:
            evidence.append(getattr(link, "interpretation", "") or getattr(link, "data_point", ""))
    return {
        "name": getattr(result, "factor_name", ""),
        "displayName": getattr(result, "display_name", "") or getattr(result, "factor_name", ""),
        "category": str(getattr(result, "category", "") or ""),
        "tier": str(getattr(result, "factor_tier", "") or ""),
        "direction": _direction_label(getattr(result, "signal_direction", "")),
        "score": round(float(getattr(result, "normalized_score", 0) or 0), 4),
        "confidence": round(float(getattr(result, "confidence", 0) or 0), 3),
        "weight": round(float(getattr(result, "weight", 0) or 0), 3),
        "conclusion": (getattr(trace, "conclusion", "") or "")[:240] if trace else "",
        "evidence": [e for e in evidence if e],
    }


def compact_factor_bundle(
    bundle: Any,
    *,
    min_aggregate: float = _DEFAULT_MIN_AGGREGATE,
) -> Dict[str, Any]:
    """Serialize FactorBundle for API / LLM / live logs."""
    errors = list(getattr(bundle, "errors", None) or [])
    all_results = list(getattr(bundle, "all_results", None) or [])
    if errors and not all_results:
        first = str(errors[0]) if errors else "no_results"
        return {"available": False, "errors": errors[:5], "reason": first}

    ranked = sorted(
        [r for r in all_results if float(getattr(r, "confidence", 0) or 0) > 0],
        key=lambda r: abs(float(getattr(r, "normalized_score", 0) or 0))
        * max(float(getattr(r, "weight", 0) or 0), 0.01),
        reverse=True,
    )
    aggregate = float(getattr(bundle, "aggregate_score", 0) or 0)
    cross = [
        {
            "name": getattr(c, "cross_name", ""),
            "direction": _direction_label(getattr(c, "signal_direction", "")),
            "score": round(float(getattr(c, "normalized_score", 0) or 0), 4),
            "confidence": round(float(getattr(c, "confidence", 0) or 0), 3),
        }
        for c in (getattr(bundle, "cross_factors", None) or [])
    ]

    return {
        "available": True,
        "symbol": getattr(bundle, "symbol", "") or "",
        "vsTokenId": getattr(bundle, "vs_token_id", "") or "",
        "aggregateScore": round(aggregate, 4),
        "side": _side_from_aggregate(aggregate, min_aggregate=min_aggregate),
        "overallCompleteness": round(float(getattr(bundle, "overall_completeness", 0) or 0), 3),
        "tier1Count": len(getattr(bundle, "tier1_results", None) or []),
        "tier2Count": len(getattr(bundle, "tier2_results", None) or []),
        "topFactors": [compact_factor_result(r) for r in ranked[:_MAX_TOP_FACTORS]],
        "crossFactors": cross[:6],
        "errors": errors[:3],
    }


def format_quant_factors_for_llm(compact: Dict[str, Any]) -> str:
    if not compact.get("available"):
        reason = compact.get("reason") or (compact.get("errors") or ["不可用"])
        if isinstance(reason, list):
            reason = "; ".join(str(x) for x in reason[:3])
        return f"量化因子管线: 不可用 ({reason})"

    lines = [
        f"加权综合得分: {compact.get('aggregateScore', 0):+.3f}（阈值 ±{compact.get('minAggregate', _DEFAULT_MIN_AGGREGATE)}）",
        f"建议方向: {compact.get('side') or '中性/观望'}",
        f"数据完整度: {float(compact.get('overallCompleteness', 0)) * 100:.0f}%",
        f"Tier1/Tier2 因子数: {compact.get('tier1Count', 0)}/{compact.get('tier2Count', 0)}",
    ]
    for item in compact.get("topFactors") or []:
        name = item.get("displayName") or item.get("name")
        lines.append(
            f"- {name}: {item.get('direction')} score={item.get('score'):+.3f} "
            f"conf={item.get('confidence')} — {(item.get('conclusion') or '')[:120]}"
        )
    cross = compact.get("crossFactors") or []
    if cross:
        lines.append("交叉因子:")
        for item in cross:
            lines.append(f"  · {item.get('name')}: {item.get('direction')} ({item.get('score'):+.3f})")
    return "\n".join(lines)


async def _build_pipeline(opts: Dict[str, Any]):
    from factors import FactorPipeline, PipelineConfig
    from libs.kucoin_openapi import KuCoinClient
    from libs.valuescan.client import ValueScanClient

    client = ValueScanClient.from_env()
    kucoin = KuCoinClient()
    if opts["market"] == "spot":
        config = PipelineConfig.for_spot()
    else:
        config = PipelineConfig.for_contract()
    return FactorPipeline(client, config, kucoin=kucoin)


async def _get_pipeline(opts: Dict[str, Any]):
    global _pipeline
    async with _pipeline_lock:
        if _pipeline is None:
            _pipeline = await _build_pipeline(opts)
        return _pipeline


async def _resolve_vs_token_id(symbol: str) -> Optional[int]:
    """Resolve symbol → vsTokenId using dashboard cache; retry on rate limits."""
    sym = str(symbol or "").upper().split("-")[0].split("/")[0]
    if not sym:
        return None

    async with _resolve_lock:
        for attempt in range(3):
            try:
                from web.api import valuescan_service as vs

                vs_id = await vs.get_vs_token_id(sym)
                if vs_id:
                    return int(vs_id)
            except Exception as exc:
                logger.warning(
                    "valuescan_service token resolve failed for %s (attempt %d): %s",
                    sym,
                    attempt + 1,
                    exc,
                )
            if attempt < 2:
                await asyncio.sleep(1.5 * (2**attempt))

    try:
        from libs.valuescan.client import ValueScanClient

        client = ValueScanClient.from_env()
        try:
            vs_id, _ = await client.resolve_symbol(sym)
            return int(vs_id) if vs_id else None
        finally:
            await client.close()
    except Exception as exc:
        logger.warning("ValueScanClient token resolve failed for %s: %s", sym, exc)
        return None


async def fetch_quant_factors_for_symbol(
    symbol: str,
    *,
    market: Optional[str] = None,
    timeout_s: Optional[float] = None,
    min_aggregate: Optional[float] = None,
) -> Dict[str, Any]:
    """Run FactorPipeline for one symbol; never raises."""
    opts = resolve_quant_factors_options()
    if market:
        opts = {**opts, "market": market}
    if not opts["enabled"]:
        return {"available": False, "reason": "disabled"}

    sym = str(symbol or "").upper().split("-")[0].split("/")[0]
    if not sym:
        return {"available": False, "reason": "empty_symbol"}

    timeout = timeout_s if timeout_s is not None else opts["timeout_s"]
    min_agg = min_aggregate if min_aggregate is not None else opts["min_aggregate"]

    try:
        vs_id = await _resolve_vs_token_id(sym)
        if not vs_id:
            return {
                "available": False,
                "reason": f"无法解析代币 {sym}（ValueScan 限流或未收录）",
                "symbol": sym,
            }

        pipeline = await _get_pipeline(opts)
        bundle = await asyncio.wait_for(pipeline.compute_all(vs_id), timeout=timeout)
        compact = compact_factor_bundle(bundle, min_aggregate=min_agg)
        compact["minAggregate"] = min_agg
        return compact
    except asyncio.TimeoutError:
        logger.warning("quant factors timeout for %s (%.0fs)", sym, timeout)
        return {"available": False, "reason": "timeout", "symbol": sym}
    except Exception as exc:
        logger.warning("quant factors failed for %s: %s", sym, exc)
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}", "symbol": sym}


def quant_gate_direction(
    quant: Dict[str, Any],
    *,
    min_aggregate: float,
) -> Tuple[str, str]:
    """Map quant bundle to gate direction: bullish | bearish | neutral + note."""
    if not quant.get("available"):
        reason = quant.get("reason") or "unknown"
        if quant.get("errors"):
            reason = "; ".join(str(e) for e in (quant.get("errors") or [])[:2])
        return "neutral", f"量化因子不可用（{reason}）"

    aggregate = float(quant.get("aggregateScore") or 0)
    side = quant.get("side") or _side_from_aggregate(aggregate, min_aggregate=min_aggregate)
    if side == "buy":
        return "bullish", f"量化综合 {aggregate:+.3f}（≥+{min_aggregate}）"
    if side == "sell":
        return "bearish", f"量化综合 {aggregate:+.3f}（≤-{min_aggregate}）"
    return "neutral", f"量化综合 {aggregate:+.3f} 处于中性区（±{min_aggregate}）"


def evaluate_quant_alignment(
    llm_side: Optional[str],
    quant: Dict[str, Any],
    *,
    require_align: bool,
    min_aggregate: float,
) -> Tuple[bool, str]:
    """Check LLM gate side against quant aggregate; skip if quant unavailable."""
    if not require_align or not llm_side:
        return True, ""
    if not quant.get("available"):
        return False, f"量化因子不可用（{quant.get('reason') or 'unknown'}），拒绝开仓"

    q_side = quant.get("side") or _side_from_aggregate(
        float(quant.get("aggregateScore") or 0),
        min_aggregate=min_aggregate,
    )
    if not q_side:
        score = float(quant.get("aggregateScore") or 0)
        return False, f"量化综合得分 {score:+.3f} 处于中性区（阈值 ±{min_aggregate}）"
    if q_side != llm_side:
        return False, f"量化因子建议 {q_side} 与入场门禁 {llm_side} 不一致"
    return True, f"量化因子与入场门禁一致 ({q_side}, 得分 {float(quant.get('aggregateScore') or 0):+.3f})"


def reset_pipeline_cache() -> None:
    """Test helper: clear cached FactorPipeline."""
    global _pipeline
    _pipeline = None
