from __future__ import annotations

import json
import os
import re
from typing import Any

from dashboard.http_client import http_post
from dashboard.signal_analysis import run_signal_analysis

DEFAULT_MODEL = "deepseek-v4-pro"
SIGNAL_KEYS = {
    "STRONG_BUY",
    "BUY",
    "WEAK_BUY",
    "HOLD",
    "WEAK_SELL",
    "SELL",
    "STRONG_SELL",
}


def llm_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def resolve_model(model: str | None = None) -> str:
    raw = (model or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL).strip()
    if "/" in raw:
        return raw.split("/", 1)[1]
    return raw


def _api_base() -> str:
    base = os.environ.get("OPENAI_API_BASE", "https://api.deepseek.com").strip().strip('"').strip("'")
    return base.rstrip("/")


def _chat_completions_url() -> str:
    base = _api_base()
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    payload = json.loads(cleaned)
    return payload if isinstance(payload, dict) else {}


def _build_prompt(symbol: str, baseline: dict[str, Any]) -> str:
    context = {
        "symbol": symbol,
        "market": baseline.get("market"),
        "kline": baseline.get("kline"),
        "evidence": baseline.get("evidence"),
        "onchainMetrics": baseline.get("onchainMetrics"),
        "tradePlan": baseline.get("tradePlan"),
        "ruleSignal": {
            "signal": baseline.get("signal"),
            "signalLabel": baseline.get("signalLabel"),
            "confidence": baseline.get("confidence"),
            "score": baseline.get("score"),
            "reasons": baseline.get("reasons"),
        },
    }
    return (
        "你是加密货币交易分析助手。根据以下多维数据给出交易信号，输出必须是单个 JSON 对象，不要 markdown。\n"
        "字段要求：\n"
        '- signal: 枚举之一 STRONG_BUY|BUY|WEAK_BUY|HOLD|WEAK_SELL|SELL|STRONG_SELL\n'
        "- signalLabel: 中文标签（如 偏多观望）\n"
        "- confidence: 0-100 数字\n"
        "- score: -100 到 100 数字\n"
        "- summary: 核心结论，1-2 句中文\n"
        '- analysis: { "marketState": string, "executionReadiness": string }\n'
        "- logicFlow: 长度 4 的数组，每项含 step,title,status 或 detail 或 note 或 summary；"
        "第 2 步可含 dimensions:[{name,bias,score}]\n"
        "保持客观，引用数据中的支撑/阻力与失效位，不要编造未提供的价格。\n\n"
        f"数据:\n{json.dumps(context, ensure_ascii=False)}"
    )


def _call_llm(prompt: str, model: str) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "只返回合法 JSON，不要解释文字。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        ensure_ascii=False,
    )
    timeout = float(os.environ.get("OPENAI_API_TIMEOUT", "90"))
    payload = http_post(
        _chat_completions_url(),
        body,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )

    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("LLM returned empty choices")
    content = (choices[0].get("message") or {}).get("content") or ""
    return _extract_json(content)


def _merge_llm(baseline: dict[str, Any], llm: dict[str, Any], model: str) -> dict[str, Any]:
    merged = dict(baseline)
    review_flags: list[str] = []
    signal = str(llm.get("signal") or baseline.get("signal") or "HOLD").upper()
    if signal not in SIGNAL_KEYS:
        signal = str(baseline.get("signal") or "HOLD").upper()
        review_flags.append("INVALID_SIGNAL_FALLBACK")

    confidence = _bounded_number(
        llm.get("confidence"),
        default=baseline.get("confidence") or 0,
        low=0,
        high=100,
        flag="CONFIDENCE_OUT_OF_RANGE",
        review_flags=review_flags,
    )
    score = _bounded_number(
        llm.get("score") if llm.get("score") is not None else baseline.get("score"),
        default=baseline.get("score") or 0,
        low=-100,
        high=100,
        flag="SCORE_OUT_OF_RANGE",
        review_flags=review_flags,
    )

    merged.update(
        {
            "ok": True,
            "engine": "llm",
            "engineMeta": {
                "provider": "deepseek",
                "model": model,
                "displayModel": "DeepSeek V4 Pro" if "v4-pro" in model else f"DeepSeek {model}",
            },
            "signal": signal,
            "signalLabel": llm.get("signalLabel") or baseline.get("signalLabel"),
            "confidence": confidence,
            "score": score,
            "summary": llm.get("summary") or baseline.get("summary"),
            "reasons": llm.get("reasons") or baseline.get("reasons"),
        }
    )
    if review_flags:
        merged["reviewFlags"] = [*(baseline.get("reviewFlags") or []), *review_flags]

    analysis = dict(baseline.get("analysis") or {})
    llm_analysis = llm.get("analysis") if isinstance(llm.get("analysis"), dict) else {}
    analysis.update({k: v for k, v in llm_analysis.items() if v})
    merged["analysis"] = analysis

    logic_flow = llm.get("logicFlow")
    if isinstance(logic_flow, list) and logic_flow:
        merged["logicFlow"] = logic_flow
    return merged


def _bounded_number(
    value: Any,
    *,
    default: Any,
    low: float,
    high: float,
    flag: str,
    review_flags: list[str],
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        review_flags.append(flag)
        return float(default or 0)
    if parsed < low or parsed > high:
        review_flags.append(flag)
        return float(default or 0)
    return parsed


def run_llm_signal_analysis(symbol: str = "BTC", *, model: str | None = None) -> dict[str, Any]:
    resolved_model = resolve_model(model)
    configured_at_start = llm_configured()
    baseline = run_signal_analysis(symbol)
    if not baseline.get("ok"):
        return baseline

    if not configured_at_start:
        baseline = dict(baseline)
        baseline["engineMeta"] = {
            **(baseline.get("engineMeta") or {}),
            "model": "规则引擎（教学沙箱）",
            "note": "未配置 OPENAI_API_KEY；使用多维规则引擎生成信号。",
        }
        return baseline

    try:
        prompt = _build_prompt(symbol.strip().upper(), baseline)
        llm_payload = _call_llm(prompt, resolved_model)
        return _merge_llm(baseline, llm_payload, resolved_model)
    except Exception as exc:
        fallback = dict(baseline)
        fallback["engine"] = "sandbox-rule-based"
        fallback["engineMeta"] = {
            "provider": "sandbox",
            "model": resolved_model,
            "displayModel": f"DeepSeek {resolved_model}",
            "note": f"LLM 调用失败，已回退规则引擎：{exc}",
        }
        return fallback
