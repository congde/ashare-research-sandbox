# -*- coding: utf-8 -*-
"""
LLM-based signal analyzer.

Delegates signal computation to a large language model via structured output,
replacing the rule-based scorer pipeline in signal_analyzer.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import json_repair
try:
    from openai import AuthenticationError
except Exception:  # pragma: no cover - keep import-safe in test/mocked envs
    class AuthenticationError(Exception):
        pass

from llm.llm import DefaultLLM
from web.api.signal_schema import (
    TradePlan, EngineMeta, ConsensusBlock, ScoreBreakdown, KeyLevels,
    ExecutionPlan, AnalysisBlock, FactorBlock, FactorsBlock, RiskItem,
    ScenarioItem, DataQuality, CalibrationBlock, DebugBlock, SignalOutput,
    LLMModel, TradingAgentsDebateBlock,
)
from web.config import config

logger = logging.getLogger(__name__)


_DISPLAY_LABELS: Dict[str, Dict[str, str]] = {
    "bias": {
        "bullish": "偏多",
        "bearish": "偏空",
        "neutral": "中性",
    },
    "market_state": {
        "trend_continuation": "趋势延续",
        "trend_continuation_near_resistance": "趋势延续但接近压力",
        "range_rebound": "区间反弹",
        "range_breakdown_risk": "区间下破风险",
        "breakout_confirmation": "突破确认",
        "false_breakout_risk": "假突破风险",
        "uncertain": "方向尚不明朗",
    },
    "horizon": {
        "intraday": "日内",
        "intraday_swing": "日内到波段",
        "swing": "波段",
    },
    "execution_readiness": {
        "ready": "可执行",
        "watch_pullback": "等待回踩",
        "wait_breakout": "等待突破确认",
        "avoid": "暂不参与",
        "wait": "继续观察",
    },
    "consensus_strength": {
        "weak": "较弱",
        "medium": "中等",
        "strong": "较强",
    },
    "factor_direction": {
        "bullish": "偏多",
        "bearish": "偏空",
        "neutral": "中性",
    },
    "position_size": {
        "small": "轻仓",
        "medium": "中等仓位",
        "large": "重仓",
    },
    "risk_severity": {
        "low": "低",
        "medium": "中",
        "high": "高",
    },
    "scenario_name": {
        "bull": "乐观情景",
        "base": "基准情景",
        "bear": "悲观情景",
    },
    "source_status": {
        "ok": "完整",
        "partial": "部分缺失",
        "missing": "缺失",
    },
    "risk_type": {
        "setup_invalidation": "交易结构失效风险",
        "incomplete_data": "数据覆盖不足风险",
        "short_term_trend_conflicts_with_medium_term_trend": "短周期与中周期趋势冲突",
    },
    "conflict": {
        "short_term_trend_conflicts_with_medium_term_trend": "短周期趋势与中周期趋势存在冲突",
    },
}


def _map_display(category: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    mapped = _DISPLAY_LABELS.get(category, {}).get(text.lower())
    if mapped:
        return mapped
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return text
    return text.replace("_", " ")


def _localize_output(result: SignalOutput) -> SignalOutput:
    result.analysis.bias = _map_display("bias", result.analysis.bias)
    result.analysis.marketState = _map_display("market_state", result.analysis.marketState)
    result.analysis.horizon = _map_display("horizon", result.analysis.horizon)
    result.analysis.executionReadiness = _map_display("execution_readiness", result.analysis.executionReadiness)
    result.analysis.consensus.direction = _map_display("bias", result.analysis.consensus.direction)
    result.analysis.consensus.strength = _map_display("consensus_strength", result.analysis.consensus.strength)
    result.analysis.consensus.conflicts = [_map_display("conflict", item) for item in result.analysis.consensus.conflicts]
    result.analysis.execution.positionSize = _map_display("position_size", result.analysis.execution.positionSize)

    for factor in (
        result.factors.technical,
        result.factors.onchain,
        result.factors.news,
        result.factors.positioning,
    ):
        factor.direction = _map_display("factor_direction", factor.direction)

    for risk in result.risks:
        risk.type = _map_display("risk_type", risk.type)
        risk.severity = _map_display("risk_severity", risk.severity)

    for scenario in result.scenarios:
        scenario.name = _map_display("scenario_name", scenario.name)

    result.dataQuality.sourceStatus = {
        key: _map_display("source_status", value) for key, value in result.dataQuality.sourceStatus.items()
    }
    result.dataQuality.conflictFlags = [_map_display("conflict", item) for item in result.dataQuality.conflictFlags]
    return result


# ---------------------------------------------------------------------------
# LLM instance cache (keyed by model enum value)
# ---------------------------------------------------------------------------
_llm_cache: Dict[str, DefaultLLM] = {}


def _get_llm(model: LLMModel = LLMModel.DEEPSEEK_V4_PRO) -> tuple[DefaultLLM, str]:
    """Return (llm_instance, resolved_model_value), cached per model."""
    key = model.value
    if key not in _llm_cache:
        provider, model_name = key.split("/", 1)
        provider_config = config.llm_providers.get(provider)
        _llm_cache[key] = DefaultLLM(
            base_url=provider_config.base_url,
            api_key=provider_config.api_key,
            default_model_name=model_name,
            timeout=600,
        )
    return _llm_cache[key], key


# ---------------------------------------------------------------------------
# Context formatters (data → concise text for LLM)
# ---------------------------------------------------------------------------

def _fmt_realtime(data: Dict[str, Any]) -> str:
    rt = data.get("realtime") or {}
    if not isinstance(rt, dict) or not rt.get("available"):
        return "暂无"
    level1 = rt.get("level1") or {}
    ticker = rt.get("futuresTicker") or {}
    parts = [
        f"抓取时间: {rt.get('fetchedAt', '?')}",
        f"合约标记价: {rt.get('markPrice') or (rt.get('futuresMarkPrice') or {}).get('value') or '暂无'}",
        f"现货 L1: {level1.get('price', '暂无')} (买一 {level1.get('bestBid', '-')} / 卖一 {level1.get('bestAsk', '-')})",
        f"买卖价差: {level1.get('spreadPct', 0):.4f}%" if level1.get("spreadPct") is not None else None,
        f"合约最新: {ticker.get('last', '暂无')} (买一 {ticker.get('bestBid', '-')} / 卖一 {ticker.get('bestAsk', '-')})",
    ]
    return "\n".join(p for p in parts if p)


def _fmt_market(data: Dict[str, Any]) -> str:
    from web.api.realtime_market_bridge import resolve_live_mark_price

    m = data.get("market") or {}
    last = resolve_live_mark_price(data) or m.get("last", 0)
    change = m.get("changeRate", 0)
    parts = [
        f"币种: {data.get('symbol', '?')}",
        f"价格: {last} USDT" if last else "价格: 暂无",
        f"24h 涨跌: {change * 100:+.2f}%" if change else None,
        f"24h 高/低: {m.get('high', '-')} / {m.get('low', '-')}" if m.get("high") else None,
        f"24h 成交量: {float(m.get('vol', 0)):.2f} (币)" if m.get("vol") else None,
        f"24h 成交额: {float(m.get('volValue', 0)):.2f} USDT" if m.get("volValue") else None,
        f"买一/卖一: {m.get('buy', '-')} / {m.get('sell', '-')}" if m.get("buy") else None,
    ]
    return "\n".join(p for p in parts if p)


_KLINE_TF_LABEL: Dict[str, str] = {
    "1min": "1m", "3min": "3m", "5min": "5m", "15min": "15m", "30min": "30m",
    "1hour": "1h", "2hour": "2h", "4hour": "4h", "6hour": "6h", "8hour": "8h", "12hour": "12h",
    "1day": "1d", "1week": "1w",
}
_KLINE_TF_ORDER: tuple = (
    "1min", "3min", "5min", "15min", "30min",
    "1hour", "2hour", "4hour", "6hour", "8hour", "12hour", "1day", "1week",
)


def _fmt_kline(data: Dict[str, Any]) -> str:
    kline = data.get("kline") or {}
    if not kline:
        return "暂无"
    blocks = []
    _ord = set(_KLINE_TF_ORDER)
    tf_list = [t for t in _KLINE_TF_ORDER if t in kline] + [t for t in kline if t not in _ord]
    for tf in tf_list:
        s = kline.get(tf)
        if not s or not isinstance(s, dict):
            continue
        lbl = _KLINE_TF_LABEL.get(tf, tf)
        live_tag = " (L1已合并)" if s.get("liveMerged") else ""
        lines = [
            f"[{lbl}{live_tag}] 趋势={s.get('trend','?')} 行情={s.get('regime','?')} 突破={s.get('breakout','none')}",
            f"  RSI={s['rsi']:.1f}" if s.get("rsi") is not None else None,
            f"  布林%B={s['bbPctB']:.1f} 宽度={s['bbWidth']:.1f}%" if s.get("bbPctB") is not None else None,
            f"  量比={s.get('volRatio',1):.2f}x 区间位置={s.get('rangePos',50):.0f}%",
            f"  支撑={s.get('support')} 阻力={s.get('resistance')}" if s.get("support") else None,
            f"  SMA20={s.get('sma20')} SMA60={s.get('sma60')}" if s.get("sma20") else None,
            f"  ATR={s.get('atr')} ATR%={s.get('atrPct')}" if s.get("atr") else None,
            f"  布林上轨={s.get('bbUpper')} 布林下轨={s.get('bbLower')}" if s.get("bbUpper") else None,
        ]
        # Append recent candle OHLCV for price-action analysis
        recent = s.get("recentCandles") or []
        if recent:
            last_n = recent[-10:]  # Most recent 10 bars
            candle_lines = [f"  近{len(last_n)}根K线(O/H/L/C/V):"]
            for c in last_n:
                candle_lines.append(f"    {c['o']}/{c['h']}/{c['l']}/{c['c']} vol={c['v']}")
            # Compute price action summary
            if len(last_n) >= 3:
                first_close = last_n[0]["c"]
                last_close = last_n[-1]["c"]
                change_pct = (last_close - first_close) / first_close * 100 if first_close > 0 else 0
                max_high = max(c["h"] for c in last_n)
                min_low = min(c["l"] for c in last_n)
                amplitude = (max_high - min_low) / first_close * 100 if first_close > 0 else 0
                # Count consecutive up/down candles
                consec_dir = 0
                for i in range(len(last_n) - 1, 0, -1):
                    if last_n[i]["c"] > last_n[i]["o"]:
                        if consec_dir <= 0:
                            consec_dir = 1
                        else:
                            consec_dir += 1
                    elif last_n[i]["c"] < last_n[i]["o"]:
                        if consec_dir >= 0:
                            consec_dir = -1
                        else:
                            consec_dir -= 1
                    else:
                        break
                dir_label = f"连续{abs(consec_dir)}根{('阳线' if consec_dir > 0 else '阴线')}" if abs(consec_dir) >= 2 else "无明显连续"
                candle_lines.append(f"  价格动量摘要: {len(last_n)}根区间涨跌={change_pct:+.2f}% 振幅={amplitude:.2f}% 最高={max_high} 最低={min_low} {dir_label}")
            lines.extend(candle_lines)
        blocks.append("\n".join(l for l in lines if l))
    sent = _fmt_market_sentiment(data)
    if sent:
        blocks.append(f"[市场情绪·恐贪/公网宏观]\n{sent}")
    return "\n".join(blocks) or "暂无"


def _fmt_market_sentiment(data: Dict[str, Any]) -> str:
    """公网恐贪与 BTC 宏观指标 — 计入技术维，非 ValueScan 链上."""
    metrics = data.get("onchainMetrics") or {}
    parts: List[str] = []
    fg = metrics.get("fearGreed")
    if isinstance(fg, (int, float)):
        parts.append(f"恐贪指数 {fg}")
    elif isinstance(fg, dict) and fg.get("value") is not None:
        ch = fg.get("change")
        ch_s = f"，较昨日 {ch:+}" if ch is not None else ""
        parts.append(f"恐贪指数 {fg['value']}（{fg.get('label', '')}）{ch_s}")
    network = metrics.get("network") or {}
    if network.get("nTx"):
        parts.append(f"BTC 24h 链上交易 {int(network['nTx']):,} 笔")
    messari = metrics.get("messari") or {}
    if messari.get("nvt") is not None:
        parts.append(f"BTC NVT {messari['nvt']}")
    if messari.get("mvrvRatio") is not None:
        parts.append(f"BTC MVRV {messari['mvrvRatio']}")
    return "\n".join(parts)


def _fmt_onchain(data: Dict[str, Any]) -> str:
    """ValueScan 文档 §3 链上数据 + 可选 MCP 补充."""
    from web.api.valuescan_service import valuescan_chain_snapshot

    vs = data.get("valuescan") or {}
    chain = data.get("valuescanChain") or valuescan_chain_snapshot(vs)
    parts: List[str] = []

    if chain.get("tokenFlow"):
        parts.append(f"代币流向: {json.dumps(chain['tokenFlow'], ensure_ascii=False)[:800]}")
    if chain.get("whaleCost"):
        wc = chain["whaleCost"]
        tail = wc[-3:] if isinstance(wc, list) else wc
        parts.append(f"主力成本趋势(近端): {json.dumps(tail, ensure_ascii=False)[:600]}")
    if chain.get("largeTransactions"):
        parts.append(f"大额交易(前{min(5, len(chain['largeTransactions']))}笔): "
                     f"{json.dumps(chain['largeTransactions'][:5], ensure_ascii=False)[:700]}")
    if chain.get("holderList"):
        parts.append(f"持币地址 Top{min(5, len(chain['holderList']))}: "
                     f"{json.dumps(chain['holderList'][:5], ensure_ascii=False)[:500]}")
    if chain.get("topHolderAddressTrends"):
        parts.append(f"Top 地址趋势: {json.dumps(chain['topHolderAddressTrends'], ensure_ascii=False)[:800]}")

    oc = data.get("onchain") or {}
    if oc.get("summary"):
        parts.append(f"MCP 补充: {oc.get('summary')}")
    extra = oc.get("extra") or {}
    for key in ("fund_flows", "whale_activity", "market_sentiment"):
        if extra.get(key):
            parts.append(f"{key}: {extra[key]}")

    return "\n".join(parts) if parts else "暂无 (ValueScan 链上数据未配置或代币未收录)"


def _fmt_news(data: Dict[str, Any]) -> str:
    news = data.get("news") or []
    meta = data.get("newsMeta") if isinstance(data.get("newsMeta"), dict) else {}
    if not news:
        total = int(meta.get("totalCount") or 0)
        hours = int(meta.get("gateHours") or 12)
        if total > 0:
            return f"暂无 {hours}h 内可解析时间的条目（检索 {total} 条已过滤陈旧/无时间戳）"
        return "暂无"
    titles = [f"- {n['title']}" for n in news[:40] if n.get("title")]
    header = f"共 {len(news)} 条（{int(meta.get('gateHours') or 12)}h 内）"
    total = int(meta.get("totalCount") or len(news))
    if total > len(news):
        header += f"，检索 {total} 条已过滤陈旧"
    return f"{header}，最新标题(前40):\n" + "\n".join(titles)


def _fmt_valuescan(data: Dict[str, Any]) -> str:
    from web.api.valuescan_signal_digest import (
        build_valuescan_digest,
        format_valuescan_digest_for_llm,
    )

    vs = data.get("valuescan") or {}
    if not vs:
        return "暂无"
    digest = data.get("valuescanDigest")
    if not digest:
        mark = 0.0
        market = data.get("market") or {}
        try:
            mark = float(market.get("last") or 0)
        except (TypeError, ValueError):
            mark = 0.0
        digest = build_valuescan_digest(vs, mark)
    text = format_valuescan_digest_for_llm(digest)
    _j = lambda v, limit=600: json.dumps(v, ensure_ascii=False)[:limit]
    extras: List[str] = []
    if vs.get("tokenFlow"):
        extras.append(f"代币流向(现货/合约): {_j(vs['tokenFlow'])}")
    price_indicators = vs.get("priceIndicators")
    if price_indicators:
        if isinstance(price_indicators, list):
            pi_snip = price_indicators[-3:]
        else:
            pi_snip = price_indicators
        extras.append(f"BTC/ETH 趋势指标(近条): {_j(pi_snip)}")
    if extras:
        return text + "\n\n补充明细:\n" + "\n".join(extras)
    return text


def _fmt_derivatives(data: Dict[str, Any]) -> str:
    d = data.get("derivatives") or {}
    if not d:
        return "暂无"
    funding = d.get("fundingRate")
    pfunding = d.get("predictedFundingRate")
    oi = d.get("openInterest")
    fut_last = d.get("futuresLast")
    spot_last = (data.get("market") or {}).get("last")
    basis_pct = None
    try:
        if fut_last not in (None, "") and spot_last not in (None, "", 0):
            basis_pct = (float(fut_last) - float(spot_last)) / float(spot_last) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        basis_pct = None

    parts = [
        f"合约符号: {d.get('futuresSymbol', '-')}",
        f"当前资金费率: {float(funding):+.6f}" if funding is not None else "当前资金费率: 暂无",
        f"预测资金费率: {float(pfunding):+.6f}" if pfunding is not None else None,
        f"持仓量(OI): {float(oi):,.2f}" if oi is not None else "持仓量(OI): 暂无",
        f"合约最新价: {float(fut_last):.6f}" if fut_last is not None else None,
        f"现货-合约基差: {basis_pct:+.3f}%" if basis_pct is not None else None,
    ]
    return "\n".join(p for p in parts if p)


def _fmt_microstructure(data: Dict[str, Any]) -> str:
    micro = data.get("microstructure") or {}
    ob = micro.get("orderbook") or {}
    rt = micro.get("recentTrades") or {}
    if not ob and not rt:
        return "暂无"

    parts = []
    if ob:
        parts.extend([
            "订单簿快照:",
            f"- spread: {ob.get('spread', 0):.6f} ({ob.get('spreadPct', 0):.3f}%)",
            f"- depth bid/ask 名义价值: {ob.get('bidNotional', 0):,.2f} / {ob.get('askNotional', 0):,.2f}",
            f"- 深度失衡(imbalance): {ob.get('imbalance', 0):+.3f}",
        ])
    if rt:
        parts.extend([
            "逐笔成交统计:",
            f"- 样本数: {rt.get('count', 0)}",
            f"- 主动买占比: {rt.get('buyRatio', 0):.3f}",
            f"- 主动买/卖名义价值: {rt.get('buyNotional', 0):,.2f} / {rt.get('sellNotional', 0):,.2f}",
        ])
    return "\n".join(parts)


def _fmt_strategy_backtests(data: Dict[str, Any]) -> str:
    from web.api.signal_backtest_context import format_backtest_for_llm

    bundle = data.get("strategyBacktests")
    if not bundle:
        return "暂无"
    text = format_backtest_for_llm(bundle)
    return text if text else "暂无"


def _fmt_quant_factors(data: Dict[str, Any]) -> str:
    quant = data.get("quantFactors") or {}
    if not quant:
        return "暂无 (未请求量化因子管线)"
    try:
        from web.api.quant_factors_bridge import format_quant_factors_for_llm

        return format_quant_factors_for_llm(quant)
    except Exception:
        return "暂无 (量化因子格式化异常)"


def _fmt_trading_agents(data: Dict[str, Any]) -> str:
    """Format TradingAgents multi-agent debate context for LLM input."""
    ta = data.get("tradingAgents")
    if not ta or not isinstance(ta, dict) or not ta.get("available"):
        return "暂无 (TradingAgents 未启用或不可用)"
    try:
        from web.api.ta_signal_bridge import format_ta_for_llm_context
        text = format_ta_for_llm_context(ta)
        return text if text else "暂无"
    except Exception:
        return "暂无 (格式化异常)"


def _build_context(data: Dict[str, Any]) -> str:
    sections = [
        ("策略回测矩阵", _fmt_strategy_backtests),
        ("量化因子矩阵 (src/factors)", _fmt_quant_factors),
        ("实时行情 (L1/合约标记价)", _fmt_realtime),
        ("行情", _fmt_market),
        ("K线技术面", _fmt_kline),
        ("筹码/资金 ValueScan 链上", _fmt_onchain),
        ("消息面", _fmt_news),
        ("ValueScan", _fmt_valuescan),
        ("衍生品", _fmt_derivatives),
        ("盘口与逐笔", _fmt_microstructure),
        ("TradingAgents 多智能体辩论", _fmt_trading_agents),
    ]
    return "\n\n".join(f"--- {name} ---\n{fn(data)}" for name, fn in sections)


def _build_rule_reference(data: Dict[str, Any]) -> tuple[Any, str]:
    from web.api.signal_analyzer import compute_signal

    rule_result = compute_signal(data)
    parts = [
        f"规则引擎信号: {rule_result.signal} / {rule_result.label}",
        f"规则引擎得分: {rule_result.score:.1f}",
        f"规则引擎置信度: {rule_result.confidence:.1f}",
    ]
    if rule_result.reasons:
        parts.append("规则引擎主要依据:")
        parts.extend(f"- {reason}" for reason in rule_result.reasons[:5])
    return rule_result, "\n".join(parts)


def _build_data_quality(data: Dict[str, Any]) -> DataQuality:
    ta = data.get("tradingAgents")
    has_ta = bool(ta and isinstance(ta, dict) and ta.get("available"))
    bt = data.get("strategyBacktests") or {}
    has_bt = bool(bt.get("available"))
    bt_ok = int(bt.get("successCount") or 0)

    # When TA / backtests are available, redistribute weights
    if has_ta and has_bt:
        weights = {
            "market": 0.12,
            "kline": 0.16,
            "onchain": 0.12,
            "news": 0.08,
            "valuescan": 0.12,
            "derivatives": 0.06,
            "microstructure": 0.04,
            "strategyBacktests": 0.10,
            "tradingAgents": 0.20,
        }
    elif has_ta:
        weights = {
            "market": 0.14,
            "kline": 0.18,
            "onchain": 0.14,
            "news": 0.09,
            "valuescan": 0.13,
            "derivatives": 0.07,
            "microstructure": 0.05,
            "tradingAgents": 0.20,
        }
    elif has_bt:
        weights = {
            "market": 0.15,
            "kline": 0.20,
            "onchain": 0.14,
            "news": 0.10,
            "valuescan": 0.14,
            "derivatives": 0.09,
            "microstructure": 0.06,
            "strategyBacktests": 0.12,
        }
    else:
        weights = {
            "market": 0.16,
            "kline": 0.22,
            "onchain": 0.16,
            "news": 0.12,
            "valuescan": 0.16,
            "derivatives": 0.10,
            "microstructure": 0.08,
        }
    source_status: Dict[str, str] = {}
    missing_fields: List[str] = []
    limitations: List[str] = []

    from web.api.realtime_market_bridge import resolve_live_mark_price

    market = data.get("market") or {}
    live_last = resolve_live_mark_price(data)
    if live_last or market.get("last"):
        source_status["market"] = "ok"
    elif market:
        source_status["market"] = "partial"
        missing_fields.append("market.last")
    else:
        source_status["market"] = "missing"
        missing_fields.append("market")

    rt = data.get("realtime") or {}
    if isinstance(rt, dict) and rt.get("available"):
        source_status["realtime"] = "ok"
    elif rt:
        source_status["realtime"] = "partial"
        missing_fields.append("realtime.partial")
    else:
        source_status["realtime"] = "missing"

    kline = data.get("kline") or {}
    kline_tfs = ("15min", "1hour", "4hour", "1day")
    kline_count = sum(1 for t in kline_tfs if kline.get(t))
    if kline_count >= 3:
        source_status["kline"] = "ok"
    elif kline_count >= 1:
        source_status["kline"] = "partial"
        missing_fields.append("kline.multi_timeframe_incomplete")
    else:
        source_status["kline"] = "missing"
        missing_fields.append("kline")

    from web.api.valuescan_service import valuescan_chain_coverage_status

    vs = data.get("valuescan") or {}
    chain_status = valuescan_chain_coverage_status(vs)
    source_status["valuescanChain"] = chain_status
    source_status["onchain"] = chain_status
    if chain_status == "ok":
        pass
    elif chain_status == "partial":
        missing_fields.append("valuescan.chain_partial")
        limitations.append("ValueScan 链上数据不完整，筹码/资金维度置信度应折减")
    else:
        missing_fields.append("valuescan.chain")
        limitations.append("ValueScan 链上数据缺失时，不宜给出强烈筹码/资金结论")

    news = data.get("news") or []
    news_meta = data.get("newsMeta") if isinstance(data.get("newsMeta"), dict) else {}
    news_total = int(news_meta.get("totalCount") or len(news))
    gate_hours = int(news_meta.get("gateHours") or 12)
    if news and news_meta.get("gateApplicable"):
        source_status["news"] = "ok"
    elif news_total > 0:
        source_status["news"] = "partial"
        missing_fields.append("news.stale_or_untimestamped")
        limitations.append(
            f"无 {gate_hours}h 内带发布时间的新鲜新闻，共识展示块可能缺少消息面"
        )
    elif news:
        source_status["news"] = "ok"
    else:
        source_status["news"] = "partial"
        missing_fields.append("news")
        limitations.append("消息面为空时，事件驱动判断可靠性下降；新鲜新闻仅体现在共识展示与 factors.news")

    valuescan = data.get("valuescan") or {}
    vs_keys = (
        "tokenDetail", "fund", "fundRatio", "fundSnapshot", "tokenFlow", "sentiment",
        "supportResistance", "whaleCost", "priceIndicators", "aiSignals", "aiMessages",
        "vsKline15m7d", "vsKline1h14d", "vsKline4h30d", "vsKline1d90d",
        "largeTransactions", "holderList", "sectorFundListSpot", "sectorFundListFutures",
        "sectorCoinTradeSpot", "sectorCoinTradeFutures", "aiMarketAnalyseHistory",
        "topHolderAddressTrends", "sseMarketEvents", "sseSignalEvents",
    )
    vs_signal_count = sum(1 for key in vs_keys if valuescan.get(key))
    if vs_signal_count >= 6:
        source_status["valuescan"] = "ok"
    elif vs_signal_count >= 1:
        source_status["valuescan"] = "partial"
        missing_fields.append("valuescan.partial")
    else:
        source_status["valuescan"] = "missing"
        missing_fields.append("valuescan")
        limitations.append("ValueScan 缺失会削弱筹码与情绪判断")

    derivatives = data.get("derivatives") or {}
    has_funding = derivatives.get("fundingRate") is not None
    has_oi = derivatives.get("openInterest") is not None
    if has_funding and has_oi:
        source_status["derivatives"] = "ok"
    elif has_funding or has_oi:
        source_status["derivatives"] = "partial"
        missing_fields.append("derivatives.partial")
    else:
        source_status["derivatives"] = "missing"
        missing_fields.append("derivatives")
        limitations.append("衍生品数据缺失时，拥挤度与挤仓风险判断不足")

    micro = data.get("microstructure") or {}
    orderbook = micro.get("orderbook") or {}
    recent_trades = micro.get("recentTrades") or {}
    has_ob = orderbook.get("imbalance") is not None
    has_rt = recent_trades.get("buyRatio") is not None
    if has_ob and has_rt:
        source_status["microstructure"] = "ok"
    elif has_ob or has_rt:
        source_status["microstructure"] = "partial"
        missing_fields.append("microstructure.partial")
    else:
        source_status["microstructure"] = "missing"
        missing_fields.append("microstructure")
        limitations.append("盘口与逐笔缺失时，入场时机与滑点评估会偏弱")

    if has_bt and bt_ok > 0:
        source_status["strategyBacktests"] = "ok" if bt_ok >= int(bt.get("totalCount") or 0) * 0.6 else "partial"
        if bt_ok < int(bt.get("totalCount") or 0):
            missing_fields.append("strategyBacktests.partial_failures")
    elif bt:
        source_status["strategyBacktests"] = "partial"
        missing_fields.append("strategyBacktests")
        limitations.append("策略回测矩阵不完整，历史策略验证参考价值下降")
    else:
        source_status["strategyBacktests"] = "missing"
        missing_fields.append("strategyBacktests")

    quant = data.get("quantFactors") or {}
    if quant.get("available"):
        completeness = float(quant.get("overallCompleteness") or 0)
        if completeness >= 0.6:
            source_status["quantFactors"] = "ok"
        else:
            source_status["quantFactors"] = "partial"
            missing_fields.append("quantFactors.low_completeness")
    elif quant.get("reason") == "disabled":
        source_status["quantFactors"] = "missing"
    else:
        source_status["quantFactors"] = "partial"
        missing_fields.append("quantFactors")
        limitations.append("量化因子管线不可用时，资金/筹码类因子权重应下调")

    # TradingAgents coverage
    if has_ta:
        ta_decision = ta.get("finalDecision") or ta.get("traderPlan") or ""
        if ta_decision and len(str(ta_decision).strip()) > 20:
            source_status["tradingAgents"] = "ok"
        elif ta.get("marketReport") or ta.get("sentimentReport"):
            source_status["tradingAgents"] = "partial"
            missing_fields.append("tradingAgents.finalDecision")
        else:
            source_status["tradingAgents"] = "partial"
            missing_fields.append("tradingAgents.reports")

    status_score = {"ok": 1.0, "partial": 0.5, "missing": 0.0}
    coverage = sum(weights[name] * status_score.get(source_status.get(name, "missing"), 0.0) for name in weights)

    conflict_flags: List[str] = []
    one_hour = (kline.get("1hour") or {}).get("trend")
    four_hour = (kline.get("4hour") or {}).get("trend")
    if one_hour and four_hour and (("bull" in one_hour and "bear" in four_hour) or ("bear" in one_hour and "bull" in four_hour)):
        conflict_flags.append("short_term_trend_conflicts_with_medium_term_trend")

    return DataQuality(
        coverageScore=round(coverage, 2),
        sourceStatus=source_status,
        missingFields=missing_fields,
        conflictFlags=conflict_flags,
        limitations=limitations,
    )


def _calc_risk_reward(
    entry: float,
    stop: float,
    target: float,
    side: Optional[str] = None,
) -> float:
    from web.api.trade_plan_executor import calc_directional_risk_reward

    return calc_directional_risk_reward(entry, stop, target, side)


def _safe_model(model_cls, value, default_factory=None):
    if isinstance(value, model_cls):
        return value
    if isinstance(value, dict):
        try:
            return model_cls(**value)
        except Exception:
            pass
    return default_factory() if default_factory else model_cls()


def _signal_bias(signal: str) -> str:
    if signal in {"BUY", "WEAK_BUY"}:
        return "bullish"
    if signal in {"SELL", "WEAK_SELL"}:
        return "bearish"
    return "neutral"


def _signal_label(signal: str) -> str:
    return {
        "BUY": "买入",
        "WEAK_BUY": "偏多观望",
        "NEUTRAL": "中性观望",
        "WEAK_SELL": "偏空观望",
        "SELL": "卖出",
    }.get(signal, "中性观望")


def _direction_from_factor(block: FactorBlock) -> str:
    value = str(getattr(block, "direction", "") or "").strip().lower()
    if value in {"bullish", "bearish", "neutral"}:
        return value
    # 兼容中文标签
    if "多" in value:
        return "bullish"
    if "空" in value:
        return "bearish"
    if "中" in value:
        return "neutral"
    return "neutral"


def direction_from_text(value: Any) -> str:
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


from web.api.entry_gate import (  # noqa: E402
    evaluate_entry_gate_alignment,
    evaluate_five_signal_alignment,
    format_alignment_dimensions_cn,
)


def _snapshot_llm_gate_factor_directions(result: SignalOutput) -> None:
    """在规则补齐 factors 之前，锁定 LLM 输出的门禁用技术/盘面方向。"""
    refs = dict(result.debug.sourceRefs or {})
    if not _factor_block_is_empty(result.factors.technical):
        refs["gateTechnicalFromLlm"] = True
        refs["gateTechnicalDirection"] = _direction_from_factor(result.factors.technical)
    if not _factor_block_is_empty(result.factors.positioning):
        refs["gatePositioningFromLlm"] = True
        refs["gatePositioningDirection"] = _direction_from_factor(result.factors.positioning)
    result.debug.sourceRefs = refs


def _resolve_technical_gate_direction(result: SignalOutput) -> str:
    from web.api.entry_gate import resolve_technical_gate_direction

    return resolve_technical_gate_direction(result)


def _resolve_positioning_gate_direction(result: SignalOutput) -> str:
    from web.api.entry_gate import resolve_positioning_gate_direction

    return resolve_positioning_gate_direction(result)


def _is_futures_signal_reversal_core(
    position_side: str,
    signal: str,
    alignment: Dict[str, Any],
) -> tuple[bool, str]:
    """持仓方向与信号/入场门禁明显相反时，触发尽快止损。"""
    side = str(position_side or "").lower()
    if side not in {"long", "short"}:
        return False, ""

    signal_upper = str(signal or "NEUTRAL").upper()
    direction = str(alignment.get("direction") or "neutral").lower()
    dimensions = alignment.get("dimensions") or {}
    gate_keys = alignment.get("gateDimensions") or list(dimensions.keys())
    gate_values = [str(dimensions.get(k) or "neutral").lower() for k in gate_keys]
    gate_n = max(3, len(gate_keys))

    if side == "long":
        if direction == "bearish":
            return True, "入场门禁转为偏空，平多止损"
        if signal_upper in {"SELL", "WEAK_SELL", "WEAK_SHORT", "SHORT"}:
            return True, f"综合信号反转为 {signal_upper}，平多止损"
        bearish_count = sum(1 for value in gate_values if value == "bearish")
        if bearish_count >= min(3, gate_n):
            return True, f"门禁维度中 {bearish_count} 项转空，平多止损"
    else:
        if direction == "bullish":
            return True, "入场门禁转为偏多，平空止损"
        if signal_upper in {"BUY", "WEAK_BUY", "WEAK_LONG", "LONG"}:
            return True, f"综合信号反转为 {signal_upper}，平空止损"
        bullish_count = sum(1 for value in gate_values if value == "bullish")
        if bullish_count >= min(3, gate_n):
            return True, f"门禁维度中 {bullish_count} 项转多，平空止损"
    return False, ""


def is_futures_signal_reversal(position_side: str, result: SignalOutput, alignment: Dict[str, Any]) -> tuple[bool, str]:
    return _is_futures_signal_reversal_core(
        position_side,
        str(result.signal or "NEUTRAL"),
        alignment,
    )


def is_futures_signal_reversal_from_analysis(
    position_side: str,
    analysis: Dict[str, Any],
) -> tuple[bool, str]:
    """Hybrid 预计算分析无 SignalOutput 时，用 row 字段做反转判断。"""
    return _is_futures_signal_reversal_core(
        position_side,
        str(analysis.get("signal") or "NEUTRAL"),
        analysis.get("fiveSignalAlignment") or {},
    )


def _roe_to_pct(value: float) -> float:
    """KuCoin unrealisedRoe may be ratio (0.05) or percent (5)."""
    if value == 0:
        return 0.0
    if abs(value) <= 2:
        return value * 100.0
    return value


def is_futures_loss_exceeded(
    position: Dict[str, Any],
    *,
    max_loss_pct: float,
    max_loss_usd: float = 0.0,
) -> tuple[bool, str]:
    """持仓浮亏超过阈值时触发平仓（与信号无关）。"""
    if max_loss_pct <= 0 and max_loss_usd <= 0:
        return False, ""

    side = str(position.get("side") or "").lower()
    entry = float(position.get("entryPrice") or 0)
    mark = float(position.get("markPrice") or 0)
    if entry > 0 and mark > 0 and side in {"long", "short"}:
        if side == "long":
            price_pct = (mark - entry) / entry * 100.0
        else:
            price_pct = (entry - mark) / entry * 100.0
    else:
        price_pct = float(position.get("unrealizedPnlPct") or 0)

    roe_pct = _roe_to_pct(float(position.get("unrealisedRoe") or position.get("unrealizedRoe") or 0))
    margin_pct = float(position.get("unrealizedMarginPct") or 0)
    candidates = [price_pct, roe_pct, margin_pct]
    worst_pct = min(candidates) if candidates else 0.0
    loss_pct = -worst_pct if worst_pct < 0 else 0.0

    unrealized_usd = float(
        position.get("unrealisedPnl")
        or position.get("unrealizedPnl")
        or position.get("unrealizedPnlUsd")
        or 0
    )
    loss_usd = -unrealized_usd if unrealized_usd < 0 else 0.0

    if max_loss_pct > 0 and loss_pct >= max_loss_pct:
        return True, f"浮亏 {loss_pct:.2f}% 超过阈值 {max_loss_pct:.2f}%"
    if max_loss_usd > 0 and loss_usd >= max_loss_usd:
        return True, f"浮亏 {loss_usd:.2f} USDT 超过阈值 {max_loss_usd:.2f} USDT"
    return False, ""


def resolve_futures_auto_exit(
    position: Dict[str, Any],
    result: Optional["SignalOutput"],
    alignment: Dict[str, Any],
    *,
    stop_on_reversal: bool,
    stop_on_loss: bool,
    max_loss_pct: float,
    max_loss_usd: float = 0.0,
    trade_plan: Optional[Dict[str, Any]] = None,
    enforce_plan_stop: bool = False,
    enforce_plan_targets: bool = False,
    analysis: Optional[Dict[str, Any]] = None,
) -> tuple[bool, str, str]:
    """返回 (是否平仓, 原因, action 标签: plan_stop | plan_target | stop_loss | loss_cut)。"""
    if trade_plan and (enforce_plan_stop or enforce_plan_targets):
        try:
            from web.api.trade_plan_executor import evaluate_trade_plan_exit, normalize_trade_plan

            plan = normalize_trade_plan(trade_plan)
            should_close, reason, action = evaluate_trade_plan_exit(
                position,
                plan,
                enforce_stop=enforce_plan_stop,
                enforce_targets=enforce_plan_targets,
            )
            if should_close:
                return True, reason, action
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "trade plan exit check failed: %s", exc, exc_info=True
            )

    if stop_on_reversal:
        pos_side = str(position.get("side") or "")
        if result is not None:
            should_stop, reason = is_futures_signal_reversal(pos_side, result, alignment)
        elif analysis:
            should_stop, reason = is_futures_signal_reversal_from_analysis(pos_side, analysis)
        else:
            should_stop, reason = False, ""
        if should_stop:
            return True, reason, "stop_loss"
    if stop_on_loss:
        loss_hit, reason = is_futures_loss_exceeded(
            position,
            max_loss_pct=max_loss_pct,
            max_loss_usd=max_loss_usd,
        )
        if loss_hit:
            return True, reason, "loss_cut"
    return False, "", ""


def _is_reversal_against_signal(data: Dict[str, Any], signal: str) -> bool:
    if signal not in {"BUY", "SELL", "WEAK_BUY", "WEAK_SELL"}:
        return False
    kline = data.get("kline") or {}
    one_hour = kline.get("1hour") or {}
    trend = str(one_hour.get("trend") or "").lower()
    breakout = str(one_hour.get("breakout") or "none").lower()
    if signal in {"BUY", "WEAK_BUY"}:
        return ("bear" in trend) or breakout == "bearish"
    return ("bull" in trend) or breakout == "bullish"


def _apply_unanimous_factor_rule(result: SignalOutput, data: Dict[str, Any]) -> tuple[SignalOutput, bool]:
    """多周期+LLM 因子同向时强化 BUY/SELL（不含可执行/共识/新闻）。"""
    from web.api.entry_gate import (
        _resolve_flow_direction,
        _resolve_structure_direction,
        resolve_entry_gate_options,
        resolve_llm_flow_direction,
        resolve_mtf_structure_direction,
    )
    from web.api.quant_factors_bridge import resolve_quant_factors_options

    q_opts = resolve_quant_factors_options()
    quant = data.get("quantFactors") or {}
    gate_opts = resolve_entry_gate_options()
    if gate_opts.get("mode") == "llm_mtf":
        s_dir, _, _ = resolve_mtf_structure_direction(data, result, gate_opts)
        if s_dir == "neutral":
            return result, False
        f_dir, _ = resolve_llm_flow_direction(result, expected_direction=s_dir)
    else:
        s_dir, _ = _resolve_structure_direction(data, result)
        f_dir, _ = _resolve_flow_direction(
            result,
            quant_factors=quant,
            quant_min_aggregate=q_opts["min_aggregate"],
            require_quant=bool(q_opts["enabled"]),
        )
    dirs = [s_dir, f_dir]
    if any(direction == "neutral" for direction in dirs):
        return result, False
    if len(set(dirs)) != 1:
        return result, False

    unanimous = dirs[0]
    if unanimous == "bullish":
        result.signal = "BUY"
        result.label = _signal_label("BUY")
        result.analysis.bias = "bullish"
        result.score = max(result.score, 35.0)
        result.confidence = max(result.confidence, 80.0)
    elif unanimous == "bearish":
        result.signal = "SELL"
        result.label = _signal_label("SELL")
        result.analysis.bias = "bearish"
        result.score = min(result.score, -35.0)
        result.confidence = max(result.confidence, 80.0)
    else:
        return result, False

    tip = "多周期与 LLM 因子同向，强化交易信号（可执行/共识/新闻不参与同向强化）。"
    if tip not in result.reasons:
        result.reasons.insert(0, tip)
    if "all_factors_unanimous" not in result.debug.sourceRefs:
        result.debug.sourceRefs["all_factors_unanimous"] = unanimous
    return result, True


def _derive_market_state(data: Dict[str, Any], signal: str) -> str:
    kline = data.get("kline") or {}
    one_hour = kline.get("1hour") or {}
    four_hour = kline.get("4hour") or {}
    breakout = one_hour.get("breakout") or four_hour.get("breakout") or "none"
    range_pos = one_hour.get("rangePos") if one_hour.get("rangePos") is not None else four_hour.get("rangePos")
    trend_1h = str(one_hour.get("trend") or "")
    trend_4h = str(four_hour.get("trend") or "")
    if breakout == "bullish":
        return "breakout_confirmation"
    if breakout == "bearish":
        return "range_breakdown_risk" if signal in {"NEUTRAL", "WEAK_BUY", "BUY"} else "breakout_confirmation"
    if "bull" in trend_1h and "bull" in trend_4h:
        return "trend_continuation_near_resistance" if range_pos is not None and range_pos >= 75 else "trend_continuation"
    if "bear" in trend_1h and "bear" in trend_4h:
        return "false_breakout_risk" if range_pos is not None and range_pos <= 25 else "range_breakdown_risk"
    if signal in {"BUY", "WEAK_BUY"}:
        return "range_rebound"
    return "uncertain"


def _factor_block_from_score_reasons(
    score: float,
    reasons: List[str],
    *,
    max_highlights: int = 4,
) -> FactorBlock:
    direction = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"
    confidence = min(1, max(0, abs(score) / 20))
    return FactorBlock(
        direction=direction,
        score=round(score, 1),
        confidence=round(confidence, 2),
        highlights=[str(r) for r in reasons[:max_highlights] if r],
    )


def _run_scorer_group(
    data: Dict[str, Any],
    scorers: List[Any],
    *,
    max_highlights: int = 4,
) -> FactorBlock:
    total = 0.0
    reasons: List[str] = []
    for fn in scorers:
        try:
            delta, items = fn(data)
            total += float(delta)
            reasons.extend(items)
        except Exception:
            logger.exception("scorer %s failed", getattr(fn, "__name__", fn))
    return _factor_block_from_score_reasons(total, reasons, max_highlights=max_highlights)


def _rule_scorer_factor_blocks(data: Dict[str, Any]) -> Dict[str, FactorBlock]:
    """按维度汇总规则引擎 scorer，保证链上/新闻等有可展示依据。"""
    from web.api.signal_analyzer import (
        TECHNICAL_SCORERS_FOR_LLM,
        score_news,
        score_onchain_mcp,
        score_vs_ai_signals,
        score_vs_fund,
        score_vs_holder_list,
        score_vs_holder_trends,
        score_vs_large_transactions,
        score_vs_price_indicators,
        score_vs_sentiment,
        score_vs_support_resistance,
        score_vs_token_flow,
        score_vs_whale,
    )

    technical = _run_scorer_group(
        data,
        TECHNICAL_SCORERS_FOR_LLM,
        max_highlights=8,
    )
    onchain = _run_scorer_group(
        data,
        [
            score_vs_token_flow,
            score_vs_whale,
            score_vs_large_transactions,
            score_vs_holder_list,
            score_vs_holder_trends,
            score_onchain_mcp,
        ],
    )
    positioning = _run_scorer_group(
        data,
        [
            score_vs_fund,
            score_vs_sentiment,
            score_vs_ai_signals,
        ],
    )
    news_block = _run_scorer_group(data, [score_news])
    consensus = _rule_consensus_block(data, technical, onchain, positioning, news_block)

    return {
        "technical": technical,
        "onchain": onchain,
        "news": news_block,
        "positioning": positioning,
        "consensus": consensus,
    }


def _rule_consensus_block(
    data: Dict[str, Any],
    technical: FactorBlock,
    onchain: FactorBlock,
    positioning: FactorBlock,
    news_block: FactorBlock,
) -> FactorBlock:
    """规则共识块（仅 UI 展示）：技术/盘面/新闻一致度，不参与门禁与下单。"""
    meta = data.get("newsMeta") if isinstance(data.get("newsMeta"), dict) else {}
    tech_dir = str(technical.direction or "neutral").lower()
    pos_dir = str(positioning.direction or "neutral").lower()
    reasons: List[str] = []
    if tech_dir in ("bullish", "bearish") and pos_dir == tech_dir:
        reasons.append(f"技术与盘面均指向 {tech_dir}")
    elif tech_dir in ("bullish", "bearish") and pos_dir in ("bullish", "bearish") and tech_dir != pos_dir:
        reasons.append(f"技术={tech_dir} 与 盘面={pos_dir} 分歧")
    elif pos_dir in ("bullish", "bearish"):
        reasons.append(f"盘面指向 {pos_dir}")
    if meta.get("gateApplicable") and news_block.highlights:
        reasons.extend([f"新闻: {h}" for h in news_block.highlights[:2]])
    elif int(meta.get("totalCount") or 0) > 0:
        reasons.append(f"{int(meta.get('gateHours') or 12)}h 内无新鲜新闻，共识不含消息面")
    score = 0.0
    for d in (tech_dir, pos_dir):
        if d == "bullish":
            score += 4
        elif d == "bearish":
            score -= 4
    if meta.get("gateApplicable"):
        try:
            score += float(news_block.score) * 0.5
        except (TypeError, ValueError):
            pass
    news_dir = str(news_block.direction or "neutral").lower()
    if meta.get("gateApplicable") and news_dir in ("bullish", "bearish"):
        gate_dirs = [d for d in (tech_dir, pos_dir) if d in ("bullish", "bearish")]
        if gate_dirs and len(set(gate_dirs)) == 1 and news_dir not in gate_dirs:
            return FactorBlock(
                direction="neutral",
                score=0.0,
                confidence=0.35,
                highlights=(reasons + ["新鲜新闻与门禁方向冲突"])[:4],
            )
    return _factor_block_from_score_reasons(score, reasons)


def _factor_block_is_empty(block: FactorBlock) -> bool:
    if block.highlights:
        return False
    try:
        if abs(float(block.score)) >= 0.01:
            return False
    except (TypeError, ValueError):
        pass
    return str(block.direction or "neutral").lower() in {"neutral", ""}


def _merge_factors_with_rule_data(factors: FactorsBlock, data: Dict[str, Any]) -> FactorsBlock:
    """LLM 未填充的维度用规则 scorer 结果补齐（常见于 onchain/news）。"""
    rule_blocks = _rule_scorer_factor_blocks(data)
    return FactorsBlock(
        technical=rule_blocks["technical"] if _factor_block_is_empty(factors.technical) else factors.technical,
        onchain=rule_blocks["onchain"] if _factor_block_is_empty(factors.onchain) else factors.onchain,
        news=rule_blocks["news"] if _factor_block_is_empty(factors.news) else factors.news,
        positioning=rule_blocks["positioning"] if _factor_block_is_empty(factors.positioning) else factors.positioning,
    )


def _derive_factors(reasons: List[str], rule_result: Any) -> FactorsBlock:
    groups = {
        "technical": [],
        "onchain": [],
        "news": [],
        "positioning": [],
        "consensus": [],
    }
    for reason in reasons or []:
        text = str(reason)
        lower = text.lower()
        if any(key in lower for key in ["rsi", "ma", "布林", "量比", "趋势", "突破", "支撑", "阻力", "4h", "1h", "15m", "1d",
                                        "atr", "资金费率", "盘口", "主动买", "基差", "持仓量", "oi", "回测", "量化",
                                        "成交额", "价差", "影线", "共振", "macd", "动量", "振幅",
                                        "恐惧", "贪婪", "恐贪", "mvrv", "nvt", "mempool", "内存池", "sat/vb"]):
            groups["technical"].append(text)
        elif any(key in lower for key in ["链上", "大额", "持币", "持仓地址", "主力成本", "代币流向", "交易所流向",
                                          "whale", "vs 地址", "vs 大额", "vs 持币", "mcp 情绪"]):
            groups["onchain"].append(text)
        elif any(key in lower for key in ["新闻", "消息", "利多", "利空", "催化", "headline"]):
            groups["news"].append(text)
            groups.setdefault("consensus", []).append(text)
        elif any(key in lower for key in ["密集成交", "价格指标", "vs 支撑", "vs 压力", "vs 密集"]):
            groups["technical"].append(text)
        elif any(key in lower for key in ["社媒", "vs ai", "vs 1h", "vs 24h", "资金/市值",
                                          "机会", "风险", "异动", "valuescan"]):
            groups["positioning"].append(text)

    def _block(items: List[str], score: float) -> FactorBlock:
        direction = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"
        confidence = min(1, max(0, abs(score) / 20))
        return FactorBlock(direction=direction, score=round(score, 1), confidence=round(confidence, 2), highlights=items[:3])

    rb = getattr(rule_result, "score", 0)
    return FactorsBlock(
        technical=_block(groups["technical"], rb * 0.45 if groups["technical"] else 0),
        onchain=_block(groups["onchain"], rb * 0.15 if groups["onchain"] else 0),
        news=_block(groups["news"], rb * 0.10 if groups["news"] else 0),
        positioning=_block(groups["positioning"], rb * 0.20 if groups["positioning"] else 0),
    )


def _derive_risks(result: SignalOutput, data_quality: DataQuality) -> List[RiskItem]:
    risks: List[RiskItem] = []
    if result.tradePlan and result.analysis.keyLevels.invalidation:
        risks.append(RiskItem(
            type="setup_invalidation",
            severity="high",
            evidence="当前交易计划存在明确失效位，一旦跌破/突破将破坏原判断",
            trigger=f"触及失效位 {result.analysis.keyLevels.invalidation}",
            mitigation="严格执行止损，不在失效后逆势加仓",
        ))
    for conflict in data_quality.conflictFlags[:2]:
        risks.append(RiskItem(
            type=conflict,
            severity="medium",
            evidence="不同周期或不同来源数据存在方向冲突",
            trigger="短线走势与中周期结构继续背离",
            mitigation="降低仓位，等待更多确认信号",
        ))
    if data_quality.coverageScore < 0.75:
        risks.append(RiskItem(
            type="incomplete_data",
            severity="medium",
            evidence="当前有效数据覆盖不足，结论存在信息偏差风险",
            trigger="缺失的数据源恰好承载关键反向证据",
            mitigation="降低置信度使用，优先参考已验证价位与止损",
        ))
    return risks[:3]


def _derive_scenarios(result: SignalOutput) -> List[ScenarioItem]:
    if not result.tradePlan:
        return []
    tp = result.tradePlan
    return [
        ScenarioItem(name="bull", probability=0.35, trigger=f"放量突破 {tp.resistance}", action="顺势跟随或突破回踩后介入", target=[tp.target1, tp.target2]),
        ScenarioItem(name="base", probability=0.45, trigger=f"维持在 {tp.support} ~ {tp.resistance} 区间内", action="按区间交易，接近支撑观察，接近阻力不追高", target=[tp.resistance]),
        ScenarioItem(name="bear", probability=0.20, trigger=f"跌破失效位 {tp.stop}", action="取消当前方向计划，等待下一个稳定支撑", target=[tp.support]),
    ]


def _trade_plan_incomplete(plan: Optional[TradePlan]) -> bool:
    if not plan:
        return True
    return not (plan.entryLow > 0 and plan.entryHigh > 0 and plan.stop > 0)


def _enrich_result(result: SignalOutput, data: Dict[str, Any], rule_result: Any, data_quality: DataQuality, model: str) -> SignalOutput:
    from web.api.valuescan_signal_digest import (
        build_valuescan_digest,
        merge_trade_plan_with_digest,
    )

    mark = 0.0
    try:
        mark = float((data.get("market") or {}).get("last") or 0)
    except (TypeError, ValueError):
        mark = 0.0
    digest = data.get("valuescanDigest") or build_valuescan_digest(data.get("valuescan") or {}, mark)
    result.valuescanInsights = digest if digest.get("available") else {}
    result.debug.sourceRefs = {**(result.debug.sourceRefs or {}), "valuescanDigest": digest}

    if digest.get("available"):
        primary = str(digest.get("primaryAlert") or "").strip()
        if primary and primary not in result.reasons:
            result.reasons = [primary, *result.reasons[:5]]
        merged_plan = merge_trade_plan_with_digest(
            result.tradePlan.model_dump() if result.tradePlan else {},
            digest,
            signal=result.signal,
        )
        if merged_plan and _trade_plan_incomplete(result.tradePlan):
            try:
                result.tradePlan = TradePlan(**merged_plan)
            except Exception:
                pass
        bias = str(digest.get("actionBias") or "")
        if bias == "risk_off" and result.signal in {"BUY", "WEAK_BUY"}:
            result.signal = "WEAK_BUY" if result.signal == "BUY" else "NEUTRAL"
            result.label = _signal_label(result.signal)
            note = "ValueScan 风险追踪活跃，下调激进多头信号"
            if note not in result.reasons:
                result.reasons.insert(0, note)

    result.dataQuality = result.dataQuality if result.dataQuality.coverageScore else data_quality
    result.engineMeta = EngineMeta(model=model, analysisVersion="v2", fallbackUsed=result.engineMeta.fallbackUsed)

    result.analysis.bias = result.analysis.bias or _signal_bias(result.signal)
    result.analysis.marketState = result.analysis.marketState if result.analysis.marketState != "uncertain" else _derive_market_state(data, result.signal)
    result.analysis.horizon = result.analysis.horizon or "intraday_swing"

    if (
        _factor_block_is_empty(result.factors.technical)
        and _factor_block_is_empty(result.factors.onchain)
        and _factor_block_is_empty(result.factors.news)
        and _factor_block_is_empty(result.factors.positioning)
    ):
        result.factors = _derive_factors(result.reasons, rule_result)
    _snapshot_llm_gate_factor_directions(result)
    result.factors = _merge_factors_with_rule_data(result.factors, data)

    if result.tradePlan:
        tp = result.tradePlan
        result.analysis.keyLevels.supports = result.analysis.keyLevels.supports or [p for p in [tp.support] if p > 0]
        result.analysis.keyLevels.resistances = result.analysis.keyLevels.resistances or [p for p in [tp.resistance, tp.target1, tp.target2] if p > 0]
        result.analysis.keyLevels.invalidation = result.analysis.keyLevels.invalidation or tp.stop
        result.analysis.execution.timeHorizon = result.analysis.execution.timeHorizon or "4h-24h"
        result.analysis.execution.positionSize = result.analysis.execution.positionSize or ("medium" if result.confidence >= 75 else "small")
        result.analysis.execution.action = result.analysis.execution.action or ("等待回踩确认后执行" if result.signal in {"WEAK_BUY", "WEAK_SELL"} else "按计划执行并严格带止损")

    if not result.analysis.consensus.direction or result.analysis.consensus.direction == "neutral":
        result.analysis.consensus.direction = result.analysis.bias
    if not result.analysis.consensus.agreementScore:
        agreement = min(1, max(0.2, result.confidence / 100))
        result.analysis.consensus.agreementScore = round(agreement, 2)
    if not result.analysis.consensus.strength or result.analysis.consensus.strength == "weak":
        score = result.analysis.consensus.agreementScore
        result.analysis.consensus.strength = "strong" if score >= 0.8 else "medium" if score >= 0.55 else "weak"
    result.analysis.consensus.conflicts = result.analysis.consensus.conflicts or data_quality.conflictFlags
    result.analysis.scoreBreakdown.technical = result.analysis.scoreBreakdown.technical or round(result.factors.technical.score, 1)
    result.analysis.scoreBreakdown.onchain = result.analysis.scoreBreakdown.onchain or round(result.factors.onchain.score, 1)
    result.analysis.scoreBreakdown.news = result.analysis.scoreBreakdown.news or round(result.factors.news.score, 1)
    result.analysis.scoreBreakdown.positioning = result.analysis.scoreBreakdown.positioning or round(result.factors.positioning.score, 1)
    result.analysis.scoreBreakdown.riskPenalty = result.analysis.scoreBreakdown.riskPenalty or (-5 if data_quality.conflictFlags else 0)

    if not result.risks:
        result.risks = _derive_risks(result, data_quality)
    if not result.scenarios:
        result.scenarios = _derive_scenarios(result)

    result, unanimous_applied = _apply_unanimous_factor_rule(result, data)
    from web.api.executable_gate import finalize_signal_execution

    finalize_signal_execution(result, data)

    # 固化“行情反转及时止损”到执行计划与风险，确保可执行。
    if result.tradePlan and result.tradePlan.stop > 0:
        reversal_note = f"若 1h 趋势反向或触及失效位 {result.tradePlan.stop}，立即止损离场。"
    else:
        reversal_note = "若 1h 趋势反向，立即止损离场。"

    if result.signal in {"BUY", "SELL", "WEAK_BUY", "WEAK_SELL"}:
        action = (result.analysis.execution.action or "").strip()
        if reversal_note not in action:
            result.analysis.execution.action = (action + "；" if action else "") + reversal_note
        has_reversal_risk = any("反向" in str(item.trigger or "") for item in result.risks)
        if not has_reversal_risk:
            result.risks.append(RiskItem(
                type="trend_reversal",
                severity="high",
                evidence="短周期行情可能出现方向反转，原交易逻辑会失效",
                trigger=reversal_note,
                mitigation="触发后立刻减仓或平仓，不做主观扛单",
            ))
        if reversal_note not in result.summary:
            result.summary = (result.summary + " " + reversal_note).strip()

    if unanimous_applied:
        catalyst = "技术+量化+盘面同向共振：适合顺势开立合约仓位"
        if catalyst not in result.analysis.catalysts:
            result.analysis.catalysts.append(catalyst)

    result.debug.calibration = CalibrationBlock(
        ruleSignal=rule_result.signal,
        ruleScore=rule_result.score,
        llmRuleGap=round(result.score - rule_result.score, 1),
    )
    result.debug.sourceRefs = {**(result.debug.sourceRefs or {}), "model": model}

    # Populate TradingAgents debate block from data context
    ta = data.get("tradingAgents")
    if ta and isinstance(ta, dict) and ta.get("available"):
        result.tradingAgentsDebate = TradingAgentsDebateBlock(
            available=True,
            dataSource=ta.get("dataSource", ""),
            latencyMs=ta.get("latencyMs", 0),
            marketSummary=str(ta.get("marketReport", ""))[:2000],
            sentimentSummary=str(ta.get("sentimentReport", ""))[:2000],
            newsSummary=str(ta.get("newsReport", ""))[:2000],
            fundamentalsSummary=str(ta.get("fundamentalsReport", ""))[:2000],
            bullArgument=str(
                ta.get("bullAnalystReport") or ta.get("bullReport") or ""
            )[:2000],
            bearArgument=str(
                ta.get("bearAnalystReport") or ta.get("bearReport") or ""
            )[:2000],
            riskAssessment=str(
                ta.get("riskManagerReport") or ta.get("riskReport") or ""
            )[:2000],
            traderPlan=str(ta.get("traderPlan", ""))[:2000],
            finalDecision=str(ta.get("finalDecision", ""))[:2000],
        )
        result.debug.sourceRefs["tradingAgents"] = True
        result.debug.sourceRefs["tradingAgentsSource"] = ta.get("dataSource", "")
        result.debug.sourceRefs["tradingAgentsLatencyMs"] = ta.get("latencyMs", 0)

    return _localize_output(result)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """\
你是一名资深加密货币量化交易专家，兼具趋势交易、链上研究、情绪分析和风险控制能力。
你的任务不是复述数据，而是基于已有市场数据、K线结构、链上指标、消息面和 ValueScan 数据，产出“高信息量、可执行、可解释、可风控”的综合信号。

必须遵循以下分析顺序：
1. 先判断市场状态：趋势延续、区间震荡、突破确认、假突破风险、趋势衰竭中的哪一种。
2. 再分维度评估：technical（价量+衍生品+盘口）/ positioning（VS 资金情绪+AI榜）/ onchain（仅展示）/ factors.news；**实盘入场门禁= 规则价量结构 + 量化+盘面资金 + 可执行（ready+tradePlan 盈亏比）**；analysis.consensus 仅参考。
3. 再做一致性校验：找出哪些数据互相印证，哪些数据互相冲突（含新鲜新闻与技术面/链上冲突）。
4. 最后才输出 signal / confidence / tradePlan / risks / scenarios。

分析纪律：
- 4h 用于定方向，1h 用于定执行；若 1h 与 4h 冲突，必须下调置信度。
- 若技术面偏多，但链上/消息/筹码不确认，只能输出 WEAK_BUY 或 NEUTRAL。
- 若价格接近强阻力且没有放量突破，不应给出激进 BUY。
- 若价格接近强支撑且出现超卖修复，可以提高反弹判断，但必须说明失效位。
- 若数据缺失或来源冲突，必须在 dataQuality 和 summary 中写明。

K线价格行为分析纪律（重要！这是信号准确性的核心）：
- 你必须仔细阅读“K线技术面”中的每根K线 OHLCV 数据，理解价格的实际走势。
- 连续阴线（收盘低于开盘）表明空头压制，应偿向空或观望；
- 连续阳线（收盘高于开盘）表明多头动能，可偿向多；
- “价格动量摘要”中的“涨跌”字段是近N根K线的复合涨跌幅，这是短期动量的核心指标；
- 如果 1h/4h K线近期明确下跌（涨跌 < -1%），无论某些链上指标偏多，都不应给出 BUY 或 WEAK_BUY；
- 如果 K线价格趋势显著下行而 RSI 未到超卖，应给出 WEAK_SELL 或 SELL；
- 如果 K线趋势与链上数据方向冲突，必须以 K线实际价格行为为主、链上为辅。价格是市场的最终表达。
- 区间位置 rangePos 接近高位（>80%）且量比不足，表明价格接近阻力且动能不足，应谨慎给出多头信号；
- 区间位置 rangePos 接近低位（<20%）且 RSI 超卖，可考虑反弹交易但必须有失效位。
- 禁止赋予"偏多观望"默认倾向。每次分析必须从实际价格行为出发，用数据证据来支持每个方向判断。

买入入场类型纪律（BUY / WEAK_BUY 时必须在 tradePlan 中体现入场场景）：
- 突破入场：价格已放量突破前期高点确认，entryLow/entryHigh 在当前价附近±0.5%，止损放在突破前低点或支撑下方 0.5~1.5x ATR，execution.action 写"突破确认后立即跟进"。
- 回踩入场（WEAK_BUY 主要场景）：趋势向上但价格未充分回调，entryLow/entryHigh 应明显低于当前市价，锚定在 SMA20 / 近期支撑 / 主力成本之上，execution.action 写"等待回踩至 XX 位再介入"，不可写"立即买入"。
- 超跌反弹入场（RSI ≤ 35 或 %B ≤ 0）：entryLow 设在布林带下轨或强支撑附近，entryHigh 不超过当前价，止损放在近期最低点下方，execution.action 写"超卖区域分批入场"。
- target1 必须使用 VS 密集成交区或 K 线阻力位的真实价格，target2 取更高阻力或从入场价起算 3x ATR，禁止硬编码为当前价 +N%。
- ValueScan tokenFlow 中现货与合约资金同步流入，是突破/多头信号的确认；分歧时降低置信度。

卖出/做空入场类型纪律（SELL / WEAK_SELL 时必须在 tradePlan 中体现合约空逻辑）：
- 反弹阻力空（WEAK_SELL 主要场景）：趋势向下但现价贴近支撑/超卖时，entryLow/entryHigh 应锚定在上方阻力位（SMA20 / VS 压力 / 前高），明显高于当前市价；stop 放在阻力上方 0.5~1.5x ATR；target1 取下一档支撑而非眼前支撑；executionReadiness 用 watch_pullback，execution.action 写"等待反弹至 XX 阻力再空"。
- 跌破追空：价格已有效跌破支撑且量能确认，entry 在破位附近，stop 放在跌破前高点/阻力上方，target1/target2 依次取下档支撑；可用 ready。
- 贴支撑禁止激进空：rangePos < 25% 或 RSI ≤ 35 且价格距支撑位 < 2% 时，不得给 SELL+ready；应降级 WEAK_SELL 或 NEUTRAL，或 watch_pullback + 阻力区 entry。
- 短周期 timing（1m/5m 优先，15m 确认）：大周期偏空但贴支撑时，必须阅读 1m/5m 近期 OHLCV 与动量摘要——若 1m/5m 连续阳线、趋势偏多或 RSI 修复+MACD 柱正，executionReadiness 必须为 watch_pullback（等阻力再空）；仅当 1m/5m 连续阴线、空头突破或短线动量明显偏空时，才可 ready 破位追空。系统会在 enrich 阶段用同一规则覆盖你的 readiness。
- 合约空价格铁律：stop 必须高于 entryHigh；target1/target2 必须低于 entryLow；target1 不得落在入场价下方不足 1x ATR 的"眼前支撑"上。
- 资金费率显著为负且做空需支付高费率时，应降低置信度或倾向 watch_pullback。

你必须最大化利用当前输入：
- market: 当前价格、24h 涨跌、高低、成交量(vol)、成交额(volValue)、买一/卖一价
- kline: 1h/4h 趋势、RSI、布林带、突破状态、量比、区间位置、支撑阻力、SMA、ATR、布林上下轨
- kline 近期K线OHLCV: 各周期（含 1m/5m）最近10根K线的开/高/低/收/量与动量摘要；**做空 timing 以 1m/5m 为主、15m 为辅**，用于区分「贴支撑等反弹」与「破位追空」
- 筹码/资金（valuescan 链上 API）: 代币流向、主力成本、大额交易、持币地址、Top 地址余额/持仓趋势
- 市场情绪（计入技术维）: onchainMetrics.fearGreed（alternative.me 恐贪指数）；BTC 另有公网 mempool/NVT/MVRV（score_public_chain_metrics）
- news: 新鲜新闻标题（已过滤陈旧条目）；写入 factors.news 与 analysis.consensus（展示用 direction/conflicts/highlights）
- valuescan: 已预处理为「VS 追踪摘要」——含大盘利好/利空/震荡、机会/风险/资金异动榜单与最新消息、关键支撑压力、VS 建议入场/止损/目标（须与 K 线交叉验证后写入 tradePlan）
- 若 VS 风险分高或命中风险榜，不得给出激进 BUY；若机会榜+资金异动共振，可提高置信度但须写明失效位
- derivatives（计入 technical）: 资金费率、预测资金费率、持仓量(OI)、现货-合约基差
- microstructure（计入 technical）: 订单簿深度失衡、点差、主动买占比、主动买卖名义价值
- technical 须综合（与规则引擎同源）：15m/1h/4h/1d 趋势与共振、RSI、布林、MACD、ATR%、SMA 结构、K 线支撑阻力、突破、量比、OHLCV 动量/影线、24h 行情与买卖价差、资金费率/OI/基差、盘口失衡与主动买卖、恐贪/公网宏观、策略回测末信号、量化因子中的价量项
- rule_reference: 规则引擎基线，可用于校准，但不可机械照抄
- strategyBacktests: 辩论前对注册表内全部策略在同一 K 线窗口上的样本内回测矩阵（收益、胜率、回撤、夏普、最新信号、最近成交）；存在过拟合风险，不得当作未来收益保证
- tradingAgents（若可用）: TradingAgents 多智能体辩论结果，包含市场分析师、情绪分析师、新闻分析师、基本面分析师、多头/空头分析师、风控经理、交易员计划和最终决策

策略回测矩阵使用纪律（当该维度有数据时）：
- 回测为历史样本内表现，与当前盘口/链上/新闻需交叉验证，不可单独作为 BUY/SELL 依据。
- 若多数策略回测亏损或最大回撤过大，应降低置信度或倾向 NEUTRAL/WEAK_*。
- 若回测矩阵与 K 线实际价格行为、规则引擎信号方向一致，可作为加分证据写入 reasons（需点名策略名与指标）。
- 回测最新 K 线信号仅表示该策略在最后一根 bar 的机械信号，不等于实盘建议。

TradingAgents 辩论数据使用纪律（当该维度有数据时）：
- TradingAgents 提供多视角分析，包括多头和空头对立辩论，你需要综合双方论点做出独立判断，不可偏听一方。
- 将 TradingAgents 的最终决策作为"高权重参考"而非直接采纳——它是多智能体协作的产物，但仍需与 K线实际价格行为交叉验证。
- 若 TradingAgents 最终决策与 K线价格行为方向一致，可提高置信度 5~10 分。
- 若 TradingAgents 最终决策与 K线价格行为方向冲突，必须以 K线为主，在 conflicts 中注明分歧。
- TradingAgents 风控经理的风险评估应直接纳入 risks 分析。
- TradingAgents 交易员投资计划中的价位（支撑/阻力/入场/止损）可作为 tradePlan 的参考依据，但仍需与 K线技术面和 ValueScan 支撑阻力交叉验证。

输出要求：
- 只返回 JSON，不要包含 markdown、解释性文字或代码块。
- reasons 只保留 3~6 条最关键证据，每条都要具体、可验证。
- summary 必须覆盖：市场状态、核心证据链、关键价位、主要风险、执行建议。
- tradePlan 必须可执行，且价格必须基于输入数据推导。
- analysis / factors / risks / scenarios / dataQuality / debug 必须完整输出，不可省略。
- 除 signal 外，analysis / factors / risks / scenarios / dataQuality 中所有分类字段尽量直接使用中文短语，不要返回英文枚举值。

输出 JSON 格式:
{
    "signal": "BUY" | "WEAK_BUY" | "NEUTRAL" | "WEAK_SELL" | "SELL",
    "label": "买入" | "偏多观望" | "中性观望" | "偏空观望" | "卖出",
    "score": <-100~100整数>,
    "confidence": <0~95>,
    "reasons": ["关键证据1", "关键证据2", "关键证据3"],
    "summary": "200~500字总结",
    "tradePlan": {
        "support": <数值>,
        "resistance": <数值>,
        "entryLow": <数值>,
        "entryHigh": <数值>,
        "stop": <数值>,
        "target1": <数值>,
        "target2": <数值>
    },
    "analysis": {
        "bias": "bullish|neutral|bearish",
        "marketState": "trend_continuation|trend_continuation_near_resistance|range_rebound|range_breakdown_risk|breakout_confirmation|false_breakout_risk|uncertain",
        "horizon": "intraday|intraday_swing|swing",
        "executionReadiness": "ready|watch_pullback|wait_breakout|avoid",
        "consensus": {
            "direction": "bullish|neutral|bearish",
            "agreementScore": <0~1>,
            "strength": "weak|medium|strong",
            "conflicts": ["冲突点1", "冲突点2"]
        },
        "scoreBreakdown": {
            "technical": <数值>,
            "onchain": <数值>,
            "news": <数值>,
            "positioning": <数值>,
            "riskPenalty": <数值>
        },
        "keyLevels": {
            "supports": [<数值>, <数值>],
            "resistances": [<数值>, <数值>],
            "invalidation": <数值>
        },
        "execution": {
            "timeHorizon": "4h-24h",
            "positionSize": "small|medium|large",
            "riskReward1": <数值>,
            "riskReward2": <数值>,
            "action": "执行建议"
        },
        "catalysts": ["触发条件1", "触发条件2"]
    },
    "factors": {
        "technical": {"direction": "...", "score": <数值>, "confidence": <0~1>, "highlights": ["..."]},
        "onchain": {"direction": "...", "score": <数值>, "confidence": <0~1>, "highlights": ["..."]},
        "news": {"direction": "...", "score": <数值>, "confidence": <0~1>, "highlights": ["..."]},
        "positioning": {"direction": "...", "score": <数值>, "confidence": <0~1>, "highlights": ["..."]}
    },
    "risks": [
        {"type": "...", "severity": "low|medium|high", "evidence": "...", "trigger": "...", "mitigation": "..."}
    ],
    "scenarios": [
        {"name": "bull|base|bear", "probability": <0~1>, "trigger": "...", "action": "...", "target": [<数值>, <数值>]}
    ],
    "dataQuality": {
        "coverageScore": <0~1>,
        "sourceStatus": {"market": "ok|partial|missing", "kline": "ok|partial|missing", "onchain": "ok|partial|missing", "news": "ok|partial|missing", "valuescan": "ok|partial|missing"},
        "missingFields": ["..."],
        "conflictFlags": ["..."],
        "limitations": ["..."]
    },
    "debug": {
        "calibration": {"ruleSignal": "...", "ruleScore": <数值>, "llmRuleGap": <数值>},
        "sourceRefs": {"model": "..."}
    }
}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def compute_signal_with_llm(
    data: Dict[str, Any],
    model: LLMModel = LLMModel.DEEPSEEK_V4_PRO,
) -> SignalOutput:
    """Run LLM signal analysis; falls back to rule-based engine on failure.

    Args:
        data:  Aggregated market data dict.
        model: LLMModel enum (default: DEEPSEEK_V4_PRO).
    """
    from web.api.valuescan_signal_digest import build_valuescan_digest

    try:
        mark = float((data.get("market") or {}).get("last") or 0)
    except (TypeError, ValueError):
        mark = 0.0
    data["valuescanDigest"] = build_valuescan_digest(data.get("valuescan") or {}, mark)

    context = _build_context(data)
    rule_result, rule_reference = _build_rule_reference(data)
    data_quality = _build_data_quality(data)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"分析 {data.get('symbol', '?')} 多维数据，给出综合交易信号。\n\n"
            f"【市场数据】\n{context}\n\n"
            f"【规则引擎基线，仅用于校准，不可机械照抄】\n{rule_reference}\n\n"
            f"【数据质量先验】\n{data_quality.model_dump_json(indent=2)}"
        )},
    ]

    timeout_s = 300.0
    try:
        t = float(getattr(config, "llm_signal_timeout", None) or 0)
        if t > 0:
            timeout_s = t
    except (TypeError, ValueError):
        pass

    def _rule_fallback(
        reason: str,
        source_refs: Dict[str, Any] | None = None,
    ) -> SignalOutput:
        refs: Dict[str, Any] = {"model": model.value, "fallback": True}
        if source_refs:
            refs.update(source_refs)
        return _enrich_result(SignalOutput(
            signal=rule_result.signal,
            label=rule_result.label,
            score=rule_result.score,
            confidence=rule_result.confidence,
            reasons=[*rule_result.reasons, reason],
            summary=rule_result.summary,
            tradePlan=TradePlan(**rule_result.trade_plan) if rule_result.trade_plan else None,
            dataQuality=data_quality,
            debug=DebugBlock(
                calibration=CalibrationBlock(ruleSignal=rule_result.signal, ruleScore=rule_result.score, llmRuleGap=0),
                sourceRefs=refs,
            ),
            engineMeta=EngineMeta(model=model.value, analysisVersion="v2", fallbackUsed=True),
        ), data=data, rule_result=rule_result, data_quality=data_quality, model=model.value)

    try:
        llm, resolved = _get_llm(model)
        mtail = (resolved or "").split("/")[-1].lower()
        ex_body = {"chat_template_kwargs": {"enable_thinking": False}} if mtail.startswith("qwen") else None
        logger.info("LLM signal using model: %s (wait_for=%ss, max_tokens=4096)", resolved, timeout_s)
        ulen = len((messages[1] or {}).get("content", "")) if len(messages) > 1 else 0
        logger.info("LLM signal user message size: %d chars", ulen)
        response = await asyncio.wait_for(
            llm.ainvoke(
                messages=messages,
                temperature=0.3,
                max_tokens=4096,
                extra_body=ex_body,
            ),
            timeout=timeout_s,
        )
        content = (response.content or "") if response else ""
        logger.info("LLM signal raw length: %d", len(content))
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("LLM signal raw content (trim):\n%s", content[:4000])
        return _parse_response(
            content=content,
            model=resolved,
            data=data,
            rule_result=rule_result,
            data_quality=data_quality,
        )

    except asyncio.TimeoutError:
        logger.error(
            "LLM signal timed out after %ss, falling back to rule-based (model=%s)", timeout_s, model.value
        )
        return _rule_fallback(
            f"⚠️ LLM 响应超时（{int(timeout_s)}s），已回退至规则引擎", {"timeoutSec": int(timeout_s)},
        )
    except AuthenticationError as exc:
        # Auth failures are operational/config issues; avoid noisy traceback spam.
        logger.error(
            "LLM signal authentication failed, falling back to rule-based (model=%s): %s",
            model.value,
            str(exc),
        )
        return _rule_fallback(
            "⚠️ LLM 鉴权失败（API Key 无效或已过期），已回退至规则引擎",
            {"authError": True, "errorType": "AuthenticationError"},
        )
    except Exception:
        logger.exception("LLM signal analysis failed, falling back to rule-based")
        return _rule_fallback("⚠️ LLM 分析失败，已回退至规则引擎")


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------
_VALID_SIGNALS = {"BUY", "WEAK_BUY", "NEUTRAL", "WEAK_SELL", "SELL"}


def _parse_response(content: str, model: str, data: Dict[str, Any], rule_result: Any, data_quality: DataQuality) -> SignalOutput:
    """Parse raw LLM text into SignalOutput with robust fallback."""
    text = content.strip()
    if text.startswith("```"):
        text = "\n".join(line for line in text.split("\n") if not line.strip().startswith("```"))
    try:
        obj = json_repair.loads(text)
    except Exception:
        logger.warning("LLM signal JSON parse failed: %s", text[:500])
        return _enrich_result(SignalOutput(
            reasons=["LLM 返回格式异常"],
            summary=text[:800],
            dataQuality=data_quality,
            debug=DebugBlock(
                calibration=CalibrationBlock(ruleSignal=rule_result.signal, ruleScore=rule_result.score, llmRuleGap=rule_result.score),
                sourceRefs={"model": model, "parseError": True},
            ),
            engineMeta=EngineMeta(model=model, analysisVersion="v2", fallbackUsed=False),
        ), data=data, rule_result=rule_result, data_quality=data_quality, model=model)

    if not isinstance(obj, dict):
        return _enrich_result(SignalOutput(
            reasons=["LLM 返回非对象格式"],
            summary=str(obj)[:800],
            dataQuality=data_quality,
            debug=DebugBlock(
                calibration=CalibrationBlock(ruleSignal=rule_result.signal, ruleScore=rule_result.score, llmRuleGap=rule_result.score),
                sourceRefs={"model": model, "invalidType": True},
            ),
            engineMeta=EngineMeta(model=model, analysisVersion="v2", fallbackUsed=False),
        ), data=data, rule_result=rule_result, data_quality=data_quality, model=model)

    # Normalise & clamp
    signal = str(obj.get("signal", "NEUTRAL")).upper()
    if signal not in _VALID_SIGNALS:
        signal = "NEUTRAL"

    label_map = {"BUY": "买入", "WEAK_BUY": "偏多观望", "NEUTRAL": "中性观望", "WEAK_SELL": "偏空观望", "SELL": "卖出"}
    trade_plan_raw = obj.get("tradePlan")
    trade_plan = TradePlan(**trade_plan_raw) if isinstance(trade_plan_raw, dict) else None

    reasons = obj.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = [str(reasons)]

    analysis = _safe_model(AnalysisBlock, obj.get("analysis"), AnalysisBlock)
    factors = _safe_model(FactorsBlock, obj.get("factors"), FactorsBlock)
    risks_raw = obj.get("risks") or []
    scenarios_raw = obj.get("scenarios") or []
    risks = [RiskItem(**item) for item in risks_raw if isinstance(item, dict)]
    scenarios = [ScenarioItem(**item) for item in scenarios_raw if isinstance(item, dict)]
    debug = _safe_model(DebugBlock, obj.get("debug"), DebugBlock)

    result = SignalOutput(
        signal=signal,
        label=obj.get("label") or label_map.get(signal, "中性观望"),
        score=max(-100, min(100, float(obj.get("score", 0)))),
        confidence=max(0, min(95, float(obj.get("confidence", 0)))),
        reasons=[str(r) for r in reasons],
        summary=str(obj.get("summary", "")),
        tradePlan=trade_plan,
        analysis=analysis,
        factors=factors,
        risks=risks,
        scenarios=scenarios,
        dataQuality=_safe_model(DataQuality, obj.get("dataQuality"), lambda: data_quality),
        debug=debug,
        engineMeta=EngineMeta(model=model, analysisVersion="v2", fallbackUsed=False),
    )

    result = _enrich_result(result, data=data, rule_result=rule_result, data_quality=data_quality, model=model)
    logger.info("LLM signal: %s score=%.1f confidence=%.1f", result.signal, result.score, result.confidence)
    return result
