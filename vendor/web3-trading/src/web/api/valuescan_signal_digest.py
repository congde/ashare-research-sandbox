# -*- coding: utf-8 -*-
"""ValueScan → actionable digest for LLM signal analysis and live trading console."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_MSG_TYPE_LABELS: Dict[int, str] = {
    1: "主力吸筹",
    2: "突破信号",
    3: "趋势启动",
    4: "回调买入",
    5: "放量突破",
    6: "缩量回踩",
    7: "底部信号",
    8: "反转信号",
    9: "主力派发",
    10: "破位风险",
    11: "见顶信号",
    12: "超买风险",
    13: "资金异动",
    14: "主力入场",
    15: "抛压预警",
    16: "短线机会",
    17: "趋势信号",
    18: "量价配合",
    19: "背离信号",
    20: "上涨止盈",
    21: "保护本金",
    22: "追踪结束",
    23: "出货预警",
    24: "持仓减少加速",
    25: "下跌止盈",
    26: "移动止盈",
    27: "大部分止盈",
    28: "FOMO",
    29: "FOMO加剧",
    30: "主力增持",
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if number != number:
            return default
        return number
    except (TypeError, ValueError):
        return default


def _msg_type_label(msg: Dict[str, Any]) -> str:
    raw = (
        msg.get("chanceMessageType")
        or msg.get("riskMessageType")
        or msg.get("fundsMessageType")
        or msg.get("fundsMovementType")
        or 0
    )
    try:
        code = int(raw)
    except (TypeError, ValueError):
        code = 0
    return _MSG_TYPE_LABELS.get(code, f"信号#{code}" if code else "追踪更新")


def _latest_messages(ai_messages: Any, limit: int = 3) -> List[Dict[str, Any]]:
    if not isinstance(ai_messages, dict):
        return []
    out: List[Dict[str, Any]] = []
    for channel in ("funds", "chance", "risk"):
        rows = ai_messages.get(channel) or []
        if not isinstance(rows, list):
            continue
        for row in rows[:limit]:
            if isinstance(row, dict):
                out.append({**row, "_channel": channel})
    out.sort(key=lambda x: _num(x.get("updateTime")), reverse=True)
    return out[:limit]


def _parse_sr_levels(vs: Dict[str, Any], mark: float) -> Tuple[List[float], List[float]]:
    sr = vs.get("supportResistance") or []
    supports: List[float] = []
    resistances: List[float] = []
    for item in sr:
        if not isinstance(item, dict):
            continue
        price = _num(item.get("price") or item.get("densePrice"))
        if price <= 0:
            continue
        kind = str(item.get("type") or item.get("denseType") or "").lower()
        if mark > 0:
            if price < mark * 0.9995 or "support" in kind:
                supports.append(price)
            elif price > mark * 1.0005 or "resist" in kind or "pressure" in kind:
                resistances.append(price)
            else:
                supports.append(price)
        else:
            supports.append(price)
    supports = sorted(set(supports), reverse=True)
    resistances = sorted(set(resistances))
    return supports[:5], resistances[:5]


def infer_market_regime(vs: Dict[str, Any]) -> Tuple[str, str]:
    """Return (regime_code, chinese_label): bullish | bearish | range | uncertain."""
    history = vs.get("aiMarketAnalyseHistory") or []
    sse = vs.get("sseMarketEvents") or []
    text_blob = ""
    if isinstance(history, list) and history:
        latest = history[0] if isinstance(history[0], dict) else {}
        text_blob += str(latest.get("content") or latest.get("analyseResult") or "")
    if isinstance(sse, list):
        for ev in sse[:2]:
            if isinstance(ev, dict):
                text_blob += str(ev.get("content") or "")

    indicators = vs.get("priceIndicators") or []
    if isinstance(indicators, list) and indicators:
        last = indicators[-1] if isinstance(indicators[-1], dict) else {}
        pmt = str(last.get("priceMarketType") or "").upper()
        if "BTC" in pmt or "ETH" in pmt:
            text_blob += " " + str(last.get("priceMarketSignal") or last.get("signal") or "")

    lower = text_blob.lower()
    if any(k in text_blob for k in ("利好", "看多", "多头", "上涨", "bullish")):
        return "bullish", "利好"
    if any(k in text_blob for k in ("利空", "看空", "空头", "下跌", "bearish")):
        return "bearish", "利空"
    if any(k in text_blob for k in ("震荡", "区间", "盘整", "range", "neutral")):
        return "range", "震荡"
    if "bull" in lower:
        return "bullish", "偏多"
    if "bear" in lower:
        return "bearish", "偏空"
    return "uncertain", "方向未定"


def _action_bias_from_signals(
    ai_signals: Dict[str, Any],
    messages: List[Dict[str, Any]],
    risk_score: float,
    opportunity_score: float,
) -> str:
    if "risk" in ai_signals or risk_score >= 6:
        return "risk_off"
    if "chance" in ai_signals or opportunity_score >= 6:
        return "bullish"
    if "funds" in ai_signals:
        return "watch"
    for msg in messages:
        ch = msg.get("_channel")
        if ch == "risk":
            return "risk_off"
        if ch == "chance":
            return "bullish"
    return "neutral"


def build_valuescan_digest(
    vs: Optional[Dict[str, Any]],
    mark_price: float = 0.0,
) -> Dict[str, Any]:
    """Structured, low-noise ValueScan summary for LLM and UI."""
    if not vs or not isinstance(vs, dict):
        return {"available": False}

    mark = _num(mark_price) or _num((vs.get("tokenDetail") or {}).get("price"))
    supports, resistances = _parse_sr_levels(vs, mark)
    regime, regime_label = infer_market_regime(vs)
    ai_signals = vs.get("aiSignals") or {}
    messages = _latest_messages(vs.get("aiMessages"), limit=4)

    alerts: List[str] = []
    opportunity_score = 0.0
    risk_score = 0.0

    hit_chance = "chance" in ai_signals
    hit_risk = "risk" in ai_signals
    hit_funds = "funds" in ai_signals
    if hit_chance:
        opportunity_score += 8
        alerts.append("AI 机会榜：该币在机会追踪列表")
    if hit_risk:
        risk_score += 8
        alerts.append("AI 风险榜：该币在风险追踪列表，注意减仓/止损")
    if hit_funds:
        opportunity_score += 3
        alerts.append("AI 资金异动：主力/资金异常活跃")

    for msg in messages:
        label = _msg_type_label(msg)
        ch = msg.get("_channel", "")
        ch_name = {"chance": "机会", "risk": "风险", "funds": "资金异动"}.get(ch, ch)
        price = msg.get("price")
        price_s = f" @ ${_num(price):,.4g}" if price else ""
        alerts.append(f"VS {ch_name}：{label}{price_s}")
        if ch == "risk":
            risk_score += 4
        elif ch == "chance":
            opportunity_score += 4
        else:
            opportunity_score += 2

    fund = vs.get("fund") or {}
    for row in fund.get("spotGoodsList") or fund.get("categories_trade_data_list") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("timeRange") or row.get("timeParticleEnum")) in ("D1", "124", "1"):
            inflow = _num(row.get("tradeInflow") or row.get("trade_inflow"))
            if inflow != 0:
                alerts.append(f"资金 D1 净{'流入' if inflow > 0 else '流出'} ${abs(inflow):,.0f}")
            break

    sent = vs.get("sentiment") or {}
    bull = _num(sent.get("bullishRatio"))
    bear = _num(sent.get("bearishRatio"))
    if bull or bear:
        alerts.append(f"社媒情绪 看多 {bull * 100:.0f}% / 看空 {bear * 100:.0f}%")

    whale = vs.get("whaleCost") or []
    whale_price = 0.0
    if isinstance(whale, list):
        for item in reversed(whale):
            if isinstance(item, dict) and item.get("cost"):
                whale_price = _num(item["cost"])
                break
    if whale_price > 0 and mark > 0:
        dev = (mark - whale_price) / whale_price * 100
        alerts.append(f"主力成本 ${whale_price:,.4g}，现价偏离 {dev:+.1f}%")

    action_bias = _action_bias_from_signals(ai_signals, messages, risk_score, opportunity_score)
    primary_alert = alerts[0] if alerts else "暂无 ValueScan 实时追踪告警"

    suggested = suggest_trade_plan_from_digest(
        mark_price=mark,
        supports=supports,
        resistances=resistances,
        action_bias=action_bias,
        regime=regime,
    )

    return {
        "available": True,
        "symbol": vs.get("symbol") or "",
        "markPrice": mark,
        "marketRegime": regime,
        "marketRegimeLabel": regime_label,
        "actionBias": action_bias,
        "opportunityScore": round(opportunity_score, 1),
        "riskScore": round(risk_score, 1),
        "primaryAlert": primary_alert,
        "alerts": alerts[:8],
        "signalHits": {
            k: k in ai_signals for k in ("chance", "risk", "funds")
        },
        "latestMessages": [
            {
                "channel": m.get("_channel"),
                "type": _msg_type_label(m),
                "price": m.get("price"),
                "updateTime": m.get("updateTime"),
            }
            for m in messages
        ],
        "supportLevels": supports,
        "resistanceLevels": resistances,
        "whaleCost": whale_price,
        "suggestedPlan": suggested,
    }


def suggest_trade_plan_from_digest(
    *,
    mark_price: float,
    supports: List[float],
    resistances: List[float],
    action_bias: str,
    regime: str,
    signal: str = "NEUTRAL",
) -> Dict[str, float]:
    """Rule-based price ladder from VS dense S/R (fallback when LLM plan is thin)."""
    mark = _num(mark_price)
    if mark <= 0:
        return {}

    support = supports[0] if supports else mark * 0.97
    resistance = resistances[0] if resistances else mark * 1.03
    sig = str(signal or "").upper()
    bearish_plan = sig in ("SELL", "WEAK_SELL") or regime == "bearish"

    if bearish_plan:
        res = resistance if resistance > mark * 0.998 else (resistances[1] if len(resistances) > 1 else mark * 1.02)
        sup = support
        stop = res * 1.005
        target1 = supports[1] if len(supports) > 1 else (sup * 0.99 if sup else mark * 0.97)
        target2 = supports[2] if len(supports) > 2 else target1 * 0.985
        entry_low = res * 0.995
        entry_high = res * 1.005
        if mark < entry_low:
            entry_low = mark * 0.998
            entry_high = max(mark * 1.002, res * 0.998)
    else:
        stop = support * 0.995 if action_bias in ("bullish", "watch") else resistance * 1.005
        target1 = resistances[0] if resistances else mark * 1.02
        target2 = resistances[1] if len(resistances) > 1 else target1 * 1.015

        if action_bias == "risk_off":
            entry_low = mark * 0.998
            entry_high = mark * 1.002
            stop = resistance * 1.003 if resistance else mark * 1.02
            target1 = support if support else mark * 0.98
            target2 = supports[1] if len(supports) > 1 else target1 * 0.99
        elif regime == "range":
            entry_low = min(support, mark * 0.998)
            entry_high = max(support, mark * 0.999)
        elif action_bias == "bullish":
            entry_low = min(support, mark * 0.995)
            entry_high = min(mark, support * 1.01) if support else mark
        else:
            entry_low = mark * 0.995
            entry_high = mark * 1.005

    return {
        "support": round(support, 8),
        "resistance": round(resistance, 8),
        "entryLow": round(entry_low, 8),
        "entryHigh": round(entry_high, 8),
        "stop": round(stop, 8),
        "target1": round(target1, 8),
        "target2": round(target2, 8),
    }


def merge_trade_plan_with_digest(
    trade_plan: Optional[Dict[str, Any]],
    digest: Dict[str, Any],
    *,
    signal: str = "NEUTRAL",
) -> Dict[str, float]:
    """Fill missing trade plan fields from VS suggested ladder."""
    suggested = digest.get("suggestedPlan") or {}
    if not suggested:
        return dict(trade_plan or {})

    out = dict(suggested)
    existing = trade_plan or {}
    for key in ("support", "resistance", "entryLow", "entryHigh", "stop", "target1", "target2"):
        val = _num(existing.get(key))
        if val > 0:
            out[key] = val

    if _num(out.get("stop")) <= 0 and suggested.get("stop"):
        out["stop"] = suggested["stop"]

    sig = str(signal or "").upper()
    if sig in ("SELL", "WEAK_SELL"):
        if _num(out.get("entryLow")) >= _num(out.get("entryHigh")):
            el, eh = out.get("entryHigh"), out.get("entryLow")
            out["entryLow"], out["entryHigh"] = eh, el
        entry_high = _num(out.get("entryHigh"))
        entry_low = _num(out.get("entryLow"))
        resistance = _num(out.get("resistance")) or _num(suggested.get("resistance"))
        support = _num(out.get("support")) or _num(suggested.get("support"))
        if entry_high > 0 and _num(out.get("stop")) <= entry_high:
            out["stop"] = round((resistance or entry_high) * 1.005, 8)
        if entry_low > 0 and 0 < _num(out.get("target1")) >= entry_low:
            out["target1"] = round((support or entry_low) * 0.99 if support else entry_low * 0.985, 8)
        t1 = _num(out.get("target1"))
        if t1 > 0 and (_num(out.get("target2")) <= 0 or _num(out.get("target2")) >= t1):
            out["target2"] = round(t1 * 0.985, 8)

    return out


def format_valuescan_digest_for_llm(digest: Dict[str, Any]) -> str:
    if not digest.get("available"):
        return "暂无 ValueScan 数据"

    lines = [
        f"标的: {digest.get('symbol') or '?'} · 参考价 ${digest.get('markPrice', 0):,.4g}",
        f"大盘/宏观情绪: {digest.get('marketRegimeLabel')} ({digest.get('marketRegime')})",
        f"VS 动作倾向: {digest.get('actionBias')} · 机会分 {digest.get('opportunityScore')} / 风险分 {digest.get('riskScore')}",
        f"首要提示: {digest.get('primaryAlert')}",
    ]
    hits = digest.get("signalHits") or {}
    hit_parts = [name for name, on in hits.items() if on]
    if hit_parts:
        lines.append(f"榜单命中: {', '.join(hit_parts)}")

    alerts = digest.get("alerts") or []
    if len(alerts) > 1:
        lines.append("追踪摘要:")
        lines.extend(f"- {a}" for a in alerts[1:6])

    supports = digest.get("supportLevels") or []
    resistances = digest.get("resistanceLevels") or []
    if supports:
        lines.append("关键支撑: " + ", ".join(f"${p:,.4g}" for p in supports[:4]))
    if resistances:
        lines.append("关键压力: " + ", ".join(f"${p:,.4g}" for p in resistances[:4]))

    plan = digest.get("suggestedPlan") or {}
    if plan.get("entryLow") and plan.get("stop"):
        lines.append(
            "VS 建议价位(规则推导，供 tradePlan 交叉验证): "
            f"入场 {plan.get('entryLow'):,.4g}~{plan.get('entryHigh'):,.4g} · "
            f"止损 {plan.get('stop'):,.4g} · 目标 {plan.get('target1'):,.4g}/{plan.get('target2'):,.4g}"
        )

    msgs = digest.get("latestMessages") or []
    if msgs:
        lines.append("最新追踪消息:")
        for m in msgs[:3]:
            lines.append(f"- [{m.get('channel')}] {m.get('type')} {m.get('price') or ''}")

    return "\n".join(lines)


async def fetch_multi_symbol_digest(
    symbols: List[str],
    mark_prices: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Batch digest for live console (parallel fetch)."""
    import asyncio

    from web.api.dashboard_service import fetch_valuescan_signal_data

    marks = mark_prices or {}
    unique = []
    seen: set[str] = set()
    for s in symbols:
        sym = str(s or "").strip().upper().split("-")[0].split("/")[0]
        if sym and sym not in seen:
            seen.add(sym)
            unique.append(sym)

    async def _one(sym: str) -> Tuple[str, Dict[str, Any]]:
        vs = await fetch_valuescan_signal_data(sym)
        digest = build_valuescan_digest(vs, marks.get(sym, 0.0))
        return sym, digest

    pairs = await asyncio.gather(*[_one(s) for s in unique[:8]], return_exceptions=True)
    per_symbol: Dict[str, Any] = {}
    regime_label = "方向未定"
    regime = "uncertain"
    for item in pairs:
        if isinstance(item, Exception):
            continue
        sym, digest = item
        per_symbol[sym] = digest
        if sym in ("BTC", "ETH") and digest.get("marketRegimeLabel"):
            regime = digest.get("marketRegime") or regime
            regime_label = digest.get("marketRegimeLabel") or regime_label

    return {
        "marketRegime": regime,
        "marketRegimeLabel": regime_label,
        "symbols": per_symbol,
    }
