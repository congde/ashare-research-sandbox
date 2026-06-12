# -*- coding: utf-8 -*-
"""
Signal analyzer — composable scorer pattern.

Each scorer function takes the aggregated data dict and returns
(score_delta: float, reasons: list[str]).  The final signal is
derived by summing all deltas and mapping to a discrete level.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
SignalLevel = str  # "BUY" | "WEAK_BUY" | "NEUTRAL" | "WEAK_SELL" | "SELL"
Scorer = Callable[[Dict[str, Any]], Tuple[float, List[str]]]

SIGNAL_THRESHOLDS: List[Tuple[float, SignalLevel, str]] = [
    (30, "BUY", "买入"),
    (10, "WEAK_BUY", "偏多观望"),
    (-10, "NEUTRAL", "中性观望"),
    (-30, "WEAK_SELL", "偏空观望"),
    (float("-inf"), "SELL", "卖出"),
]

_POSITIVE_NEWS_KW = frozenset({
    "bullish", "surge", "rally", "soar", "breakout", "all-time high", "ath",
    "pump", "gains", "buy", "upgrade", "adoption", "launch", "利好", "暴涨", "突破", "新高",
})
_NEGATIVE_NEWS_KW = frozenset({
    "bearish", "crash", "dump", "plunge", "liquidat", "sell-off", "selloff",
    "hack", "exploit", "ban", "scam", "fraud", "利空", "暴跌", "清算", "崩盘",
})

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
_TF_WEIGHTS: List[Tuple[str, str, float]] = [
    ("15min", "15m", 0.6),
    ("1hour", "1h", 1.0),
    ("4hour", "4h", 1.5),
]


def _tf_sigs(data: Dict[str, Any]) -> List[Tuple[str, Dict, float]]:
    """Return [(label, sig_dict, weight)] for each available kline timeframe."""
    kline = data.get("kline") or {}
    return [(lbl, kline[tf], w) for tf, lbl, w in _TF_WEIGHTS if kline.get(tf)]


def _resolve_levels(data: Dict[str, Any]) -> Tuple[float, float, float]:
    """Return (last_price, support, resistance), refined by VS dense-area levels."""
    from web.api.realtime_market_bridge import resolve_live_mark_price

    kline = data.get("kline") or {}
    vs = data.get("valuescan") or {}
    last = resolve_live_mark_price(data)
    kl = kline.get("1hour") or kline.get("4hour") or {}
    sup = kl.get("support") or (last * 0.98 if last else 0)
    res = kl.get("resistance") or (last * 1.02 if last else 0)
    vs_sr = vs.get("supportResistance") or []
    if vs_sr and last:
        ps = [float(i.get("price", 0)) for i in vs_sr if i.get("price")]
        vs_sup = sorted([p for p in ps if p < last], reverse=True)
        vs_res = sorted([p for p in ps if p >= last])
        if vs_sup:
            sup = max(sup, vs_sup[0])
        if vs_res:
            res = min(res, vs_res[0])
    return last, sup, res


# ---------------------------------------------------------------------------
# Individual scorers
# ---------------------------------------------------------------------------
def score_kline(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """K-line trend: MA alignment, range position, volume across timeframes."""
    _TREND_SCORES = {"bullish": 18, "bearish": -18, "weak_bullish": 8, "weak_bearish": -8}
    _TREND_LABELS = {
        "bullish": "均线多头排列（MA20 > MA60），趋势偏多",
        "bearish": "均线空头排列（MA20 < MA60），趋势偏空",
        "weak_bullish": "价格站上 MA20，短线偏多",
        "weak_bearish": "价格跌破 MA20，短线偏空",
    }
    score, reasons = 0.0, []
    for lbl, sig, w in _tf_sigs(data):
        trend = sig.get("trend", "neutral")
        if trend in _TREND_SCORES:
            score += _TREND_SCORES[trend] * w
            reasons.append(f"{lbl} {_TREND_LABELS[trend]}")
        rp = sig.get("rangePos", 50)
        if rp >= 80:
            score -= 5; reasons.append(f"{lbl} 区间位置 {rp:.0f}%，接近阻力位，注意回落风险")
        elif rp <= 20:
            score += 5; reasons.append(f"{lbl} 区间位置 {rp:.0f}%，接近支撑位，关注反弹")
        vr = sig.get("volRatio", 1.0)
        if vr >= 1.5:
            reasons.append(f"{lbl} 近 5 根量能放大 {vr:.1f}x，资金活跃")
        elif vr <= 0.5:
            reasons.append(f"{lbl} 近 5 根量能萎缩 {vr:.1f}x，市场观望")
    return score, reasons


def score_market(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Score based on 24h price change."""
    change = (data.get("market") or {}).get("changeRate", 0)
    pct = f"{change * 100:.2f}%"
    if change > 0.05:
        return 12, [f"24h 涨幅 {pct}，强势上涨"]
    if change > 0.02:
        return 6, [f"24h 涨幅 {pct}，温和上涨"]
    if change < -0.05:
        return -12, [f"24h 跌幅 {pct}，大幅回调"]
    if change < -0.02:
        return -6, [f"24h 跌幅 {pct}，温和下跌"]
    return 0, []


def _score_fear_greed_value(
    fg: float,
    *,
    label: str = "",
    change: Optional[float] = None,
    yesterday: Optional[float] = None,
) -> Tuple[float, List[str]]:
    """Shared fear/greed scoring (alternative.me or MCP). Used by technical dimension."""
    score = 0.0
    reasons: List[str] = []
    trend_note = ""
    if change is not None:
        trend_note = f"，较昨日{'上升' if change > 0 else '下降'} {abs(change):.0f} 点"
    elif yesterday is not None:
        try:
            diff = fg - float(yesterday)
            trend_note = f"，较昨日{'上升' if diff > 0 else '下降'} {abs(diff):.0f} 点"
        except (ValueError, TypeError):
            pass

    thresholds = [(75, -5, "极度贪婪", "注意过热风险"), (55, 3, "贪婪", "市场情绪偏乐观")]
    for threshold, delta, default_label, desc in thresholds:
        if fg >= threshold:
            score += delta
            reasons.append(f"恐贪指数 {fg:.0f}（{label or default_label}），{desc}{trend_note}")
            return score, reasons
    if fg <= 25:
        score += 5
        reasons.append(f"恐贪指数 {fg:.0f}（{label or '极度恐惧'}），或存在超跌反弹机会{trend_note}")
    elif fg <= 45:
        score -= 3
        reasons.append(f"恐贪指数 {fg:.0f}（{label or '恐惧'}），市场情绪偏谨慎{trend_note}")
    return score, reasons


def score_fear_greed(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Public fear & greed (alternative.me) + optional MCP — counts toward technical, not onchain."""
    score = 0.0
    reasons: List[str] = []

    metrics = data.get("onchainMetrics") or {}
    fg = metrics.get("fearGreed") or {}
    if fg.get("value") is not None:
        try:
            delta, items = _score_fear_greed_value(
                float(fg["value"]),
                label=str(fg.get("label") or ""),
                change=fg.get("change"),
            )
            score += delta
            reasons.extend(items)
        except (TypeError, ValueError):
            pass

    extra = (data.get("onchain") or {}).get("extra") or {}
    fg_raw = extra.get("fear_greed")
    if fg_raw is not None and not reasons:
        try:
            fg_val = float(fg_raw) if not isinstance(fg_raw, dict) else float(fg_raw.get("value", 50))
            status = fg_raw.get("status", "").replace("_", " ") if isinstance(fg_raw, dict) else ""
            delta, items = _score_fear_greed_value(
                fg_val,
                label=status,
                yesterday=extra.get("fear_greed_yesterday"),
            )
            score += delta
            reasons.extend(items)
        except (ValueError, TypeError):
            pass

    return score, reasons


def score_onchain_mcp(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Optional MCP market_sentiment supplement (not ValueScan chain APIs)."""
    score = 0.0
    reasons: List[str] = []
    extra = (data.get("onchain") or {}).get("extra") or {}

    # --- Sentiment label ---
    sentiment = extra.get("sentiment")
    if sentiment:
        s_str = str(sentiment).lower() if not isinstance(sentiment, dict) else str(sentiment.get("label", "")).lower()
        if "bull" in s_str or "positive" in s_str:
            score += 8
            reasons.append(f"MCP 情绪: {sentiment}，偏乐观")
        elif "bear" in s_str or "negative" in s_str:
            score -= 8
            reasons.append(f"MCP 情绪: {sentiment}，偏悲观")

    # --- Fund flows ---
    fund_flows = extra.get("fund_flows")
    if fund_flows is not None:
        delta, reason = _score_fund_flows(fund_flows)
        score += delta
        if reason:
            reasons.append(reason)

    # --- Summary ---
    onchain_summary = (data.get("onchain") or {}).get("summary", "")
    if onchain_summary:
        reasons.append(f"MCP 情绪摘要: {onchain_summary[:200]}")

    return score, reasons


def _score_fund_flows(fund_flows) -> Tuple[float, str]:
    if isinstance(fund_flows, dict):
        net = fund_flows.get("net") or fund_flows.get("netFlow") or fund_flows.get("net_inflow")
        if net is not None:
            try:
                return (6, "资金面净流入，买盘活跃") if float(net) > 0 else (-6, "资金面净流出，卖压偏重")
            except (ValueError, TypeError):
                pass
        return 0, ""
    ff = str(fund_flows).lower()
    if "inflow" in ff or "positive" in ff:
        return 6, "资金面净流入"
    if "outflow" in ff or "negative" in ff:
        return -6, "资金面净流出"
    return 0, ""


def score_rsi(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """RSI overbought/oversold across timeframes."""
    score, reasons = 0.0, []
    for lbl, sig, w in _tf_sigs(data):
        rsi = sig.get("rsi")
        if rsi is None:
            continue
        if rsi >= 80:
            score -= 10 * w; reasons.append(f"{lbl} RSI {rsi:.1f}，严重超买，回调概率高")
        elif rsi >= 70:
            score -= 6 * w; reasons.append(f"{lbl} RSI {rsi:.1f}，超买区间，关注回调风险")
        elif rsi <= 20:
            score += 10 * w; reasons.append(f"{lbl} RSI {rsi:.1f}，严重超卖，反弹概率高")
        elif rsi <= 30:
            score += 6 * w; reasons.append(f"{lbl} RSI {rsi:.1f}，超卖区间，关注反弹机会")
        elif 45 <= rsi <= 55:
            reasons.append(f"{lbl} RSI {rsi:.1f}，多空均衡区")
    return score, reasons


def score_bollinger(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Bollinger Bands %B position and squeeze detection across timeframes."""
    score, reasons = 0.0, []
    for lbl, sig, w in _tf_sigs(data):
        pctb = sig.get("bbPctB")
        bbw = sig.get("bbWidth")
        if pctb is None:
            continue
        if pctb >= 100:
            score -= 6 * w; reasons.append(f"{lbl} 价格突破布林带上轨（%B {pctb:.0f}%），短期超买")
        elif pctb >= 80:
            score -= 3 * w; reasons.append(f"{lbl} 价格接近布林带上轨（%B {pctb:.0f}%），注意压力")
        elif pctb <= 0:
            score += 6 * w; reasons.append(f"{lbl} 价格跌破布林带下轨（%B {pctb:.0f}%），短期超卖")
        elif pctb <= 20:
            score += 3 * w; reasons.append(f"{lbl} 价格接近布林带下轨（%B {pctb:.0f}%），关注支撑")
        if bbw is not None and bbw < 2.5:
            reasons.append(f"{lbl} 布林带极度收窄（宽度 {bbw:.1f}%），即将选择方向")
    return score, reasons


def score_macd(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Score based on MACD line/signal relationship and histogram direction."""
    score = 0.0
    reasons: List[str] = []

    for lbl, sig, weight in _tf_sigs(data):
        macd_line = sig.get("macd")
        macd_signal = sig.get("macdSignal")
        macd_hist = sig.get("macdHistogram")
        if macd_line is None or macd_signal is None or macd_hist is None:
            continue

        if macd_line > macd_signal and macd_hist > 0:
            score += 5 * weight
            reasons.append(f"{lbl} MACD 位于信号线上方且柱体为正，动能偏多")
        elif macd_line < macd_signal and macd_hist < 0:
            score -= 5 * weight
            reasons.append(f"{lbl} MACD 位于信号线下方且柱体为负，动能偏空")
        elif macd_hist > 0:
            score += 2 * weight
            reasons.append(f"{lbl} MACD 柱体转正，短线动能改善")
        elif macd_hist < 0:
            score -= 2 * weight
            reasons.append(f"{lbl} MACD 柱体为负，短线动能承压")

    return score, reasons


def score_regime(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Market regime (trending/ranging/transitional) — highest timeframe only."""
    score, reasons = 0.0, []
    for lbl, sig, w in reversed(_tf_sigs(data)):  # 4h first
        regime = sig.get("regime", "unknown")
        if regime == "unknown":
            continue
        atr_pct = sig.get("atrPct")
        atr_str = f"（ATR% {atr_pct:.1f}%）" if atr_pct else ""
        if regime == "ranging":
            reasons.append(f"{lbl} 市场处于震荡区间{atr_str}，适合区间高抛低吸")
        elif regime == "trending":
            trend = sig.get("trend", "")
            dir_ = "上涨" if "bullish" in trend else "下跌" if "bearish" in trend else "运行"
            score += 4 if "bullish" in trend else -4 if "bearish" in trend else 0
            reasons.append(f"{lbl} 市场处于趋势行情{atr_str}，{dir_}趋势中，顺势操作为宜")
        else:
            reasons.append(f"{lbl} 市场处于过渡阶段，等待方向确认")
        break  # report highest timeframe only
    return score, reasons
def score_breakout(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Breakout beyond recent range with volume confirmation across timeframes."""
    score, reasons = 0.0, []
    for lbl, sig, w in _tf_sigs(data):
        bo = sig.get("breakout", "none")
        if bo == "none":
            continue
        vr = sig.get("volRatio", 1.0)
        vol_note = f"，成交量放大 {vr:.1f}x 确认" if vr >= 1.5 else "，成交量温和放大"
        strength = (12 if vr >= 1.5 else 7) * w
        if bo == "bullish":
            score += strength; reasons.append(f"{lbl} 价格向上突破前期高点{vol_note}，多头信号")
        elif bo == "bearish":
            score -= strength; reasons.append(f"{lbl} 价格向下跌破前期低点{vol_note}，空头信号")
    return score, reasons


def score_atr_volatility(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """ATR% — volatility expansion/contraction context."""
    score, reasons = 0.0, []
    for lbl, sig, w in _tf_sigs(data):
        atr_pct = sig.get("atrPct")
        if atr_pct is None:
            continue
        if atr_pct >= 5.0:
            reasons.append(f"{lbl} ATR% {atr_pct:.1f}% 波动放大，趋势/突破策略权重上升")
        elif atr_pct <= 1.0:
            reasons.append(f"{lbl} ATR% {atr_pct:.1f}% 波动极低，警惕假突破与窄幅震荡")
        elif atr_pct >= 3.0:
            score += 2 * w
        elif atr_pct <= 1.5:
            score -= 1 * w
    return score, reasons


def score_sma_spread(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """SMA20 vs SMA60 spread and price vs SMA structure."""
    score, reasons = 0.0, []
    for lbl, sig, w in _tf_sigs(data):
        close = sig.get("close")
        sma20 = sig.get("sma20")
        sma60 = sig.get("sma60")
        if not close or not sma20 or not sma60:
            continue
        try:
            close_f, s20, s60 = float(close), float(sma20), float(sma60)
        except (TypeError, ValueError):
            continue
        if s60 <= 0:
            continue
        spread_pct = (s20 - s60) / s60 * 100
        if spread_pct > 1.5 and close_f > s20:
            score += 5 * w
            reasons.append(f"{lbl} 收盘在 SMA20 上且 SMA20 高于 SMA60 {spread_pct:+.1f}%，结构偏多")
        elif spread_pct < -1.5 and close_f < s20:
            score -= 5 * w
            reasons.append(f"{lbl} 收盘在 SMA20 下且 SMA20 低于 SMA60 {spread_pct:+.1f}%，结构偏空")
        elif close_f < s20 < s60:
            score -= 3 * w
            reasons.append(f"{lbl} 价格在均线下方压制（<SMA20<SMA60）")
        elif close_f > s20 > s60:
            score += 3 * w
            reasons.append(f"{lbl} 价格在均线上方支撑（>SMA20>SMA60）")
    return score, reasons


def score_price_momentum(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Recent OHLCV candle momentum (15m/1h/4h)."""
    score, reasons = 0.0, []
    for lbl, sig, w in _tf_sigs(data):
        recent = sig.get("recentCandles") or []
        if len(recent) < 3:
            continue
        try:
            first_close = float(recent[0]["c"])
            last_close = float(recent[-1]["c"])
        except (KeyError, TypeError, ValueError):
            continue
        if first_close <= 0:
            continue
        chg = (last_close - first_close) / first_close * 100
        if chg >= 1.5:
            score += 6 * w
            reasons.append(f"{lbl} 近{len(recent)}根 K 线涨跌 {chg:+.2f}%，短线动能偏多")
        elif chg <= -1.5:
            score -= 6 * w
            reasons.append(f"{lbl} 近{len(recent)}根 K 线涨跌 {chg:+.2f}%，短线动能偏空")
        elif abs(chg) >= 0.5:
            reasons.append(f"{lbl} 近{len(recent)}根 K 线涨跌 {chg:+.2f}%，动能温和")
    return score, reasons


def score_derivatives(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Futures funding rate, OI context, spot-futures basis."""
    d = data.get("derivatives") or {}
    if not d:
        return 0, []
    score, reasons = 0.0, []
    funding = d.get("fundingRate")
    pfunding = d.get("predictedFundingRate")
    market = data.get("market") or {}
    spot = market.get("last")
    fut = d.get("futuresLast")
    try:
        if funding is not None:
            fr = float(funding)
            if fr >= 0.0003:
                score -= 5
                reasons.append(f"资金费率 {fr:+.4%} 偏高，多头拥挤/回调风险")
            elif fr <= -0.0001:
                score += 4
                reasons.append(f"资金费率 {fr:+.4%} 为负，空头支付费率，反弹环境")
            elif fr > 0:
                reasons.append(f"资金费率 {fr:+.4%} 温和为正")
        if pfunding is not None and funding is not None:
            if float(pfunding) < float(funding) - 0.00005:
                reasons.append("预测资金费率下行，拥挤度或缓解")
        if spot and fut:
            basis = (float(fut) - float(spot)) / float(spot) * 100
            if basis >= 0.15:
                score -= 3
                reasons.append(f"现货-合约基差 {basis:+.3f}%，合约溢价偏高")
            elif basis <= -0.05:
                score += 2
                reasons.append(f"现货-合约基差 {basis:+.3f}%，现货相对偏强")
        oi = d.get("openInterest")
        if oi is not None:
            reasons.append(f"持仓量 OI {float(oi):,.0f}")
    except (TypeError, ValueError):
        pass
    return score, reasons


def score_microstructure(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Order book imbalance and taker buy/sell pressure."""
    micro = data.get("microstructure") or {}
    ob = micro.get("orderbook") or {}
    rt = micro.get("recentTrades") or {}
    if not ob and not rt:
        return 0, []
    score, reasons = 0.0, []
    imb = ob.get("imbalance")
    if imb is not None:
        try:
            imbalance = float(imb)
            if imbalance >= 0.15:
                score += 5
                reasons.append(f"盘口深度失衡 {imbalance:+.2f}，买盘更厚")
            elif imbalance <= -0.15:
                score -= 5
                reasons.append(f"盘口深度失衡 {imbalance:+.2f}，卖盘更厚")
        except (TypeError, ValueError):
            pass
    buy_ratio = rt.get("buyRatio")
    if buy_ratio is not None:
        try:
            br = float(buy_ratio)
            if br >= 0.58:
                score += 4
                reasons.append(f"逐笔主动买占比 {br:.1%}，短线买盘主导")
            elif br <= 0.42:
                score -= 4
                reasons.append(f"逐笔主动买占比 {br:.1%}，短线卖盘主导")
        except (TypeError, ValueError):
            pass
    spread_pct = ob.get("spreadPct")
    if spread_pct is not None:
        try:
            sp = float(spread_pct)
            if sp >= 0.08:
                reasons.append(f"点差 {sp:.3f}% 偏宽，流动性一般")
        except (TypeError, ValueError):
            pass
    return score, reasons


def score_kline_sr_proximity(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """K-line support/resistance proximity (same fields as LLM K线技术面)."""
    last, support, resistance = _resolve_levels(data)
    if not last:
        return 0, []
    score, reasons = 0.0, []
    if support and support > 0:
        dist = (last - support) / last * 100
        if dist <= 1.5:
            score += 6
            reasons.append(f"贴近 K 线支撑 {support:.4f}（距 {dist:.2f}%），反弹观察区")
        elif dist <= 3.5:
            score += 2
            reasons.append(f"靠近 K 线支撑 {support:.4f}（距 {dist:.2f}%）")
    if resistance and resistance > 0:
        dist = (resistance - last) / last * 100
        if dist <= 1.5:
            score -= 6
            reasons.append(f"贴近 K 线阻力 {resistance:.4f}（距 {dist:.2f}%），突破需放量")
        elif dist <= 3.5:
            score -= 2
            reasons.append(f"接近 K 线阻力 {resistance:.4f}（距 {dist:.2f}%）")
    return score, reasons


def score_multi_tf_alignment(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """15m/1h/4h/1d trend alignment — mirrors LLM 4h定方向/1h定执行纪律."""
    kline = data.get("kline") or {}
    tf_dirs: List[Tuple[str, str]] = []
    for tf, lbl in (("4hour", "4h"), ("1hour", "1h"), ("15min", "15m"), ("1day", "1d")):
        trend = str((kline.get(tf) or {}).get("trend") or "")
        if not trend or trend == "neutral":
            continue
        if "bull" in trend:
            tf_dirs.append((lbl, "bullish"))
        elif "bear" in trend:
            tf_dirs.append((lbl, "bearish"))
    if len(tf_dirs) < 2:
        return 0, []
    bulls = sum(1 for _, d in tf_dirs if d == "bullish")
    bears = sum(1 for _, d in tf_dirs if d == "bearish")
    labels = "/".join(f"{l}={'多' if d == 'bullish' else '空'}" for l, d in tf_dirs)
    if bears == 0 and bulls >= 2:
        return min(10, 4 + bulls), [f"多周期趋势共振偏多: {labels}"]
    if bulls == 0 and bears >= 2:
        return -min(10, 4 + bears), [f"多周期趋势共振偏空: {labels}"]
    h4 = next((d for l, d in tf_dirs if l == "4h"), None)
    h1 = next((d for l, d in tf_dirs if l == "1h"), None)
    if h4 and h1 and h4 != h1:
        return 0, [f"1h 与 4h 趋势冲突（{labels}），置信度应下调"]
    return 0, [f"多周期方向不一: {labels}"]


def score_market_depth(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """24h 行情深度：涨跌、成交额、买一卖一价差（LLM 行情段）。"""
    m = data.get("market") or {}
    if not m.get("last"):
        return 0, []
    score, reasons = 0.0, []
    change = float(m.get("changeRate") or 0)
    if change > 0.08:
        score += 4
        reasons.append(f"24h 强势 +{change * 100:.1f}%")
    elif change < -0.08:
        score -= 4
        reasons.append(f"24h 弱势 {change * 100:.1f}%")
    vol_val = float(m.get("volValue") or 0)
    if vol_val >= 50_000_000:
        reasons.append(f"24h 成交额 {vol_val / 1e6:.1f}M USDT，流动性充足")
    elif 0 < vol_val < 5_000_000:
        reasons.append(f"24h 成交额仅 {vol_val / 1e6:.2f}M USDT，流动性偏弱")
    buy, sell = m.get("buy"), m.get("sell")
    try:
        if buy and sell and float(buy) > 0:
            spread_pct = (float(sell) - float(buy)) / float(buy) * 100
            if spread_pct <= 0.03:
                score += 2
                reasons.append(f"买卖一价差 {spread_pct:.3f}%，盘口紧")
            elif spread_pct >= 0.12:
                score -= 1
                reasons.append(f"买卖一价差 {spread_pct:.3f}%，盘口较宽")
    except (TypeError, ValueError):
        pass
    return score, reasons


def _normalize_backtest_candle_signal(sig: Any) -> str:
    if not isinstance(sig, dict):
        return ""
    for key in ("side", "signal", "action", "direction"):
        raw = str(sig.get(key) or "").lower()
        if raw in {"buy", "long", "bullish", "bull", "weak_buy"}:
            return "bullish"
        if raw in {"sell", "short", "bearish", "bear", "weak_sell", "weak_short"}:
            return "bearish"
    return ""


def score_strategy_backtests(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """策略回测矩阵最新 K 线机械信号（LLM 策略回测矩阵段）。"""
    bundle = data.get("strategyBacktests") or {}
    if not bundle.get("available"):
        return 0, []
    strategies = [s for s in (bundle.get("strategies") or []) if s.get("ok")]
    if not strategies:
        return 0, []
    bull, bear = 0, 0
    bull_names: List[str] = []
    bear_names: List[str] = []
    for s in strategies:
        direction = _normalize_backtest_candle_signal(s.get("lastCandleSignal"))
        name = str(s.get("displayName") or s.get("name") or "")[:20]
        if direction == "bullish":
            bull += 1
            if name:
                bull_names.append(name)
        elif direction == "bearish":
            bear += 1
            if name:
                bear_names.append(name)
    total = bull + bear
    if total == 0:
        return 0, [f"回测矩阵 {len(strategies)} 策略，末根 K 线无方向信号"]
    score = 0.0
    reasons: List[str] = []
    if bull > bear and bull >= max(2, total * 0.55):
        score = min(8, bull - bear + 2)
        reasons.append(f"回测末信号 {bull}/{total} 策略偏多" + (f"（{', '.join(bull_names[:3])}）" if bull_names else ""))
    elif bear > bull and bear >= max(2, total * 0.55):
        score = -min(8, bear - bull + 2)
        reasons.append(f"回测末信号 {bear}/{total} 策略偏空" + (f"（{', '.join(bear_names[:3])}）" if bear_names else ""))
    else:
        reasons.append(f"回测末信号多空分散（多 {bull} / 空 {bear}）")
    return score, reasons


def score_quant_factors_technical(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """量化因子矩阵中价量/技术相关项（LLM 量化因子矩阵段，轻权重）。"""
    quant = data.get("quantFactors") or {}
    if not quant.get("available"):
        return 0, []
    score = 0.0
    reasons: List[str] = []
    agg = float(quant.get("aggregateScore") or 0)
    tech_kw = ("momentum", "volatility", "trend", "rsi", "macd", "volume", "price", "动量", "波动", "趋势", "量价")
    picked = 0
    for item in quant.get("topFactors") or []:
        if not isinstance(item, dict):
            continue
        cat = str(item.get("category") or "").lower()
        name = str(item.get("displayName") or item.get("name") or "")
        if not any(k in cat or k in name.lower() for k in tech_kw):
            continue
        try:
            fs = float(item.get("score") or 0)
        except (TypeError, ValueError):
            fs = 0.0
        if abs(fs) < 0.05:
            continue
        score += fs * 2
        reasons.append(f"量化·{name[:24]} {fs:+.2f}")
        picked += 1
        if picked >= 3:
            break
    if abs(agg) >= 0.12 and not reasons:
        score += agg * 3
        reasons.append(f"量化综合得分 {agg:+.3f}")
    return score, reasons


def score_candle_structure(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """近几根 K 线实体/影线结构（LLM OHLCV 价格行为）。"""
    score, reasons = 0.0, []
    for lbl, sig, w in _tf_sigs(data):
        if lbl not in ("15m", "1h"):
            continue
        recent = sig.get("recentCandles") or []
        if len(recent) < 3:
            continue
        last3 = recent[-3:]
        try:
            bodies = [float(c["c"]) - float(c["o"]) for c in last3]
            ranges = [float(c["h"]) - float(c["l"]) for c in last3 if float(c["h"]) > float(c["l"])]
        except (KeyError, TypeError, ValueError):
            continue
        if not ranges:
            continue
        upper_wicks = 0
        lower_wicks = 0
        for c in last3:
            o, h, l, cl = float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])
            rng = h - l
            if rng <= 0:
                continue
            if (h - max(o, cl)) / rng > 0.55:
                upper_wicks += 1
            if (min(o, cl) - l) / rng > 0.55:
                lower_wicks += 1
        if lower_wicks >= 2 and bodies[-1] > 0:
            score += 4 * w
            reasons.append(f"{lbl} 近3根下影线偏长+阳线，支撑拒绝下跌")
        if upper_wicks >= 2 and bodies[-1] < 0:
            score -= 4 * w
            reasons.append(f"{lbl} 近3根上影线偏长+阴线，阻力压制")
    return score, reasons


def score_public_chain_metrics(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """BTC public network metrics (blockchain.info / mempool) — technical macro, not VS chain."""
    score = 0.0
    reasons: List[str] = []
    metrics = data.get("onchainMetrics") or {}

    mempool = metrics.get("mempool") or {}
    mem_count = mempool.get("count", 0)
    if mem_count > 0:
        if mem_count > 150000:
            score += 3
            reasons.append(f"内存池拥堵（{mem_count:,} 笔待确认），链上活跃度高")
        elif mem_count > 80000:
            reasons.append(f"内存池正常偏高（{mem_count:,} 笔待确认）")
        elif mem_count < 10000:
            reasons.append(f"内存池清闲（{mem_count:,} 笔待确认），链上活跃度偏低")

    fees = metrics.get("fees") or {}
    fastest_fee = fees.get("fastest", 0)
    if fastest_fee > 0:
        if fastest_fee > 100:
            score += 2
            reasons.append(f"BTC 链上手续费偏高（最快 {fastest_fee} sat/vB），需求旺盛")
        elif fastest_fee < 5:
            reasons.append(f"BTC 链上手续费极低（最快 {fastest_fee} sat/vB），链上需求清淡")

    network = metrics.get("network") or {}
    n_tx = network.get("nTx", 0)
    if n_tx > 400000:
        score += 2
        reasons.append(f"24h 链上交易 {n_tx:,} 笔，网络活跃度高")
    elif n_tx > 0 and n_tx < 200000:
        score -= 2
        reasons.append(f"24h 链上交易 {n_tx:,} 笔，网络活跃度偏低")

    diff_adj = metrics.get("difficultyAdj") or {}
    diff_change = diff_adj.get("difficultyChange")
    if diff_change is not None and diff_change != 0:
        if diff_change > 5:
            score += 2
            reasons.append(f"下次难度预计上调 {diff_change:.1f}%，矿工算力增长看好后市")
        elif diff_change < -5:
            score -= 2
            reasons.append(f"下次难度预计下调 {abs(diff_change):.1f}%，矿工算力下降需关注")

    messari = metrics.get("messari") or {}

    nvt = messari.get("nvt")
    if nvt is not None:
        if nvt > 150:
            score -= 4
            reasons.append(f"NVT 比率 {nvt:.1f}，网络估值相对链上交易量偏高")
        elif nvt < 40:
            score += 4
            reasons.append(f"NVT 比率 {nvt:.1f}，网络估值相对链上交易量偏低，或存在价值低估")

    mvrv = messari.get("mvrvRatio")
    if mvrv is not None:
        if mvrv > 3.5:
            score -= 6
            reasons.append(f"MVRV 比率 {mvrv:.2f}，市值远超已实现市值，市场可能过热")
        elif mvrv > 2.5:
            score -= 3
            reasons.append(f"MVRV 比率 {mvrv:.2f}，市场偏向过热区域")
        elif mvrv < 1.0:
            score += 6
            reasons.append(f"MVRV 比率 {mvrv:.2f}，市值低于已实现市值，处于低估区间")
        elif mvrv < 1.5:
            score += 3
            reasons.append(f"MVRV 比率 {mvrv:.2f}，市值接近已实现市值，估值合理偏低")

    active_addr = messari.get("activeAddresses")
    if active_addr is not None and active_addr > 0:
        if active_addr > 1000000:
            score += 2
            reasons.append(f"24h 活跃地址 {active_addr:,}，网络使用活跃")
        elif active_addr < 400000:
            score -= 1
            reasons.append(f"24h 活跃地址 {active_addr:,}，网络使用偏冷")

    return score, reasons


def _float_field(row: Dict[str, Any], *keys: str) -> float:
    for key in keys:
        if row.get(key) is not None:
            try:
                return float(row[key])
            except (TypeError, ValueError):
                continue
    return 0.0


def score_vs_large_transactions(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """ValueScan §3 大额交易 — exchange inflow vs outflow notional."""
    vs = data.get("valuescan") or {}
    txns = vs.get("largeTransactions") or []
    if not txns:
        return 0.0, []

    to_ex = from_ex = 0.0
    for row in txns[:20]:
        if not isinstance(row, dict):
            continue
        amount = _float_field(row, "amount")
        if amount <= 0:
            continue
        if str(row.get("toExchangeName") or "").strip():
            to_ex += amount
        if str(row.get("fromExchangeName") or "").strip():
            from_ex += amount

    if to_ex <= 0 and from_ex <= 0:
        return 0.0, [f"VS 大额链上交易 {len(txns)} 笔，暂无明确交易所流向标签"]

    score = 0.0
    reasons: List[str] = []
    if from_ex > to_ex * 1.2 and from_ex > 0:
        score += 4
        reasons.append(f"VS 大额交易偏流出交易所（≈${from_ex:,.0f}），提币/囤积偏多")
    elif to_ex > from_ex * 1.2 and to_ex > 0:
        score -= 4
        reasons.append(f"VS 大额交易偏流入交易所（≈${to_ex:,.0f}），抛压/卖盘风险")
    else:
        reasons.append(f"VS 大额交易交易所流向均衡（入 ${to_ex:,.0f} / 出 ${from_ex:,.0f}）")
    return score, reasons


def score_vs_holder_list(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """ValueScan §3 持币地址 — top holder concentration."""
    vs = data.get("valuescan") or {}
    holders = vs.get("holderList") or []
    if not holders:
        return 0.0, []

    balances: List[float] = []
    for row in holders[:10]:
        if not isinstance(row, dict):
            continue
        bal = _float_field(row, "balance", "holdAmount", "amount")
        if bal > 0:
            balances.append(bal)

    if len(balances) < 2:
        return 0.0, [f"VS 持币地址 Top{len(holders)}，样本不足"]

    total = sum(balances)
    top_share = balances[0] / total if total else 0.0
    score = 0.0
    reasons: List[str] = []
    if top_share >= 0.45:
        score -= 3
        reasons.append(f"VS 持币集中度高：Top1 占 Top10 余额 {top_share * 100:.1f}%")
    elif top_share <= 0.2:
        score += 2
        reasons.append(f"VS 持币分布较分散：Top1 占 Top10 余额 {top_share * 100:.1f}%")
    else:
        reasons.append(f"VS 持币集中度中等：Top1 占 Top10 余额 {top_share * 100:.1f}%")
    return score, reasons


def _trend_delta(points: List[Dict[str, Any]], value_keys: Tuple[str, ...]) -> Optional[float]:
    vals: List[float] = []
    for row in points:
        if not isinstance(row, dict):
            continue
        v = _float_field(row, *value_keys)
        if v != 0:
            vals.append(v)
    if len(vals) < 2:
        return None
    first, last = vals[0], vals[-1]
    if first == 0:
        return None
    return (last - first) / abs(first) * 100


def score_vs_holder_trends(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """ValueScan §3 地址四维趋势（Top 持仓地址）."""
    vs = data.get("valuescan") or {}
    trends = vs.get("topHolderAddressTrends") or []
    if not trends:
        return 0.0, []

    score = 0.0
    reasons: List[str] = []
    accum = distrib = 0
    for entry in trends[:3]:
        if not isinstance(entry, dict):
            continue
        addr = str(entry.get("address") or "")[:10]
        bal_chg = _trend_delta(entry.get("balanceTrend") or [], ("balance",))
        hold_chg = _trend_delta(entry.get("holdTrend") or [], ("holdCost", "cost", "balance"))
        if bal_chg is not None and bal_chg > 5:
            accum += 1
            reasons.append(f"VS 地址 {addr}… 余额趋势 +{bal_chg:.1f}%")
        elif bal_chg is not None and bal_chg < -5:
            distrib += 1
            reasons.append(f"VS 地址 {addr}… 余额趋势 {bal_chg:.1f}%")
        if hold_chg is not None and hold_chg > 3:
            accum += 1
        elif hold_chg is not None and hold_chg < -3:
            distrib += 1

    if accum > distrib:
        score += min(5, accum * 2)
    elif distrib > accum:
        score -= min(5, distrib * 2)
    if not reasons:
        reasons.append(f"VS Top{len(trends)} 地址链上趋势平稳")
    return score, reasons


# Backward-compatible alias
score_onchain = score_onchain_mcp
score_onchain_metrics = score_public_chain_metrics


def score_vs_fund(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Score based on ValueScan real-time fund accumulation and fund/market-cap ratio."""
    score = 0.0
    reasons: List[str] = []
    vs = data.get("valuescan") or {}
    fund = vs.get("fund") or {}
    ratio = vs.get("fundRatio") or {}

    spots = fund.get("spotGoodsList") or []
    for item in spots:
        time_range = item.get("timeRange", "")
        inflow = item.get("tradeInflow")
        if inflow is None:
            continue
        inflow = float(inflow)
        if time_range in ("H1", "h1"):
            if abs(inflow) > 500_000:
                delta = 4 if inflow > 0 else -4
                score += delta
                direction = "净流入" if inflow > 0 else "净流出"
                reasons.append(f"VS 1h 现货资金{direction} ${abs(inflow):,.0f}")
        elif time_range in ("D1", "d1"):
            if abs(inflow) > 5_000_000:
                delta = 6 if inflow > 0 else -6
                score += delta
                direction = "净流入" if inflow > 0 else "净流出"
                reasons.append(f"VS 24h 现货资金{direction} ${abs(inflow):,.0f}")

    total_inflow = ratio.get("totalTradeInflow")
    if total_inflow is not None:
        total_inflow = float(total_inflow)
        mcr = ratio.get("totalMarketCapRatio")
        if mcr is not None and float(mcr) > 0.001:
            score += 3
            reasons.append(f"VS 资金/市值比 {float(mcr) * 100:.4f}%，资金流入占比较高")
        if abs(total_inflow) > 10_000_000:
            delta = 4 if total_inflow > 0 else -4
            score += delta
            direction = "净流入" if total_inflow > 0 else "净流出"
            reasons.append(f"VS 总计（现货+合约）{direction} ${abs(total_inflow):,.0f}")

    return score, reasons


def score_vs_sentiment(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Score based on ValueScan social media sentiment ratios."""
    score = 0.0
    reasons: List[str] = []
    vs = data.get("valuescan") or {}
    sentiment = vs.get("sentiment") or {}

    bullish = sentiment.get("bullishRatio")
    bearish = sentiment.get("bearishRatio")
    if bullish is not None and bearish is not None:
        bull_pct = float(bullish) * 100
        bear_pct = float(bearish) * 100
        if bull_pct >= 60:
            score += 6
            reasons.append(f"VS 社媒情绪偏多: 看多 {bull_pct:.1f}% vs 看空 {bear_pct:.1f}%")
        elif bull_pct >= 50:
            score += 3
            reasons.append(f"VS 社媒情绪温和偏多: 看多 {bull_pct:.1f}% vs 看空 {bear_pct:.1f}%")
        elif bear_pct >= 60:
            score -= 6
            reasons.append(f"VS 社媒情绪偏空: 看空 {bear_pct:.1f}% vs 看多 {bull_pct:.1f}%")
        elif bear_pct >= 50:
            score -= 3
            reasons.append(f"VS 社媒情绪温和偏空: 看空 {bear_pct:.1f}% vs 看多 {bull_pct:.1f}%")
        else:
            reasons.append(f"VS 社媒情绪均衡: 看多 {bull_pct:.1f}% / 看空 {bear_pct:.1f}%")

    return score, reasons


def score_vs_ai_signals(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Score based on whether the token appears in VS AI opportunity / risk / fund anomaly lists."""
    score = 0.0
    reasons: List[str] = []
    vs = data.get("valuescan") or {}
    ai = vs.get("aiSignals") or {}

    if ai.get("chance"):
        item = ai["chance"]
        score += 8
        cost = item.get("cost")
        deviation = item.get("deviation")
        note_parts = []
        if cost:
            note_parts.append(f"主力成本 ${float(cost):,.0f}")
        if deviation:
            note_parts.append(f"偏离 {float(deviation):.1f}%")
        note = f"（{'，'.join(note_parts)}）" if note_parts else ""
        reasons.append(f"VS AI 智选: 该币种出现在【机会】信号列表{note}")

    if ai.get("risk"):
        item = ai["risk"]
        score -= 8
        reasons.append("VS AI 智选: 该币种出现在【风险】信号列表，注意风险")

    if ai.get("funds"):
        item = ai["funds"]
        inflow_data = (
            item.get("fundsCoinTradeDataV1Vos")
            or item.get("chanceCoinTradeDataV1Vos")
            or []
        )
        m1 = next((t for t in inflow_data if t.get("timeRange") == "M1"), None)
        if m1:
            net = float(m1.get("tradeInflow") or 0)
            if net > 0:
                score += 4
                reasons.append(f"VS AI: 资金异动信号，月净流入 ${net:,.0f}")
            elif net < 0:
                score -= 4
                reasons.append(f"VS AI: 资金异动信号，月净流出 ${abs(net):,.0f}")
        else:
            reasons.append("VS AI: 该币种出现资金异动信号")

    return score, reasons


def score_vs_whale(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Score based on VS whale position cost vs current price and 7-day accumulation/distribution trend."""
    score = 0.0
    reasons: List[str] = []
    vs = data.get("valuescan") or {}
    whale_cost = vs.get("whaleCost") or []

    if not whale_cost:
        return score, reasons

    # --- Latest cost vs current price (PnL check) ---
    latest = next((item for item in reversed(whale_cost) if isinstance(item, dict) and item.get("cost")), {})
    cost = latest.get("cost")
    price = latest.get("price")
    if cost is not None and price is not None:
        cost_f, price_f = float(cost), float(price)
        if cost_f > 0:
            pnl_pct = (price_f - cost_f) / cost_f * 100
            if pnl_pct < -10:
                score += 5
                reasons.append(f"VS 主力成本 ${cost_f:,.2f}，当前浮亏 {pnl_pct:.1f}%，主力或有护盘动力")
            elif pnl_pct < 0:
                score += 2
                reasons.append(f"VS 主力成本 ${cost_f:,.2f}，当前小幅浮亏 {pnl_pct:.1f}%")
            elif pnl_pct > 30:
                score -= 5
                reasons.append(f"VS 主力成本 ${cost_f:,.2f}，当前浮盈 {pnl_pct:.1f}%，注意获利了结风险")
            elif pnl_pct > 15:
                score -= 2
                reasons.append(f"VS 主力成本 ${cost_f:,.2f}，当前浮盈 {pnl_pct:.1f}%")
            else:
                reasons.append(f"VS 主力成本 ${cost_f:,.2f}，浮盈 {pnl_pct:.1f}%，持仓成本区间内")

    # --- 7-day cost trend: rising = accumulation, falling = distribution ---
    valid_items = [item for item in whale_cost if isinstance(item, dict) and item.get("cost")]
    if len(valid_items) >= 3:
        costs = [float(item["cost"]) for item in valid_items[-7:]]
        first_cost, last_cost = costs[0], costs[-1]
        if first_cost > 0:
            trend_pct = (last_cost - first_cost) / first_cost * 100
            if trend_pct > 3:
                score += 3
                reasons.append(f"VS 主力成本近期持续抬升 {trend_pct:+.1f}%，主力在持续建仓（积累）")
            elif trend_pct < -3:
                score -= 3
                reasons.append(f"VS 主力成本近期持续下降 {trend_pct:+.1f}%，主力或在减仓（发散）")

    return score, reasons


def score_vs_support_resistance(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Score based on VS AI dense-area support/resistance proximity."""
    score = 0.0
    reasons: List[str] = []
    vs = data.get("valuescan") or {}
    sr_list = vs.get("supportResistance") or []
    market = data.get("market") or {}
    current_price = market.get("last", 0)

    if not sr_list or not current_price:
        return score, reasons

    prices = [float(item.get("price", 0)) for item in sr_list if item.get("price")]
    if not prices:
        return score, reasons

    supports = sorted([p for p in prices if p <= current_price], reverse=True)
    resistances = sorted([p for p in prices if p > current_price])

    if supports:
        nearest_sup = supports[0]
        dist_pct = (current_price - nearest_sup) / current_price * 100
        if dist_pct < 2:
            score += 4
            reasons.append(f"VS 密集成交区支撑 ${nearest_sup:,.0f} 距当前价仅 {dist_pct:.1f}%，支撑较强")
        elif dist_pct < 5:
            score += 2
            reasons.append(f"VS 最近支撑位 ${nearest_sup:,.0f}（距 {dist_pct:.1f}%）")

    if resistances:
        nearest_res = resistances[0]
        dist_pct = (nearest_res - current_price) / current_price * 100
        if dist_pct < 2:
            score -= 4
            reasons.append(f"VS 密集成交区压力 ${nearest_res:,.0f} 距当前价仅 {dist_pct:.1f}%，注意阻力")
        elif dist_pct < 5:
            score -= 2
            reasons.append(f"VS 最近压力位 ${nearest_res:,.0f}（距 {dist_pct:.1f}%）")

    return score, reasons


def score_vs_price_indicators(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Score based on VS price indicator bull/bear signal ratio."""
    score = 0.0
    reasons: List[str] = []
    vs = data.get("valuescan") or {}
    indicators = vs.get("priceIndicators") or []

    if not indicators:
        return score, reasons

    recent = indicators[:20]
    bull = sum(1 for i in recent if i.get("priceMarketType") == 1)
    bear = sum(1 for i in recent if i.get("priceMarketType") == 2)
    total = bull + bear
    if total == 0:
        return score, reasons

    bull_ratio = bull / total
    if bull_ratio >= 0.7:
        score += 6
        reasons.append(f"VS 价格指标偏多: 近期 {bull}/{total} 条看多信号 ({bull_ratio * 100:.0f}%)")
    elif bull_ratio >= 0.55:
        score += 3
        reasons.append(f"VS 价格指标温和偏多: {bull}/{total} 条看多信号 ({bull_ratio * 100:.0f}%)")
    elif bull_ratio <= 0.3:
        score -= 6
        reasons.append(f"VS 价格指标偏空: 近期 {bear}/{total} 条看空信号 ({(1 - bull_ratio) * 100:.0f}%)")
    elif bull_ratio <= 0.45:
        score -= 3
        reasons.append(f"VS 价格指标温和偏空: {bear}/{total} 条看空信号 ({(1 - bull_ratio) * 100:.0f}%)")
    else:
        reasons.append(f"VS 价格指标多空均衡: 看多 {bull} / 看空 {bear}")

    return score, reasons


def score_vs_token_flow(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Score based on VS token-level fund flow (net inflow/outflow and spot-futures convergence)."""
    score = 0.0
    reasons: List[str] = []
    vs = data.get("valuescan") or {}
    flow = vs.get("tokenFlow") or {}

    if not flow:
        return score, reasons

    # Normalise to a flat dict if the API returns a list (take latest entry)
    if isinstance(flow, list):
        flow = flow[-1] if flow and isinstance(flow[-1], dict) else {}

    # Net inflow — try multiple common field names
    net = (
        flow.get("netInflow")
        or flow.get("net")
        or flow.get("netFlow")
        or flow.get("totalNetInflow")
    )
    spot_net = flow.get("spotNetInflow") or flow.get("spotNet") or flow.get("spotInflow")
    futures_net = (
        flow.get("futuresNetInflow")
        or flow.get("futuresNet")
        or flow.get("contractNetInflow")
    )

    if net is not None:
        try:
            net_f = float(net)
        except (ValueError, TypeError):
            net_f = 0.0
        if abs(net_f) > 1_000_000:
            delta = 5 if net_f > 0 else -5
            score += delta
            reasons.append(
                f"VS 代币资金{'净流入' if net_f > 0 else '净流出'} ${abs(net_f):,.0f}，"
                f"{'主动买盘明显' if net_f > 0 else '卖压较重'}"
            )
        elif abs(net_f) > 100_000:
            delta = 2 if net_f > 0 else -2
            score += delta
            reasons.append(f"VS 代币资金温和{'净流入' if net_f > 0 else '净流出'} ${abs(net_f):,.0f}")

    # Spot-futures convergence check
    if spot_net is not None and futures_net is not None:
        try:
            s_f, f_f = float(spot_net), float(futures_net)
            if s_f > 0 and f_f > 0:
                score += 2
                reasons.append(
                    f"VS 现货与合约资金同步净流入（现货 ${s_f:,.0f}·合约 ${f_f:,.0f}），多头共振"
                )
            elif s_f < 0 and f_f < 0:
                score -= 2
                reasons.append(
                    f"VS 现货与合约资金同步净流出（现货 ${s_f:,.0f}·合约 ${f_f:,.0f}），空头共振"
                )
            elif s_f > 0 > f_f:
                reasons.append("VS 现货资金流入但合约资金流出，多空分歧，勿追高")
            elif s_f < 0 < f_f:
                reasons.append("VS 合约资金流入但现货资金流出，需关注是否为空单对冲")
        except (ValueError, TypeError):
            pass

    return score, reasons


def score_news(data: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Score based on keyword sentiment in news headlines."""
    news_list = data.get("news") or []
    if not news_list:
        return 0, []

    pos = neg = 0
    for item in news_list:
        text = ((item.get("title") or "") + " " + (item.get("body") or "")).lower()
        if any(kw in text for kw in _POSITIVE_NEWS_KW):
            pos += 1
        if any(kw in text for kw in _NEGATIVE_NEWS_KW):
            neg += 1

    if pos > neg and pos >= 2:
        return min(10, pos * 3), [f"消息面偏多: {pos} 条正面消息 vs {neg} 条负面消息"]
    if neg > pos and neg >= 2:
        return -min(10, neg * 3), [f"消息面偏空: {neg} 条负面消息 vs {pos} 条正面消息"]
    return 0, [f"消息面中性: {len(news_list)} 条新闻，无明显多空倾向"]


# ---------------------------------------------------------------------------
# Default scorer pipeline
# ---------------------------------------------------------------------------
# 与 LLM 信号分析上下文对齐的技术面 scorer 列表（见 llm_signal_analyzer._build_context）
TECHNICAL_SCORERS_FOR_LLM: List[Scorer] = [
    score_kline,
    score_rsi,
    score_bollinger,
    score_macd,
    score_regime,
    score_breakout,
    score_kline_sr_proximity,
    score_multi_tf_alignment,
    score_sma_spread,
    score_atr_volatility,
    score_price_momentum,
    score_candle_structure,
    score_market,
    score_market_depth,
    score_derivatives,
    score_microstructure,
    score_fear_greed,
    score_public_chain_metrics,
    score_strategy_backtests,
    score_quant_factors_technical,
]

# 门禁「资金」维：链上筹码 + 交易所资金/情绪（去重后合并计分，不与技术价量重复）
CAPITAL_SCORERS_FOR_GATE: List[Scorer] = [
    score_vs_token_flow,
    score_vs_whale,
    score_vs_large_transactions,
    score_vs_holder_list,
    score_vs_holder_trends,
    score_onchain_mcp,
    score_vs_fund,
    score_vs_sentiment,
    score_vs_ai_signals,
]

DEFAULT_SCORERS: List[Scorer] = [
    *TECHNICAL_SCORERS_FOR_LLM,
    score_news,
    *CAPITAL_SCORERS_FOR_GATE,
    # 仅作规则引擎补充证据，不参与分维门禁
    score_vs_support_resistance,
    score_vs_price_indicators,
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class SignalResult:
    signal: SignalLevel = "NEUTRAL"
    label: str = "中性观望"
    score: float = 0
    confidence: float = 0
    reasons: List[str] = field(default_factory=list)
    summary: str = ""
    trade_plan: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def compute_signal(
    data: Dict[str, Any],
    scorers: List[Scorer] | None = None,
) -> SignalResult:
    """
    Run all scorers against aggregated data, produce a SignalResult.
    """
    all_reasons: List[str] = []
    total = 0.0
    for scorer in (scorers or DEFAULT_SCORERS):
        try:
            delta, reasons = scorer(data)
            total += delta
            all_reasons.extend(reasons)
        except Exception:
            logger.exception("scorer %s failed", scorer.__name__)

    total = max(-100, min(100, total))
    confidence = min(95, abs(total))

    signal = label = ""
    for threshold, sig, lbl in SIGNAL_THRESHOLDS:
        if total >= threshold:
            signal, label = sig, lbl
            break

    trade_plan = _build_trade_plan(data, signal)
    summary = _build_summary(data, signal, label, confidence, total, all_reasons, trade_plan)

    return SignalResult(
        signal=signal, label=label, score=total, confidence=confidence,
        reasons=all_reasons, summary=summary, trade_plan=trade_plan,
    )


# ---------------------------------------------------------------------------
# Summary / trade plan builders
# ---------------------------------------------------------------------------
def _build_summary(
    data: Dict, signal: str, label: str, confidence: float, score: float,
    reasons: List[str], trade_plan: Dict[str, Any],
) -> str:
    sym = data.get("symbol", "?")
    change = (data.get("market") or {}).get("changeRate", 0)
    vs = data.get("valuescan") or {}
    last, support, resistance = _resolve_levels(data)
    lines = [
        f"【{sym} 综合信号: {label}】(置信度 {confidence:.1f}%  ·  综合得分 {'+' if score >= 0 else ''}{score:.0f})",
        "",
        f"当前价格: {last:.6g} USDT" if last else None,
        f"24h 涨跌: {'+' if change >= 0 else ''}{change * 100:.2f}%",
        f"支撑位: {support:.6g} | 阻力位: {resistance:.6g}" if support and resistance else None,
    ]

    whale_cost = vs.get("whaleCost") or []
    if whale_cost:
        wc = whale_cost[-1] if isinstance(whale_cost[-1], dict) else {}
        wc_cost = wc.get("cost")
        if wc_cost:
            lines.append(f"主力成本: {float(wc_cost):.6g} USDT")

    lines += ["", "--- 分析依据 ---"]
    lines.extend(f"{i}. {r}" for i, r in enumerate(reasons[:15], 1))

    plan = trade_plan
    if signal in ("BUY", "WEAK_BUY") and last > 0:
        lines += [
            "", "--- 交易计划（仅供参考） ---",
            f"入场区间: {plan['entryLow']:.6g} ~ {plan['entryHigh']:.6g}",
            f"止损位: {plan['stop']:.6g}",
            f"第一目标: {plan['target1']:.6g}",
            f"第二目标: {plan['target2']:.6g}",
            f"建议仓位: {'15~25%' if signal == 'BUY' else '8~15%'}",
            "失效条件: 跌破止损位且 1h 放量确认",
        ]
    elif signal in ("SELL", "WEAK_SELL") and last > 0:
        lines += [
            "", "--- 风险提示 ---",
            f"关键支撑: {support:.6g}，若跌破则可能加速下跌",
            f"反弹阻力: {resistance:.6g}",
            "建议: 减仓或设置止损保护，等待趋势明朗化",
        ]
    else:
        lines += [
            "", "--- 操作建议 ---",
            "多空信号不明确，建议观望等待方向选择",
            f"关注区间: {support:.6g} ~ {resistance:.6g}" if support and resistance else None,
        ]

    return "\n".join(l for l in lines if l is not None)


def _build_trade_plan(data: Dict, signal: str) -> Dict[str, Any]:
    """
    Context-aware trade plan: entry zone, ATR-based stop, resistance-anchored targets.
    Entry types: breakout | oversold_bounce | pullback | market (default)
    """
    kline = data.get("kline") or {}
    vs = data.get("valuescan") or {}
    last, support, resistance = _resolve_levels(data)

    tf4h = kline.get("4hour") or {}
    tf1h = kline.get("1hour") or {}
    tf_main = tf4h or tf1h
    sma20 = tf_main.get("sma20") or last
    atr = tf1h.get("atr") or tf4h.get("atr") or (last * 0.01 if last else 0)
    breakout = tf_main.get("breakout", "none")
    bb_lower = tf1h.get("bbLower") or tf4h.get("bbLower") or support
    rsi = tf1h.get("rsi") or tf4h.get("rsi") or 50

    vs_sr = vs.get("supportResistance") or []
    vs_supports_all: List[float] = []
    vs_resistances_all: List[float] = []
    if vs_sr and last:
        ps = [float(i.get("price", 0)) for i in vs_sr if i.get("price")]
        vs_supports_all = sorted([p for p in ps if p < last], reverse=True)
        vs_resistances_all = sorted([p for p in ps if p >= last])
    # Whale cost as additional support anchor for pullback entries
    whale_cost_price: float = 0.0
    whale_cost_list = vs.get("whaleCost") or []
    if whale_cost_list:
        wc_last = next(
            (item for item in reversed(whale_cost_list) if isinstance(item, dict) and item.get("cost")), None
        )
        if wc_last:
            whale_cost_price = float(wc_last["cost"])

    # --- Entry zone ---
    is_breakout = breakout == "bullish" and signal in ("BUY", "WEAK_BUY")
    is_oversold = (rsi is not None) and rsi <= 35 and signal in ("BUY", "WEAK_BUY")
    is_pullback = signal in ("BUY", "WEAK_BUY") and not is_breakout and not is_oversold

    if is_breakout:
        # Buy the breakout: enter around current price, stop below breakout level
        entry_low = last * 0.998
        entry_high = last * 1.006
        stop = max(support * 0.997 if support else 0, last - 1.5 * atr) if atr else support * 0.997
    elif is_oversold:
        # Oversold bounce: enter near BB lower / support zone
        bb_entry = min(bb_lower, last) if bb_lower and bb_lower > 0 else last
        entry_low = bb_entry * 0.998
        entry_high = last * 1.002
        stop = (support - atr) if (support and atr) else support * 0.993
    elif is_pullback:
        # Pullback to SMA20 or support: offer entry below current market price
        pullback_anchor = max(
            sma20 if sma20 else 0,
            support if support else 0,
            whale_cost_price if (whale_cost_price and support < whale_cost_price < last) else 0,
        ) or last
        entry_low = pullback_anchor * 0.998
        entry_high = min(last, pullback_anchor * 1.015)
        stop = (support - atr) if (support and atr) else support * 0.993
    else:
        # Baseline / sell-side reference
        entry_low = last * 0.995 if last else 0
        entry_high = last * 1.003 if last else 0
        stop = (support - atr) if (support and atr) else (support * 0.997 if support else last * 0.98)

    # --- Target calculation anchored to actual resistance levels ---
    if vs_resistances_all:
        target1 = vs_resistances_all[0]
        target2 = vs_resistances_all[1] if len(vs_resistances_all) >= 2 else (
            last + 3.0 * atr if atr else last * 1.05
        )
    else:
        target1 = resistance * 0.998 if resistance else (last + 1.5 * atr if atr else last * 1.02)
        target2 = last + 3.0 * atr if atr else last * 1.04

    if signal in ("SELL", "WEAK_SELL") and last:
        entry_low = last * 0.997
        entry_high = last * 1.005
        stop = resistance * 1.003 if resistance else (last + 1.5 * atr if atr else last * 1.02)
        target1 = support * 1.002 if support else (last - 2.0 * atr if atr else last * 0.98)
        target2 = max(0, last - 3.0 * atr) if atr else last * 0.96

    def _r(v: float) -> float:
        return round(v, 8) if v else 0

    return {
        "support": _r(support),
        "resistance": _r(resistance),
        "atr": _r(atr),
        "entryLow": _r(entry_low),
        "entryHigh": _r(entry_high),
        "stop": _r(stop),
        "target1": _r(target1),
        "target2": _r(target2),
        "entryType": "breakout" if is_breakout else "oversold_bounce" if is_oversold else "pullback" if is_pullback else "market",
    }
