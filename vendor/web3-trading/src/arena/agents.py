# -*- coding: utf-8 -*-
"""Arena 交易 Agent 定义。"""

from __future__ import annotations

import math
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from arena.models import AgentProfile, AgentRiskBoundary, AgentSignal, AgentSignalSet
from arena.agent_config import model_for_agent


_OUTPUT_SCHEMA = """你必须输出一个 AgentSignalSet JSON 对象（注意外层包装）:
{
    "summary": "一句话总结当前市场状态和决策依据",
    "signals": [
        {
            "agent_name": "你的 agent 名称",
            "symbol": "BTC",
            "action": "buy|sell|short|cover|hold",
            "direction": "long|short|neutral",
            "intent": "open|close|reduce|wait",
            "execution_action": "buy|sell|short|cover|hold",
            "score": 0.0,
            "confidence": 0.0,
            "horizon": "scalp|intraday|swing|position",
            "regime": "当前市场状态描述",
            "entry_reason": ["决策理由1", "决策理由2"],
            "invalidation": "信号失效条件",
            "stop_loss_pct": 1.0,
            "take_profit_pct": 2.0,
            "data_sources": ["使用的数据源"],
            "risk_flags": ["风险标记"],
            "metadata": {}
        }
    ]
}

重要：
- 外层必须有 "summary" 和 "signals" 两个字段
- signals 数组中每个 symbol 必须有一条信号
- 不要输出裸 AgentSignal 对象，必须包裹在 AgentSignalSet 里
"""

_DIRECT_ACTIONS = {"buy", "sell", "short", "cover", "hold"}


def _execution_action_from_signal_action(action: str) -> str:
    lower = str(action or "").lower()
    if lower in _DIRECT_ACTIONS:
        return lower
    return {
        "LONG": "buy",
        "SHORT": "short",
        "WEAK_LONG": "buy",
        "WEAK_SHORT": "short",
    }.get(str(action or "").upper(), "hold")


def _direction_from_signal_action(action: str) -> str:
    lower = str(action or "").lower()
    upper = str(action or "").upper()
    if lower in {"buy", "cover"} or upper in {"LONG", "WEAK_LONG"}:
        return "long"
    if lower in {"sell", "short"} or upper in {"SHORT", "WEAK_SHORT"}:
        return "short"
    return "neutral"


def _intent_from_execution_action(action: str) -> str:
    lower = str(action or "").lower()
    if lower in {"buy", "short"}:
        return "open"
    if lower in {"sell", "cover"}:
        return "close"
    return "wait"

_PROMPT_DIR = Path(__file__).parent / "prompts"


def _load_agent_prompt(filename: str) -> str:
    return (_PROMPT_DIR / filename).read_text(encoding="utf-8").strip()


def _prompt_path(filename: str) -> str:
    return f"src/arena/prompts/{filename}"


def _agent_mode() -> str:
    return os.getenv("QUANT_ARENA_AGENT_MODE", "llm").strip().lower() or "llm"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _clamp_score(score: float) -> float:
    return max(-100.0, min(100.0, score))


def _conviction_score(score: float) -> float:
    return max(0.0, min(100.0, abs(score)))


def _confidence(score: float, floor: float = 0.2, cap: float = 0.86) -> float:
    return max(floor, min(cap, abs(score) / 100.0))


def _action_from_score(score: float, strong: float = 35.0, weak: float = 15.0) -> str:
    if score >= strong:
        return "LONG"
    if score >= weak:
        return "WEAK_LONG"
    if score <= -strong:
        return "SHORT"
    if score <= -weak:
        return "WEAK_SHORT"
    return "WAIT"


def _first_market_context(context: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    target = symbol.upper().replace("/", "-").split("-")[0]
    for item in _as_list(context.get("marketContext")):
        if str(item.get("symbol") or "").upper() == target:
            return item
    return {}


def _kline(symbol_context: Dict[str, Any], timeframe: str) -> Dict[str, Any]:
    data = symbol_context.get("kline") or {}
    item = data.get(timeframe) or {}
    return item if isinstance(item, dict) else {}


def _price(symbol_context: Dict[str, Any]) -> float:
    market = symbol_context.get("marketStats") or {}
    return _num(market.get("last") or market.get("price") or 0)


def _trend_score(value: str, weight: float) -> float:
    trend = str(value or "").lower()
    if trend == "bullish":
        return weight
    if trend == "weak_bullish":
        return weight * 0.5
    if trend == "bearish":
        return -weight
    if trend == "weak_bearish":
        return -weight * 0.5
    return 0.0


def _latest_regime(symbol_context: Dict[str, Any]) -> str:
    return str(_kline(symbol_context, "4hour").get("regime") or _kline(symbol_context, "1hour").get("regime") or "unknown")


def _atr_stop_pct(symbol_context: Dict[str, Any], multiplier: float = 1.6) -> float:
    atr_pct = _num(_kline(symbol_context, "1hour").get("atrPct") or _kline(symbol_context, "4hour").get("atrPct"), 1.5)
    return max(1.0, min(8.0, atr_pct * multiplier if atr_pct > 0 else 1.5))


def _signal(
    symbol_context: Dict[str, Any],
    agent_name: str,
    symbol: str,
    score: float,
    horizon: str,
    reasons: List[str],
    risk_flags: Optional[List[str]] = None,
    data_sources: Optional[List[str]] = None,
) -> AgentSignal:
    directional_score = _clamp_score(score)
    stop_pct = _atr_stop_pct(symbol_context)
    action = _action_from_score(directional_score)
    execution_action = _execution_action_from_signal_action(action)
    return AgentSignal(
        agent_name=agent_name,
        symbol=symbol.upper().replace("/", "-").split("-")[0],
        action=action,
        direction=_direction_from_signal_action(action),
        intent=_intent_from_execution_action(execution_action),
        execution_action=execution_action,
        score=_conviction_score(directional_score) if action != "WAIT" else min(_conviction_score(directional_score), 30.0),
        confidence=0.0 if action == "WAIT" else _confidence(directional_score),
        horizon=horizon,  # type: ignore[arg-type]
        regime=_latest_regime(symbol_context),
        entry_reason=reasons[:6],
        invalidation="价格跌破结构支撑/阻力或信号条件消失" if action != "WAIT" else "等待策略条件重新出现",
        stop_loss_pct=stop_pct if action in ("LONG", "SHORT") else None,
        take_profit_pct=max(stop_pct * 1.6, 2.0) if action in ("LONG", "SHORT") else None,
        data_sources=data_sources or ["KuCoin.marketStats", "KuCoin.kline", "local_indicators", "ValueScan.dashboardSignals"],
        risk_flags=risk_flags or [],
        metadata={"price": _price(symbol_context)},
    )


def _allows(allowed: Iterable[str], *names: str) -> bool:
    allowed_set = set(allowed)
    return any(name in allowed_set for name in names)


def _filter_market_context(context: Dict[str, Any], symbols: Iterable[str], allowed: Iterable[str]) -> List[Dict[str, Any]]:
    allowed_set = set(allowed)
    symbol_set = {str(symbol).upper().replace("/", "-").split("-")[0] for symbol in symbols}
    result: List[Dict[str, Any]] = []
    for item in _as_list(context.get("marketContext")):
        symbol = str(item.get("symbol") or "").upper()
        if symbol_set and symbol not in symbol_set:
            continue
        filtered: Dict[str, Any] = {"symbol": item.get("symbol"), "pair": item.get("pair")}
        if _allows(allowed_set, "KuCoin.marketStats", "KuCoin.market"):
            filtered["marketStats"] = item.get("marketStats") or {}
        if _allows(allowed_set, "KuCoin.kline", "local_indicators"):
            filtered["kline"] = item.get("kline") or {}
        if _allows(allowed_set, "KuCoin.orderbook"):
            filtered["orderbook"] = item.get("orderbook") or {}
        if _allows(allowed_set, "KuCoin.recentTrades"):
            filtered["recentTrades"] = item.get("recentTrades") or []
        result.append(filtered)
    return result


def _agent_account_context(context: Dict[str, Any], profile: AgentProfile) -> Dict[str, Any]:
    from arena.agent_config import account_for_agent
    accounts = context.get("accounts") if isinstance(context.get("accounts"), dict) else {}
    # 优先用环境变量配置的 account_id（如 claude），再 fallback 到 profile 硬编码值
    config_account_id = account_for_agent(profile.name, profile.account_id)
    account = accounts.get(config_account_id) or accounts.get(profile.account_id) or accounts.get(profile.name) or accounts.get("default") or context.get("account") or {"available": False}
    return account if isinstance(account, dict) else {"available": False}


def _build_agent_user_prompt(profile: AgentProfile, input_context: Dict[str, Any]) -> str:
    return (
        "你将作为一个独立 Arena Agent 生成交易信号。\n"
        "只允许基于本次输入上下文和你的 allowed_data_apis 做判断，禁止编造缺失数据。\n"
        "每个 symbols 中的交易对都必须输出一个 AgentSignal；证据不足时输出 WAIT。\n"
        "只输出 AgentSignalSet JSON，不要输出 Markdown 或额外解释。\n\n"
        f"角色/策略定义:\n{profile.role}\n{profile.strategy}\n\n"
        "允许访问的数据 API:\n"
        + "\n".join(f"- {api}" for api in profile.allowed_data_apis)
        + "\n\n固定输出 schema:\n"
        + profile.output_schema
        + "\n\n适用市场状态:\n"
        + ", ".join(profile.suitable_market_regimes)
        + "\n\n风险边界:\n"
        + json.dumps(profile.risk_boundary.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n\n本次 Agent 输入上下文:\n"
        + f"```json\n{json.dumps(input_context, ensure_ascii=False, indent=2, default=str)}\n```"
    )


def _build_agent_prompt(profile: AgentProfile, input_context: Dict[str, Any]) -> str:
    return f"SYSTEM PROMPT:\n{profile.prompt}\n\nUSER PROMPT:\n{_build_agent_user_prompt(profile, input_context)}"


def _resolve_arena_llm(model: Optional[str]) -> tuple[Any, Optional[str]]:
    """Route provider/model ids to the same LLM clients as llm_signal_analyzer."""
    raw = str(model or "").strip()
    if "/" in raw:
        try:
            from web.api.llm_signal_analyzer import _get_llm
            from web.api.signal_schema import LLMModel

            llm_inst, _resolved = _get_llm(LLMModel(raw))
            return llm_inst, raw.split("/", 1)[1]
        except ValueError:
            pass
    from llm.llm import llm as default_llm

    return default_llm, raw or None


async def _invoke_agent_llm(messages: List[Dict[str, Any]], model: Optional[str]) -> tuple[AgentSignalSet, str, str]:
    requested = str(model or "").strip() or "LLM_MODEL_NAME"
    fallback_model = (os.getenv("QUANT_ARENA_AGENT_FALLBACK_MODEL") or os.getenv("QUANT_ARENA_DEEPSEEK_FALLBACK_MODEL") or "").strip()
    client, api_model = _resolve_arena_llm(model)
    kwargs = {"model": api_model} if api_model else {}
    try:
        result: AgentSignalSet = await client.ainvoke(
            messages=messages,
            temperature=0.2,
            response_format=AgentSignalSet,
            timeout=90,
            **kwargs,
        )
        return result, api_model or requested, ""
    except Exception as exc:
        if not fallback_model or fallback_model == requested:
            raise
        fb_client, fb_api = _resolve_arena_llm(fallback_model)
        fb_kwargs = {"model": fb_api} if fb_api else {}
        result = await fb_client.ainvoke(
            messages=messages,
            temperature=0.2,
            response_format=AgentSignalSet,
            timeout=120,
            **fb_kwargs,
        )
        return result, fb_api or fallback_model, f"{type(exc).__name__}: {exc}"


class ArenaAgent(ABC):
    """Arena 交易 Agent 基类。"""

    name: str = "base"
    display_name: str = "Base Agent"
    profile: AgentProfile = AgentProfile(
        name="base",
        display_name="Base Agent",
        role="Arena 基类",
        strategy="不直接参与交易。",
        prompt="你是 Arena 基类。",
        output_schema=_OUTPUT_SCHEMA,
    )

    def build_input_context(self, context: Dict[str, Any], symbols: Iterable[str]) -> Dict[str, Any]:
        """按 Agent 的允许数据 API 过滤输入上下文。"""
        symbol_list = [str(symbol).upper().replace("/", "-") for symbol in symbols]
        allowed = self.profile.allowed_data_apis
        profile_payload = self.profile.model_dump(mode="json")
        available_apis = list(profile_payload.get("allowed_data_apis") or [])
        if not context.get("dexContext"):
            available_apis = [api for api in available_apis if not str(api).startswith("DexScan")]
        if not context.get("socialHeat"):
            available_apis = [api for api in available_apis if api != "HengAn.socialHeat"]
        if not context.get("ragDocs"):
            available_apis = [api for api in available_apis if api != "OpenSearch.RAG"]
        profile_payload["allowed_data_apis"] = available_apis
        filtered: Dict[str, Any] = {
            "agentProfile": profile_payload,
            "symbols": symbol_list,
            "dataQuality": context.get("dataQuality") or {},
            "executionRequest": context.get("executionRequest") or {},
        }
        if any(api.startswith("KuCoin") or api == "local_indicators" for api in allowed):
            filtered["marketContext"] = _filter_market_context(context, symbol_list, allowed)
        if any(api.startswith("ValueScan") or api == "signalEvidence" for api in allowed):
            filtered["evidence"] = context.get("evidence") or {}
        if any(api.startswith("DexScan") for api in allowed) and context.get("dexContext"):
            filtered["dexContext"] = context.get("dexContext") or []
        if _allows(allowed, "HengAn.socialHeat") and context.get("socialHeat"):
            filtered["socialHeat"] = context.get("socialHeat") or {}
        if _allows(allowed, "OpenSearch.RAG") and context.get("ragDocs"):
            filtered["ragDocs"] = context.get("ragDocs") or []
        if _allows(allowed, "account.snapshot"):
            filtered["account"] = _agent_account_context(context, self.profile)
            filtered["accountBinding"] = {
                "agent_name": self.name,
                "account_id": self.profile.account_id,
                "fallback_order": [self.profile.account_id, self.profile.name, "default"],
            }
        return filtered

    def build_prompt(self, input_context: Dict[str, Any]) -> str:
        """构造可落盘/打印的完整 Agent 提示词。"""
        return _build_agent_prompt(self.profile, input_context)

    async def generate_with_llm(self, input_context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        """调用 LLM，按 AgentSignalSet 结构化输出交易信号。"""
        model = model_for_agent(self.name)
        messages = [
            {"role": "system", "content": self.profile.prompt},
            {"role": "user", "content": _build_agent_user_prompt(self.profile, input_context)},
        ]
        result, actual_model, fallback_reason = await _invoke_agent_llm(messages, model)
        signals = self._normalize_llm_signals(result, symbols)
        for signal in signals:
            signal.metadata["requested_model"] = model or "LLM_MODEL_NAME"
            signal.metadata["actual_model"] = actual_model
            if fallback_reason:
                signal.metadata["fallback_reason"] = fallback_reason
        return signals

    def _normalize_llm_signals(self, result: AgentSignalSet, symbols: Iterable[str]) -> List[AgentSignal]:
        symbol_set = {str(symbol).upper().replace("/", "-").split("-")[0] for symbol in symbols}
        normalized: List[AgentSignal] = []
        seen_symbols: set[str] = set()
        for signal in result.signals:
            symbol = signal.symbol.upper().replace("/", "-").split("-")[0]
            if symbol_set and symbol not in symbol_set:
                continue
            raw_action = str(signal.execution_action or signal.action)
            execution_action = _execution_action_from_signal_action(raw_action)
            action = signal.action if signal.confidence >= self.profile.risk_boundary.min_confidence_to_trade else "hold"
            if str(action).upper() == "WAIT":
                action = "hold"
            if str(action).lower() == "hold":
                execution_action = "hold"
            is_wait = execution_action == "hold"
            if is_wait:
                score = min(abs(signal.score), 30.0)
                confidence = min(signal.confidence, self.profile.risk_boundary.min_confidence_to_trade)
                stop_loss_pct = None
                take_profit_pct = None
            else:
                score = abs(signal.score)
                confidence = signal.confidence
                stop_loss_pct = signal.stop_loss_pct
                take_profit_pct = signal.take_profit_pct
            normalized.append(signal.model_copy(update={
                "agent_name": self.name,
                "symbol": symbol,
                "action": action,
                "direction": _direction_from_signal_action(execution_action),
                "intent": _intent_from_execution_action(execution_action),
                "execution_action": execution_action,
                "score": max(0.0, min(100.0, score)),
                "confidence": max(0.0, min(1.0, confidence)),
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
                "data_sources": [source for source in signal.data_sources if source in self.profile.allowed_data_apis],
                "metadata": {
                    **signal.metadata,
                    "agent_summary": result.summary,
                    "prompt_path": self.profile.prompt_path,
                    "agent_mode": "llm",
                },
            }))
            seen_symbols.add(symbol)

        for symbol in symbol_set - seen_symbols:
            normalized.append(AgentSignal(
                agent_name=self.name,
                symbol=symbol,
                action="hold",
                direction="neutral",
                intent="wait",
                execution_action="hold",
                score=0.0,
                confidence=0.0,
                horizon="intraday",
                regime="llm_missing_output",
                entry_reason=["LLM 未返回该 symbol 的有效信号"],
                invalidation="等待下一轮完整输出",
                data_sources=[],
                risk_flags=["missing_llm_signal"],
                metadata={"agent_summary": result.summary, "prompt_path": self.profile.prompt_path, "agent_mode": "llm"},
            ))
        return normalized

    async def generate(self, context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        """基于同一份上下文生成每个 symbol 的独立信号。"""
        input_context = context if context.get("agentProfile") else self.build_input_context(context, symbols)
        if _agent_mode() == "rule":
            signals = await self.generate_rule(input_context, symbols)
            return [signal.model_copy(update={"metadata": {**signal.metadata, "agent_mode": "rule"}}) for signal in signals]
        return await self.generate_with_llm(input_context, symbols)

    @abstractmethod
    async def generate_rule(self, context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        """基于本地规则生成信号，用于测试、降级和对照。"""


class TrendHunterAgent(ArenaAgent):
    profile = AgentProfile(
        name="trend_hunter",
        display_name="Trend_Hunter",
        account_id="trend_hunter",
        role="趋势延续交易 Agent，专注 1h/4h 结构方向和动量一致性。",
        strategy="只在中高周期趋势、MACD 动能、价格相对 MA20 同向时提高分数；震荡或信号冲突时等待。",
        prompt=_load_agent_prompt("trend_hunter.md"),
        prompt_path=_prompt_path("trend_hunter.md"),
        allowed_data_apis=["KuCoin.marketStats", "KuCoin.kline", "local_indicators", "ValueScan.dashboardSignals", "account.snapshot"],
        output_schema=_OUTPUT_SCHEMA,
        suitable_market_regimes=["trending", "breakout", "transitional"],
        risk_boundary=AgentRiskBoundary(
            max_position_risk_pct=0.01,
            max_gross_exposure_pct=0.12,
            min_confidence_to_trade=0.55,
            max_leverage=1.0,
            notes=["禁止逆 4h 主趋势主动开仓", "ATR 止损优先"],
        ),
    )
    name = "trend_hunter"
    display_name = "Trend_Hunter"

    async def generate_rule(self, context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        signals = []
        for symbol in symbols:
            item = _first_market_context(context, symbol)
            one_hour = _kline(item, "1hour")
            four_hour = _kline(item, "4hour")
            score = 0.0
            reasons: List[str] = []

            score += _trend_score(four_hour.get("trend"), 32)
            score += _trend_score(one_hour.get("trend"), 20)
            if four_hour.get("trend"):
                reasons.append(f"4h趋势={four_hour.get('trend')}")
            if one_hour.get("trend"):
                reasons.append(f"1h趋势={one_hour.get('trend')}")

            macd_hist = _num(one_hour.get("macdHistogram") or four_hour.get("macdHistogram"), 0)
            if macd_hist > 0:
                score += 10
                reasons.append("MACD动能为正")
            elif macd_hist < 0:
                score -= 10
                reasons.append("MACD动能为负")

            price = _price(item)
            sma20 = _num(one_hour.get("sma20"), 0)
            if price > 0 and sma20 > 0:
                score += 8 if price >= sma20 else -8
                reasons.append("价格位于1h MA20上方" if price >= sma20 else "价格位于1h MA20下方")

            signals.append(_signal(item, self.name, symbol, score, "swing", reasons, data_sources=self.profile.allowed_data_apis))
        return signals


class GreedNinjaAgent(ArenaAgent):
    profile = AgentProfile(
        name="greed_ninja",
        display_name="Greed_Ninja",
        account_id="greed_ninja",
        role="情绪和区间极端反转 Agent，专注 RSI、布林带和区间位置的过热/过冷。",
        strategy="在 RSI/布林/区间位置同时极端时给出逆向信号；若逆 4h 趋势则降权，不追单。",
        prompt=_load_agent_prompt("greed_ninja.md"),
        prompt_path=_prompt_path("greed_ninja.md"),
        allowed_data_apis=["KuCoin.marketStats", "KuCoin.kline", "local_indicators", "ValueScan.dashboardSignals", "HengAn.socialHeat", "OpenSearch.RAG", "signalEvidence", "account.snapshot"],
        output_schema=_OUTPUT_SCHEMA,
        suitable_market_regimes=["ranging", "transitional", "high_vol"],
        risk_boundary=AgentRiskBoundary(
            max_position_risk_pct=0.008,
            max_gross_exposure_pct=0.08,
            min_confidence_to_trade=0.60,
            max_leverage=1.0,
            notes=["逆大周期趋势必须降权", "只做极端位置，不在中位区开仓"],
        ),
    )
    name = "greed_ninja"
    display_name = "Greed_Ninja"

    async def generate_rule(self, context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        signals = []
        for symbol in symbols:
            item = _first_market_context(context, symbol)
            one_hour = _kline(item, "1hour")
            four_hour = _kline(item, "4hour")
            rsi = _num(one_hour.get("rsi"), 50)
            bb_pct_b = _num(one_hour.get("bbPctB"), 50)
            range_pos = _num(one_hour.get("rangePos"), 50)
            trend = str(four_hour.get("trend") or "")
            score = 0.0
            reasons: List[str] = []
            risk_flags: List[str] = []

            if rsi <= 25:
                score += 36
                reasons.append(f"1h RSI极端超卖={rsi:.1f}")
            elif rsi <= 35:
                score += 20
                reasons.append(f"1h RSI偏超卖={rsi:.1f}")
            elif rsi >= 75:
                score -= 36
                reasons.append(f"1h RSI极端超买={rsi:.1f}")
            elif rsi >= 65:
                score -= 20
                reasons.append(f"1h RSI偏超买={rsi:.1f}")

            if bb_pct_b <= 10:
                score += 18
                reasons.append("价格接近布林下轨")
            elif bb_pct_b >= 90:
                score -= 18
                reasons.append("价格接近布林上轨")

            if range_pos <= 20:
                score += 12
                reasons.append("价格接近区间下沿")
            elif range_pos >= 80:
                score -= 12
                reasons.append("价格接近区间上沿")

            if "bullish" in trend and score < 0:
                score *= 0.6
                risk_flags.append("逆4h多头趋势做空，降权")
            if "bearish" in trend and score > 0:
                score *= 0.6
                risk_flags.append("逆4h空头趋势做多，降权")

            signals.append(_signal(item, self.name, symbol, score, "intraday", reasons, risk_flags, self.profile.allowed_data_apis))
        return signals


class AIGridAgent(ArenaAgent):
    profile = AgentProfile(
        name="ai_grid",
        display_name="AI_Grid",
        account_id="ai_grid",
        role="震荡网格/均值回归 Agent，只在区间市场寻找边缘位置。",
        strategy="当 1h regime 为 ranging 且价格接近区间上下沿时输出均值回归信号；非震荡市场等待。",
        prompt=_load_agent_prompt("ai_grid.md"),
        prompt_path=_prompt_path("ai_grid.md"),
        allowed_data_apis=["KuCoin.marketStats", "KuCoin.kline", "local_indicators", "ValueScan.dashboardSignals", "DexScan.risk", "account.snapshot"],
        output_schema=_OUTPUT_SCHEMA,
        suitable_market_regimes=["ranging"],
        risk_boundary=AgentRiskBoundary(
            max_position_risk_pct=0.006,
            max_gross_exposure_pct=0.10,
            min_confidence_to_trade=0.55,
            max_leverage=1.0,
            notes=["非 ranging 禁止主动开仓", "区间中部无优势时等待"],
        ),
    )
    name = "ai_grid"
    display_name = "AI_Grid"

    async def generate_rule(self, context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        signals = []
        for symbol in symbols:
            item = _first_market_context(context, symbol)
            one_hour = _kline(item, "1hour")
            regime = str(one_hour.get("regime") or "unknown")
            range_pos = _num(one_hour.get("rangePos"), 50)
            bb_pct_b = _num(one_hour.get("bbPctB"), 50)
            score = 0.0
            reasons: List[str] = []
            risk_flags: List[str] = []

            if regime != "ranging":
                risk_flags.append(f"非震荡区间 regime={regime}")
                reasons.append("网格策略等待震荡区间")
            else:
                if range_pos <= 25 or bb_pct_b <= 20:
                    score += 38
                    reasons.append("震荡区间下沿，适合均值回归做多")
                elif range_pos >= 75 or bb_pct_b >= 80:
                    score -= 38
                    reasons.append("震荡区间上沿，适合均值回归做空/减仓")
                else:
                    reasons.append("区间中部，没有网格边缘优势")

            signals.append(_signal(item, self.name, symbol, score, "intraday", reasons, risk_flags, self.profile.allowed_data_apis))
        return signals


class ReversalScalperAgent(ArenaAgent):
    profile = AgentProfile(
        name="reversal_scalper",
        display_name="Reversal_Scalper",
        account_id="reversal_scalper",
        role="短线极端反转 Agent，关注 15m 超买/超卖、布林位置和放量确认。",
        strategy="只有 15m RSI 与布林带同时极端，并有放量确认时才提高分数；缺盘口/逐笔数据时只允许 paper 参考。",
        prompt=_load_agent_prompt("reversal_scalper.md"),
        prompt_path=_prompt_path("reversal_scalper.md"),
        allowed_data_apis=["KuCoin.marketStats", "KuCoin.kline", "KuCoin.orderbook", "KuCoin.recentTrades", "local_indicators", "DexScan.risk", "HengAn.socialHeat", "account.snapshot"],
        output_schema=_OUTPUT_SCHEMA,
        suitable_market_regimes=["high_vol", "ranging", "transitional"],
        risk_boundary=AgentRiskBoundary(
            max_position_risk_pct=0.004,
            max_gross_exposure_pct=0.05,
            min_confidence_to_trade=0.65,
            max_leverage=1.0,
            notes=["缺盘口/逐笔时不得实盘", "短线信号必须快进快出"],
        ),
    )
    name = "reversal_scalper"
    display_name = "Reversal_Scalper"

    async def generate_rule(self, context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        signals = []
        for symbol in symbols:
            item = _first_market_context(context, symbol)
            fifteen_min = _kline(item, "15min")
            rsi = _num(fifteen_min.get("rsi"), 50)
            bb_pct_b = _num(fifteen_min.get("bbPctB"), 50)
            vol_ratio = _num(fifteen_min.get("volRatio"), 1)
            score = 0.0
            reasons: List[str] = []
            risk_flags: List[str] = []

            if rsi <= 25 and bb_pct_b <= 10:
                score += 34
                reasons.append("15m超卖且贴近布林下轨")
            elif rsi >= 75 and bb_pct_b >= 90:
                score -= 34
                reasons.append("15m超买且贴近布林上轨")

            if abs(score) > 0 and vol_ratio >= 1.5:
                score *= 1.25
                reasons.append(f"15m放量确认 volRatio={vol_ratio:.2f}")
            if not item.get("orderbook") and not item.get("recentTrades"):
                risk_flags.append("未启用盘口/逐笔数据，短线反转信号仅供paper参考")

            signals.append(_signal(item, self.name, symbol, score, "scalp", reasons, risk_flags, self.profile.allowed_data_apis))
        return signals


class TechnicalSignalAgent(ArenaAgent):
    profile = AgentProfile(
        name="technical_signal",
        display_name="Technical_Signal",
        account_id="technical_signal",
        role="本地技术信号规则 Agent，复用趋势、RSI、布林、突破、量能和市场状态评分。",
        strategy="只使用本地指标做规则评分；分数超过阈值才输出可执行方向，否则等待。",
        prompt="你是本地技术信号规则 Agent，本 Agent 不调用 LLM。",
        prompt_path="src/backtest/strategies/technical_signal.py",
        allowed_data_apis=["KuCoin.marketStats", "KuCoin.kline", "local_indicators", "ValueScan.dashboardSignals", "account.snapshot"],
        output_schema=_OUTPUT_SCHEMA,
        suitable_market_regimes=["trending", "breakout", "ranging", "transitional"],
        risk_boundary=AgentRiskBoundary(
            max_position_risk_pct=0.006,
            max_gross_exposure_pct=0.08,
            min_confidence_to_trade=0.55,
            max_leverage=1.0,
            paper_only_until_review=False,
            notes=["本地规则策略", "实盘仍必须经过 RiskManager 和 LiveTrader"],
        ),
    )
    name = "technical_signal"
    display_name = "Technical_Signal"

    async def generate(self, context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        input_context = context if context.get("agentProfile") else self.build_input_context(context, symbols)
        signals = await self.generate_rule(input_context, symbols)
        return [signal.model_copy(update={"metadata": {**signal.metadata, "agent_mode": "rule"}}) for signal in signals]

    async def generate_rule(self, context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        signals = []
        for symbol in symbols:
            item = _first_market_context(context, symbol)
            one_hour = _kline(item, "1hour")
            trend = str(one_hour.get("trend") or "")
            rsi = _num(one_hour.get("rsi"), 50)
            bb_pct_b = _num(one_hour.get("bbPctB"), 50)
            breakout = str(one_hour.get("breakout") or "")
            vol_ratio = _num(one_hour.get("volRatio"), 1)
            range_pos = _num(one_hour.get("rangePos"), 50)
            regime = str(one_hour.get("regime") or "")

            score = _trend_score(trend, 20)
            reasons: List[str] = [f"1h趋势={trend or 'unknown'}"]
            risk_flags: List[str] = []
            if rsi >= 80:
                score -= 12
                reasons.append(f"RSI极端超买={rsi:.1f}")
            elif rsi >= 70:
                score -= 7.2
                reasons.append(f"RSI超买={rsi:.1f}")
            elif rsi <= 20:
                score += 12
                reasons.append(f"RSI极端超卖={rsi:.1f}")
            elif rsi <= 30:
                score += 7.2
                reasons.append(f"RSI超卖={rsi:.1f}")
            if bb_pct_b >= 100:
                score -= 6
                reasons.append("触及/突破布林上轨")
            elif bb_pct_b <= 0:
                score += 6
                reasons.append("触及/跌破布林下轨")
            if breakout == "bullish":
                score += 15 if vol_ratio >= 1.5 else 8
                reasons.append("放量向上突破" if vol_ratio >= 1.5 else "向上突破")
            elif breakout == "bearish":
                score -= 15 if vol_ratio >= 1.5 else 8
                reasons.append("放量向下突破" if vol_ratio >= 1.5 else "向下突破")
            if regime == "ranging":
                if range_pos >= 80:
                    score -= 4
                    reasons.append("震荡区间上沿")
                elif range_pos <= 20:
                    score += 4
                    reasons.append("震荡区间下沿")
            if abs(score) < 25:
                risk_flags.append("技术综合分未达到入场阈值")
            signals.append(_signal(item, self.name, symbol, score, "intraday", reasons, risk_flags, self.profile.allowed_data_apis))
        return signals


class ClaudeAgent(ArenaAgent):
    profile = AgentProfile(
        name="claude_agent",
        display_name="Claude_Agent",
        account_id="claude_agent",
        role="通用 LLM 交易决策 Agent，综合市场结构、账户、证据、RAG 和风险状态。",
        strategy="按风险优先提示词完成市场结构、多信号一致性、账户约束、方向与置信度推理，输出 AgentSignalSet。",
        prompt=_load_agent_prompt("claude_agent.md"),
        prompt_path=_prompt_path("claude_agent.md"),
        allowed_data_apis=[
            "KuCoin.marketStats",
            "KuCoin.kline",
            "KuCoin.orderbook",
            "KuCoin.recentTrades",
            "local_indicators",
            "ValueScan.dashboardSignals",
            "DexScan.risk",
            "HengAn.socialHeat",
            "OpenSearch.RAG",
            "account.snapshot",
            "signalEvidence",
        ],
        output_schema=_OUTPUT_SCHEMA,
        suitable_market_regimes=["trending", "breakout", "ranging", "high_vol", "transitional"],
        risk_boundary=AgentRiskBoundary(
            max_position_risk_pct=0.02,
            max_gross_exposure_pct=0.30,
            min_confidence_to_trade=0.50,
            max_leverage=5.0,
            paper_only_until_review=False,
            notes=["真实执行必须经过 RiskManager 和 LiveTrader", "数据源不可用时必须保守"],
        ),
    )
    name = "claude_agent"
    display_name = "Claude_Agent"

    def _system_prompt(self) -> str:
        from quant.decision_engine import load_trading_system_prompt

        return f"{self.profile.prompt}\n\n## 项目风险优先交易系统提示词\n\n{load_trading_system_prompt()}"

    def build_prompt(self, input_context: Dict[str, Any]) -> str:
        return f"SYSTEM PROMPT:\n{self._system_prompt()}\n\nUSER PROMPT:\n{_build_agent_user_prompt(self.profile, input_context)}"

    async def generate_with_llm(self, input_context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        model = (model_for_agent(self.name) or "").strip()
        result, actual_model, fallback_reason = await _invoke_agent_llm([
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": _build_agent_user_prompt(self.profile, input_context)},
        ], model)
        signals = self._normalize_llm_signals(result, symbols) if result.signals else []
        missing_only = bool(signals) and all("missing_llm_signal" in signal.risk_flags for signal in signals)
        if not signals or missing_only:
            fallback_signals = await self.generate_rule(input_context, symbols)
            if fallback_signals:
                return [signal.model_copy(update={
                    "metadata": {
                        **signal.metadata,
                        "requested_model": model or "LLM_MODEL_NAME",
                        "actual_model": actual_model,
                        "llm_agent_summary": result.summary,
                        "llm_agent_signal_count": len(result.signals or []),
                        "fallback_reason": fallback_reason or ("missing_agent_signal" if missing_only else "empty_agent_signal_set"),
                        "agent_mode": "llm_decision_fallback",
                    },
                }) for signal in fallback_signals]
        for signal in signals:
            signal.metadata["requested_model"] = model or "LLM_MODEL_NAME"
            signal.metadata["actual_model"] = actual_model
            if fallback_reason:
                signal.metadata["fallback_reason"] = fallback_reason
        return signals

    async def generate_rule(self, context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        from quant.decision_engine import make_trading_decision

        decision_set = await make_trading_decision({**context, "arenaAgent": self.name})
        signals: List[AgentSignal] = []
        seen_symbols: set[str] = set()
        for decision in decision_set.decisions:
            action = decision.action if decision.action in _DIRECT_ACTIONS else "hold"
            score = min(100.0, decision.confidence * 100.0)
            symbol = decision.symbol.upper().replace("/", "-").split("-")[0]
            signals.append(AgentSignal(
                agent_name=self.name,
                symbol=symbol,
                action=action,  # type: ignore[arg-type]
                direction=_direction_from_signal_action(action),
                intent=_intent_from_execution_action(action),
                execution_action=action,  # type: ignore[arg-type]
                score=score,
                confidence=decision.confidence,
                horizon="intraday",
                regime="llm",
                entry_reason=decision.evidence_for or ([decision.rationale] if decision.rationale else []),
                invalidation=decision.invalidation,
                stop_loss_pct=None,
                take_profit_pct=None,
                data_sources=decision.data_sources,
                risk_flags=decision.evidence_against,
                metadata={
                    "decision": decision.model_dump(mode="json"),
                    "decision_summary": decision_set.summary,
                    "fallback_decision_count": len(decision_set.decisions),
                    "fallback_risk_state": decision_set.risk_state,
                    "fallback_should_execute": decision_set.should_execute,
                },
            ))
            seen_symbols.add(symbol)
        for symbol in {str(item).upper().replace("/", "-").split("-")[0] for item in symbols} - seen_symbols:
            signals.append(AgentSignal(
                agent_name=self.name,
                symbol=symbol,
                action="hold",
                direction="neutral",
                intent="wait",
                execution_action="hold",
                score=0.0,
                confidence=0.0,
                horizon="intraday",
                regime="llm_decision_empty",
                entry_reason=["TradingDecision 未返回该 symbol 的决策"],
                invalidation="等待下一轮完整输出",
                risk_flags=["empty_trading_decision"],
                metadata={
                    "decision_summary": decision_set.summary,
                    "fallback_decision_count": len(decision_set.decisions),
                    "fallback_risk_state": decision_set.risk_state,
                    "fallback_should_execute": decision_set.should_execute,
                    "input_data_quality": context.get("dataQuality") or {},
                },
            ))
        return signals


class DashboardDeepSeekAgent(ArenaAgent):
    profile = AgentProfile(
        name="dashboard_deepseek",
        display_name="Dashboard_DeepSeek",
        account_id="dashboard_deepseek",
        role="Dashboard DeepSeek 信号分析 Agent，复用看板多维行情、证据和账户上下文做保守交易判断。",
        strategy="先判断数据质量和风险，再给出 buy/sell/short/cover/hold；信号冲突、数据缺失或风险收益不清晰时等待。",
        prompt=_load_agent_prompt("dashboard_deepseek.md"),
        prompt_path=_prompt_path("dashboard_deepseek.md"),
        allowed_data_apis=[
            "KuCoin.marketStats",
            "KuCoin.kline",
            "KuCoin.orderbook",
            "KuCoin.recentTrades",
            "local_indicators",
            "ValueScan.dashboardSignals",
            "DexScan.risk",
            "HengAn.socialHeat",
            "OpenSearch.RAG",
            "account.snapshot",
            "signalEvidence",
        ],
        output_schema=_OUTPUT_SCHEMA,
        suitable_market_regimes=["trending", "breakout", "ranging", "high_vol", "transitional"],
        risk_boundary=AgentRiskBoundary(
            max_position_risk_pct=0.01,
            max_gross_exposure_pct=0.12,
            min_confidence_to_trade=0.58,
            max_leverage=1.0,
            paper_only_until_review=True,
            notes=["Dashboard DeepSeek Agent 默认只做 paper 信号", "数据质量不足时必须 hold"],
        ),
    )
    name = "dashboard_deepseek"
    display_name = "Dashboard_DeepSeek"

    async def generate_with_llm(self, input_context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        model = model_for_agent(self.name, os.getenv("QUANT_ARENA_DEEPSEEK_MODEL", "deepseek/deepseek-v4-pro")) or "deepseek/deepseek-v4-pro"
        messages = [
            {"role": "system", "content": self.profile.prompt},
            {"role": "user", "content": _build_agent_user_prompt(self.profile, input_context)},
        ]
        result, actual_model, fallback_reason = await _invoke_agent_llm(messages, model)
        metadata = {"requested_model": model, "actual_model": actual_model}
        if fallback_reason:
            metadata["fallback_reason"] = fallback_reason
        return [signal.model_copy(update={"metadata": {**signal.metadata, **metadata}}) for signal in self._normalize_llm_signals(result, symbols)]

    async def generate_rule(self, context: Dict[str, Any], symbols: Iterable[str]) -> List[AgentSignal]:
        agent = ClaudeAgent()
        return [signal.model_copy(update={"agent_name": self.name}) for signal in await agent.generate_rule(context, symbols)]


AGENT_REGISTRY = {
    TrendHunterAgent.name: TrendHunterAgent,
    GreedNinjaAgent.name: GreedNinjaAgent,
    AIGridAgent.name: AIGridAgent,
    ReversalScalperAgent.name: ReversalScalperAgent,
    TechnicalSignalAgent.name: TechnicalSignalAgent,
    ClaudeAgent.name: ClaudeAgent,
    DashboardDeepSeekAgent.name: DashboardDeepSeekAgent,
}


def normalize_agent_names(names: Iterable[str] | str | None) -> List[str]:
    if names is None:
        return ["claude_agent", "trend_hunter", "greed_ninja", "ai_grid", "reversal_scalper"]
    if isinstance(names, str):
        raw_names = [item.strip() for item in names.split(",")]
    else:
        raw_names = [str(item).strip() for item in names]
    result = []
    for name in raw_names:
        normalized = name.lower().replace("-", "_")
        if normalized and normalized in AGENT_REGISTRY and normalized not in result:
            result.append(normalized)
    return result or ["claude_agent", "trend_hunter", "greed_ninja", "ai_grid", "reversal_scalper"]


def create_agent(name: str) -> ArenaAgent:
    cls = AGENT_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown arena agent: {name}")
    return cls()