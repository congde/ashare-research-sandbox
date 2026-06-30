from __future__ import annotations

from typing import Any

from dashboard import api as dashboard_api
from dashboard.kline_analysis import TREND_LABELS, kline_verdict, run_kline_analysis
from dashboard.mode import prefer_offline


SIGNAL_LABELS = {
    "STRONG_BUY": "强烈看多",
    "BUY": "偏多",
    "WEAK_BUY": "偏多观望",
    "HOLD": "观望",
    "WEAK_SELL": "偏空观望",
    "SELL": "偏空",
    "STRONG_SELL": "强烈看空",
}

TREND_SCORES = {
    "bullish": 20,
    "weak_bullish": 10,
    "neutral": 0,
    "weak_bearish": -10,
    "bearish": -20,
}


def _signal_from_score(score: float) -> tuple[str, str]:
    if score >= 40:
        return "STRONG_BUY", SIGNAL_LABELS["STRONG_BUY"]
    if score >= 20:
        return "BUY", SIGNAL_LABELS["BUY"]
    if score >= 8:
        return "WEAK_BUY", SIGNAL_LABELS["WEAK_BUY"]
    if score <= -40:
        return "STRONG_SELL", SIGNAL_LABELS["STRONG_SELL"]
    if score <= -20:
        return "SELL", SIGNAL_LABELS["SELL"]
    if score <= -8:
        return "WEAK_SELL", SIGNAL_LABELS["WEAK_SELL"]
    return "HOLD", SIGNAL_LABELS["HOLD"]


def _market_state(trends: list[str]) -> str:
    bullish = sum(1 for item in trends if item in {"bullish", "weak_bullish"})
    bearish = sum(1 for item in trends if item in {"bearish", "weak_bearish"})
    if bullish >= 3 and bearish == 0:
        return "趋势延续"
    if bearish >= 3 and bullish == 0:
        return "趋势延续"
    if bullish > 0 and bearish > 0:
        return "多空分歧"
    return "震荡整理"


def _execution_readiness(score: float, rsi: float | None, range_pos: float | None) -> str:
    if score >= 20 and rsi is not None and rsi < 65:
        return "可执行"
    if score >= 8 and range_pos is not None and range_pos > 70:
        return "等待回踩"
    if score <= -8:
        return "观望"
    return "等待确认"


def _build_trade_plan(
    *,
    symbol: str,
    close: float,
    support: float,
    resistance: float,
    direction: str,
    invalidation: float | None = None,
) -> dict[str, Any]:
    if direction == "bullish":
        entry_low = close * 0.998
        entry_high = close * 1.002
        stop = invalidation or support
        target1 = resistance
        target2 = resistance + (resistance - support) * 0.5
    elif direction == "bearish":
        entry_low = close * 0.998
        entry_high = close * 1.002
        stop = invalidation or resistance
        target1 = support
        target2 = support - (resistance - support) * 0.5
    else:
        entry_low = close * 0.995
        entry_high = close * 1.005
        stop = support
        target1 = resistance
        target2 = resistance

    risk = abs(close - stop) if stop else 0
    reward1 = abs(target1 - close) if target1 else 0
    reward2 = abs(target2 - close) if target2 else 0
    rr1 = round(reward1 / risk, 2) if risk > 0 else 0
    rr2 = round(reward2 / risk, 2) if risk > 0 else 0

    return {
        "symbol": symbol,
        "direction": direction,
        "entryLow": round(entry_low, 2),
        "entryHigh": round(entry_high, 2),
        "stopLoss": round(stop, 2) if stop else None,
        "target1": round(target1, 2) if target1 else None,
        "target2": round(target2, 2) if target2 else None,
        "rr1": rr1,
        "rr2": rr2,
    }


def run_signal_analysis(symbol: str = "BTC") -> dict[str, Any]:
    base = (symbol or "BTC").strip().upper().replace("-USDT", "")
    pair = f"{base}-USDT"

    kline_bundle: dict[str, Any] = {}
    score = 0.0
    reasons: list[str] = []
    trends: list[str] = []

    timeframe_weights = {
        "15min": 0.15,
        "1hour": 0.35,
        "4hour": 0.3,
        "1day": 0.2,
    }
    primary = run_kline_analysis(pair, kline_type="1hour", limit=120)
    if not primary.get("ok"):
        return {
            "ok": False,
            "message": primary.get("message", "K线分析失败"),
            "error": primary.get("error", "kline_failed"),
        }

    offline = prefer_offline()
    for tf, weight in timeframe_weights.items():
        if tf == "1hour":
            payload = primary
        elif offline:
            payload = primary
        else:
            payload = run_kline_analysis(pair, kline_type=tf, limit=80)
        if not payload.get("ok"):
            continue
        analysis = payload.get("analysis") or {}
        trend_key = analysis.get("trend", "neutral")
        trends.append(trend_key)
        verdict = kline_verdict(analysis)
        tf_score = verdict.get("score", 0) * weight
        score += tf_score
        kline_bundle[tf] = {
            "trend": TREND_LABELS.get(trend_key, "中性"),
            "trendKey": trend_key,
            "score": verdict.get("score", 0),
            "rsi": analysis.get("rsi"),
            "verdict": verdict,
        }
        if tf == "1hour" and verdict.get("reasons"):
            reasons.extend(verdict["reasons"][:2])

    market_payload = dashboard_api.market_tickers()
    tickers = list(market_payload.get("tickers") or [])
    ticker = next((item for item in tickers if str(item.get("symbol", "")).upper() == pair), None) or {}
    metrics_primary = primary.get("metrics") or {}
    market = {
        "symbol": base,
        "pair": pair,
        "price": float(ticker.get("last") or metrics_primary.get("latestClose") or 0),
        "changeRate24h": float(ticker.get("changeRate") or 0) * 100,
        "high24h": float(ticker.get("high") or 0) if ticker.get("high") is not None else None,
        "low24h": float(ticker.get("low") or 0) if ticker.get("low") is not None else None,
        "volValue24h": float(ticker.get("volValue") or 0) if ticker.get("volValue") is not None else None,
    }

    onchain_payload = dashboard_api.onchain(base)
    fear_greed = None
    if onchain_payload.get("ok"):
        fg = (onchain_payload.get("marketSentiment") or {}).get("fearGreed") or {}
        fear_greed = fg.get("value") if isinstance(fg, dict) else fg
        if fear_greed is not None:
            if fear_greed <= 25:
                score += 5
                reasons.append(f"恐贪指数 {fear_greed} 偏恐惧，关注反弹")
            elif fear_greed >= 75:
                score -= 5
                reasons.append(f"恐贪指数 {fear_greed} 偏贪婪，注意回调")

    token_fund = dashboard_api.token_fund(base)
    bullish_ratio = None
    if token_fund.get("ok"):
        items = list(token_fund.get("items") or token_fund.get("tokens") or [])
        row = next((item for item in items if str(item.get("symbol", "")).upper() == base), None)
        if row:
            bullish_ratio = row.get("bullishRatio") or row.get("bullish_ratio")
            if bullish_ratio is not None:
                ratio = float(bullish_ratio)
                if ratio >= 0.6:
                    score += 6
                    reasons.append(f"资金情绪偏多 {ratio * 100:.0f}%")
                elif ratio <= 0.4:
                    score -= 6
                    reasons.append(f"资金情绪偏空 {ratio * 100:.0f}%")

    metrics = primary.get("metrics") or {}
    analysis_primary = primary.get("analysis") or {}
    verdict_primary = kline_verdict(analysis_primary)
    direction = verdict_primary.get("direction", "neutral")
    signal_key, signal_label = _signal_from_score(score)
    confidence = min(95, round(abs(score) * 1.2, 1))
    market_state = _market_state(trends)
    execution = _execution_readiness(
        score,
        analysis_primary.get("rsi"),
        analysis_primary.get("rangePos"),
    )

    support = float(metrics.get("support20") or 0)
    resistance = float(metrics.get("resistance20") or 0)
    close = float(metrics.get("latestClose") or market.get("price") or 0)
    invalidation = resistance if direction == "bullish" else support
    trade_plan = _build_trade_plan(
        symbol=base,
        close=close,
        support=support,
        resistance=resistance,
        direction=direction,
        invalidation=invalidation,
    )

    summary_parts = [
        f"{signal_label} · 置信度 {confidence:.1f}% · 得分 {score:+.0f}",
    ]
    if execution == "等待回踩":
        summary_parts.append(
            f"价格接近阻力 {resistance:.2f}，建议等待回踩确认；失效位 {invalidation:.2f}。"
        )
    elif direction == "bullish":
        summary_parts.append(f"若 1h 趋势反向或触及失效位 {invalidation:.2f}，立即止损离场。")
    else:
        summary_parts.append("多维证据尚未形成一致方向，保持观望。")

    technical_score = kline_bundle.get("1hour", {}).get("score", 0)
    evidence = {
        "technical": {"bias": "偏多" if technical_score > 0 else "偏空" if technical_score < 0 else "中性", "score": round(technical_score, 1)},
        "capital": {"bias": "偏多" if (bullish_ratio or 0.5) > 0.55 else "偏空" if (bullish_ratio or 0.5) < 0.45 else "中性", "score": round((float(bullish_ratio or 0.5) - 0.5) * 40, 1)},
        "sentiment": {"bias": "偏多" if (fear_greed or 50) < 40 else "偏空" if (fear_greed or 50) > 60 else "中性", "score": round((50 - float(fear_greed or 50)) / 5, 1)},
        "consensus": {"bias": "中性", "consistency": confidence},
    }

    return {
        "ok": True,
        "engine": "sandbox-rule-based",
        "engineMeta": {"provider": "sandbox", "model": "规则引擎（教学沙箱）"},
        "symbol": base,
        "pair": pair,
        "signal": signal_key,
        "signalLabel": signal_label,
        "confidence": confidence,
        "score": round(score, 1),
        "summary": " ".join(summary_parts),
        "reasons": reasons[:6],
        "tradePlan": trade_plan,
        "market": market,
        "kline": kline_bundle,
        "analysis": {
            "marketState": market_state,
            "executionReadiness": execution,
            "marketStateDetail": f"{market_state} - 中性",
            "coverage": "日内 / 覆盖度 95%",
        },
        "onchainMetrics": {"fearGreed": fear_greed},
        "evidence": evidence,
        "logicFlow": [
            {
                "step": 1,
                "title": "市场状态识别",
                "status": f"{market_state} - 中性",
                "detail": f"覆盖 {len(kline_bundle)} 个周期",
                "badges": [signal_key, f"失效位 {invalidation / 1000:.2f}K" if invalidation > 1000 else f"失效位 {invalidation:.0f}"],
            },
            {
                "step": 2,
                "title": "多维证据汇总",
                "dimensions": [
                    {"name": "技术面", "bias": evidence["technical"]["bias"], "score": evidence["technical"]["score"]},
                    {"name": "筹码/资金", "bias": evidence["capital"]["bias"], "score": evidence["capital"]["score"]},
                    {"name": "盘面/资金情绪", "bias": evidence["sentiment"]["bias"], "score": evidence["sentiment"]["score"]},
                    {"name": "共识", "bias": evidence["consensus"]["bias"], "score": evidence["consensus"]["consistency"]},
                ],
            },
            {
                "step": 3,
                "title": "冲突与风险校验",
                "note": "主要维度方向一致" if len(set(trends)) <= 2 else "多周期存在分歧",
                "status": f"执行准备度 {execution}",
            },
            {
                "step": 4,
                "title": "执行与风控落地",
                "summary": summary_parts[0],
                "detail": summary_parts[1] if len(summary_parts) > 1 else "",
                "rr1": trade_plan.get("rr1"),
                "rr2": trade_plan.get("rr2"),
            },
        ],
    }
