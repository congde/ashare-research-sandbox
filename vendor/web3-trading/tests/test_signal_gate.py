# -*- coding: utf-8 -*-
"""入场门禁：四周期 + LLM 因子 + 量化软否决 + 可执行。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-test")

from web.config import init_config

init_config("conf/default.yaml")

from web.api.entry_gate import (
    collect_timeframe_directions,
    evaluate_entry_gate_alignment,
    resolve_entry_gate_options,
    resolve_quant_gate_confirm,
)
from web.api.five_signal_view import build_entry_gate_list, format_alignment_dimensions_cn
from web.api.llm_signal_analyzer import (
    _apply_unanimous_factor_rule,
    _snapshot_llm_gate_factor_directions,
)
from web.api.quant_factors_bridge import quant_gate_direction
from web.api.signal_schema import (
    AnalysisBlock,
    DebugBlock,
    ExecutionPlan,
    FactorBlock,
    FactorsBlock,
    SignalOutput,
    TradePlan,
)


def _market_bullish() -> dict:
    return {
        "kline": {
            "15min": {"trend": "weak_bullish"},
            "1hour": {"trend": "bullish"},
            "4hour": {"trend": "bullish"},
            "1day": {"trend": "bullish"},
        },
        "derivatives": {"fundingRate": {"fundingRate": 0.0001}},
        "strategyBacktests": {"available": False},
    }


def _market_mixed_bearish_direction() -> dict:
    """截图型：4h/1d 空头，15m/1h 短线偏多。"""
    return {
        "kline": {
            "15min": {"trend": "weak_bullish"},
            "1hour": {"trend": "weak_bullish"},
            "4hour": {"trend": "bearish"},
            "1day": {"trend": "bearish"},
        },
        "strategyBacktests": {"available": False},
    }


def _market_all_bearish() -> dict:
    return {
        "kline": {
            "15min": {"trend": "weak_bearish"},
            "1hour": {"trend": "bearish"},
            "4hour": {"trend": "bearish"},
            "1day": {"trend": "bearish"},
        },
        "strategyBacktests": {"available": False},
    }


def _make_result(
    *,
    tech_dir: str = "bullish",
    pos_dir: str = "bullish",
    signal: str = "BUY",
    bias: str = "bullish",
    readiness: str = "ready",
    rr: float = 2.0,
    confidence: float = 70,
) -> SignalOutput:
    tech = FactorBlock(
        direction=tech_dir,
        score=10,
        confidence=0.8,
        highlights=["llm tech"],
    )
    pos = FactorBlock(
        direction=pos_dir,
        score=5,
        confidence=0.6,
        highlights=["llm pos"],
    )
    result = SignalOutput(
        signal=signal,
        label="买入",
        score=40,
        confidence=confidence,
        factors=FactorsBlock(
            technical=tech,
            onchain=FactorBlock(),
            news=FactorBlock(),
            positioning=pos,
        ),
        analysis=AnalysisBlock(
            bias=bias,
            executionReadiness=readiness,
            execution=ExecutionPlan(riskReward1=rr),
        ),
        tradePlan=TradePlan(
            entryLow=99,
            entryHigh=101,
            stop=95,
            target1=110,
            target2=120,
        ),
        debug=DebugBlock(sourceRefs={}),
    )
    _snapshot_llm_gate_factor_directions(result)
    return result


def test_quant_gate_direction():
    assert quant_gate_direction(
        {"available": True, "aggregateScore": 0.2, "side": "buy"},
        min_aggregate=0.12,
    )[0] == "bullish"
    direction, note = quant_gate_direction(
        {"available": False, "reason": "timeout"},
        min_aggregate=0.12,
    )
    assert direction == "neutral"
    assert "不可用" in note


def test_collect_timeframe_directions():
    dirs = collect_timeframe_directions(_market_bullish())
    assert dirs["4h"] == "bullish"
    assert dirs["1d"] == "bullish"
    assert dirs["15m"] == "bullish"


def test_entry_gate_pass_llm_mtf():
    quant = {"available": True, "aggregateScore": 0.2, "side": "buy"}
    align = evaluate_entry_gate_alignment(
        _make_result(),
        market_data=_market_bullish(),
        quant_factors=quant,
    )
    assert align["aligned"] is True
    assert align["side"] == "buy"
    assert align.get("gateMode") == "llm_mtf"
    assert set(align.get("alignedTimeframes") or []) == {"15m", "1h", "4h", "1d"}
    assert align.get("quantStatus") == "confirm"


def test_entry_gate_mixed_tf_fails_g1():
    quant = {"available": True, "aggregateScore": -0.2, "side": "sell"}
    align = evaluate_entry_gate_alignment(
        _make_result(
            signal="SELL",
            tech_dir="bearish",
            pos_dir="bearish",
            bias="bearish",
        ),
        market_data=_market_mixed_bearish_direction(),
        quant_factors=quant,
    )
    assert align["aligned"] is False
    assert align["dimensions"]["structure"] == "neutral"
    assert align.get("failedGate") == "structure"
    assert "不一致" in (align.get("reason") or "")


def test_entry_gate_all_bearish_sell_passes():
    quant = {"available": True, "aggregateScore": -0.2, "side": "sell"}
    sell_result = _make_result(
        signal="SELL",
        tech_dir="bearish",
        pos_dir="bearish",
        bias="bearish",
    )
    sell_result.tradePlan = TradePlan(
        entryLow=99,
        entryHigh=101,
        stop=105,
        target1=90,
        target2=85,
    )
    align = evaluate_entry_gate_alignment(
        sell_result,
        market_data=_market_all_bearish(),
        quant_factors=quant,
    )
    assert align["aligned"] is True
    assert align["side"] == "sell"


def test_entry_gate_weak_signal_not_aligned():
    align = evaluate_entry_gate_alignment(
        _make_result(signal="WEAK_SELL", tech_dir="bearish", pos_dir="bearish", bias="bearish"),
        market_data=_market_all_bearish(),
        quant_factors={"available": True, "aggregateScore": -0.2, "side": "sell"},
    )
    assert align["aligned"] is False
    assert "SELL" in (align.get("reason") or "")


def test_quant_soft_veto_blocks_buy():
    opts = resolve_entry_gate_options()
    ok, _, status, note = resolve_quant_gate_confirm(
        "bullish",
        {"available": True, "aggregateScore": -0.2, "side": "sell"},
        quant_min_aggregate=0.12,
        gate_opts=opts,
    )
    assert ok is False
    assert status == "veto"
    assert "否决" in note


def test_entry_gate_fails_executable():
    quant = {"available": True, "aggregateScore": 0.2, "side": "buy"}
    result = _make_result(readiness="wait", rr=2.0)
    align = evaluate_entry_gate_alignment(
        result,
        market_data=_market_bullish(),
        quant_factors=quant,
    )
    assert align["aligned"] is False
    assert align.get("failedGate") == "executable"


def test_entry_gate_fails_llm_factor_conflict():
    align = evaluate_entry_gate_alignment(
        _make_result(tech_dir="bearish", pos_dir="bearish", bias="bearish"),
        market_data=_market_bullish(),
        quant_factors={"available": True, "aggregateScore": 0.2, "side": "buy"},
    )
    assert align["aligned"] is False
    assert align.get("failedGate") == "flow"


def test_build_entry_gate_list():
    quant = {"available": True, "aggregateScore": 0.2, "side": "buy"}
    align = evaluate_entry_gate_alignment(
        _make_result(),
        market_data=_market_bullish(),
        quant_factors=quant,
    )
    view = {
        "fiveSignalAlignment": align,
        "factors": _make_result().factors.model_dump(),
        "quantFactors": quant,
        "consensus": {},
        "dataQuality": {},
    }
    items = build_entry_gate_list(view)
    assert len(items) == 4
    assert [i["key"] for i in items] == ["structure", "flow", "quant", "executable"]
    assert all(i["participatesInGate"] for i in items)
    assert format_alignment_dimensions_cn(align)


def test_unanimous_mtf_structure_flow():
    quant = {"available": True, "aggregateScore": 0.2, "side": "buy"}
    result = _make_result()
    data = {**_market_bullish(), "quantFactors": quant}
    result, applied = _apply_unanimous_factor_rule(result, data)
    assert applied is True
    assert result.signal == "BUY"
