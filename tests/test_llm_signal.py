from __future__ import annotations

import os

from dashboard.llm_signal import _merge_llm, llm_configured, resolve_model, run_llm_signal_analysis


def test_resolve_model_defaults_to_deepseek_v4_pro(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert resolve_model() == "deepseek-v4-pro"
    assert resolve_model("deepseek/deepseek-v4-pro") == "deepseek-v4-pro"
    assert resolve_model("deepseek-chat") == "deepseek-chat"


def test_llm_configured_reads_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm_configured() is False
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert llm_configured() is True


def test_merge_llm_overrides_signal_fields() -> None:
    baseline = {
        "ok": True,
        "signal": "HOLD",
        "signalLabel": "观望",
        "confidence": 10,
        "score": 0,
        "summary": "rule",
        "analysis": {"marketState": "震荡整理"},
        "logicFlow": [{"step": 1, "title": "规则"}],
        "market": {"price": 100},
        "kline": {},
        "tradePlan": {},
    }
    merged = _merge_llm(
        baseline,
        {
            "signal": "WEAK_BUY",
            "signalLabel": "偏多观望",
            "confidence": 48,
            "score": 30,
            "summary": "等待回踩确认",
            "analysis": {"executionReadiness": "等待回踩"},
            "logicFlow": [{"step": 1, "title": "LLM"}],
        },
        "deepseek-v4-pro",
    )
    assert merged["engine"] == "llm"
    assert merged["signal"] == "WEAK_BUY"
    assert merged["analysis"]["executionReadiness"] == "等待回踩"
    assert merged["engineMeta"]["model"] == "deepseek-v4-pro"


def test_merge_llm_flags_invalid_signal_and_numeric_range() -> None:
    baseline = {
        "ok": True,
        "signal": "HOLD",
        "signalLabel": "观望",
        "confidence": 10,
        "score": 0,
        "summary": "rule",
        "analysis": {},
    }
    merged = _merge_llm(
        baseline,
        {
            "signal": "BUY_NOW",
            "confidence": 130,
            "score": -140,
            "summary": "invalid",
        },
        "deepseek-v4-pro",
    )

    assert merged["signal"] == "HOLD"
    assert merged["confidence"] == 10
    assert merged["score"] == 0
    assert merged["reviewFlags"] == [
        "INVALID_SIGNAL_FALLBACK",
        "CONFIDENCE_OUT_OF_RANGE",
        "SCORE_OUT_OF_RANGE",
    ]


def test_run_llm_signal_analysis_without_key_falls_back(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    payload = run_llm_signal_analysis("BTC")
    assert payload.get("ok") is True
    assert payload.get("engineMeta", {}).get("note")
