# -*- coding: utf-8 -*-
"""交易决策 Agent 工具。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from agent.tools.base import BaseTool, ToolResult
from quant.decision_engine import TradingDecisionSet, make_trading_decision
from quant.hengan_data import (
    get_dex_current_price,
    get_dex_liquidity,
    get_dex_price_info,
    get_dex_risk_labels,
    get_dex_top_holders,
    get_social_heat,
)
from quant.live_trader import LiveTrader
from quant.opensearch_rag import opensearch_rag
from quant.risk_manager import RiskManager
from web.api import valuescan_service as vs
from web.api.dashboard_service import (
    fetch_kline_signals,
    fetch_market_stats,
    fetch_orderbook_snapshot,
    fetch_recent_trades,
)

logger = logging.getLogger(__name__)


def _compact_text(value: Any, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _first_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, dict)), {})
    return {}


def _direction_from_score(score: float) -> str:
    if score >= 10:
        return "bullish"
    if score <= -10:
        return "bearish"
    return "neutral"


def _flatten_strings(value: Any) -> List[str]:
    out: List[str] = []
    if isinstance(value, str):
        if value.strip():
            out.append(value.strip())
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                out.extend(_flatten_strings(item))
            elif isinstance(item, str):
                out.append(f"{key}:{item}" if key else item)
            elif isinstance(item, bool) and item:
                out.append(str(key))
    elif isinstance(value, list):
        for item in value:
            out.extend(_flatten_strings(item))
    return out


def _normalize_symbols(symbols: Any) -> List[str]:
    if isinstance(symbols, str):
        items = [s.strip() for s in symbols.split(",")]
    elif isinstance(symbols, list):
        items = [str(s).strip() for s in symbols]
    else:
        items = []
    return [s.upper().replace("/", "-") for s in items if s]


def _spot_pair(symbol: str, quote: str = "USDT") -> str:
    s = symbol.upper().replace("/", "-")
    return s if "-" in s else f"{s}-{quote.upper()}"


def _is_error_payload(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    code = value.get("code")
    message = str(value.get("msg") or value.get("message") or "")
    if code is None:
        return False
    code_text = str(code)
    if code_text in ("0", "200", "200000"):
        return False
    if code_text in ("-1", "3003", "3006", "500"):
        return True
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "invalid authorization",
            "token invalid",
            "no static resource",
        )
    )


async def _safe_call(coro, default=None):
    try:
        value = await coro
        if _is_error_payload(value):
            logger.warning(
                "trading data source returned error payload: code=%s msg=%s",
                value.get("code"),
                value.get("msg") or value.get("message"),
            )
            return default
        return value
    except Exception as exc:
        logger.warning("trading data source error: %s", exc)
        return default


class TradingDecisionTool(BaseTool):
    """Gather market/account/RAG data, ask LLM for decision, risk-check and optionally execute."""

    @property
    def name(self) -> str:
        return "trading_decision"

    @property
    def description(self) -> str:
        return (
            "Crypto trading decision tool. It gathers KuCoin market stats/K-lines, ValueScan fund/on-chain data, "
            "optional HengAn DexScan data, optional OpenSearch RAG context, account balances/positions via CCXT, "
            "then uses the mandatory trading system prompt to output buy/sell/short/cover/hold decisions. "
            "All actionable decisions pass RiskManager; real execution requires execute=true, dry_run=false and QUANT_LIVE_TRADING=true."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Symbols to analyze, e.g. ['BTC', 'ETH'] or ['BTC-USDT'].",
                },
                "quote": {"type": "string", "description": "Quote currency, default USDT."},
                "execute": {"type": "boolean", "description": "Whether to execute approved decisions."},
                "dry_run": {"type": "boolean", "description": "Keep orders in dry-run mode. Default true."},
                "confirmation": {"type": "string", "description": "Required value CONFIRM when execute=true and dry_run=false."},
                "include_account": {"type": "boolean", "description": "Fetch account balance/positions via CCXT."},
                "include_rag": {"type": "boolean", "description": "Search OpenSearch RAG knowledge."},
                "rag_size": {
                    "type": "integer",
                    "description": "Number of OpenSearch market/news docs per index. Default 4.",
                },
                "include_microstructure": {
                    "type": "boolean",
                    "description": "Include orderbook and recent trades. Default false. Use the same value for dry-run and live to keep inputs comparable.",
                },
                "include_valuescan_messages": {
                    "type": "boolean",
                    "description": "Include long ValueScan AI messages. Default false to keep prompts compact.",
                },
                "include_signal_evidence": {
                    "type": "boolean",
                    "description": "Inject Dashboard scorer and signal_analysis quality evidence into dataContext. Default true.",
                },
                "include_trading_agents": {
                    "type": "boolean",
                    "description": "Run TradingAgents debate and inject it as evidence. Default follows use_trading_agents config.",
                },
                "trading_agents_timeout_s": {
                    "type": "number",
                    "description": "Timeout seconds for each TradingAgents debate run. Default 90.",
                },
                "dex_tokens": {
                    "type": "array",
                    "description": "Optional HengAn/DexScan token descriptors: [{symbol, chainName, tokenContractAddress}]",
                    "items": {"type": "object"},
                },
            },
            "required": ["symbols"],
        }

    async def _collect_symbol_context(
        self,
        symbol: str,
        quote: str,
        include_microstructure: bool = False,
        include_valuescan_messages: bool = False,
    ) -> Dict[str, Any]:
        pair = _spot_pair(symbol, quote)
        base = pair.split("-")[0]
        vs_id = await _safe_call(vs.get_vs_token_id(base), None)

        tasks = {
            "marketStats": _safe_call(fetch_market_stats(pair), {}),
            "kline": _safe_call(fetch_kline_signals(pair, ("15min", "1hour", "4hour")), {}),
        }
        if include_microstructure:
            tasks.update({
                "orderbook": _safe_call(fetch_orderbook_snapshot(pair), {}),
                "recentTrades": _safe_call(fetch_recent_trades(pair), {}),
            })
        if vs_id:
            tasks.update({
                "valueScanFund": _safe_call(vs.get_realtime_fund(vs_id), {}),
                "valueScanFundRatio": _safe_call(vs.get_fund_market_cap_ratio(vs_id), {}),
                "valueScanFlow": _safe_call(vs.get_token_flow(vs_id), {}),
                "valueScanWhaleCost": _safe_call(vs.get_whale_cost(vs_id), []),
                "valueScanSupportResistance": _safe_call(vs.get_support_resistance(vs_id), []),
                "valueScanSentiment": _safe_call(vs.get_social_sentiment(vs_id), {}),
            })
            if include_valuescan_messages:
                tasks.update({
                    "valueScanChanceMessages": _safe_call(vs.get_ai_messages(vs_id, "chance"), []),
                    "valueScanRiskMessages": _safe_call(vs.get_ai_messages(vs_id, "risk"), []),
                    "valueScanFundsMessages": _safe_call(vs.get_ai_messages(vs_id, "funds"), []),
                })
        results = await asyncio.gather(*tasks.values())
        return {
            "symbol": base,
            "pair": pair,
            "vsTokenId": vs_id,
            **dict(zip(tasks.keys(), results)),
        }

    async def _collect_dex_context(self, dex_tokens: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        out = []
        for item in dex_tokens or []:
            symbol = item.get("symbol") or ""
            chain = item.get("chainName") or item.get("chain") or ""
            address = item.get("tokenContractAddress") or item.get("address") or ""
            if not chain or not address:
                continue
            price, info, liquidity, risk, holders = await asyncio.gather(
                _safe_call(get_dex_current_price(chain, address), {}),
                _safe_call(get_dex_price_info(chain, address), {}),
                _safe_call(get_dex_liquidity(chain, address), {}),
                _safe_call(get_dex_risk_labels(chain, address), {}),
                _safe_call(get_dex_top_holders(chain, address), {}),
            )
            if not any((price, info, liquidity, risk, holders)):
                logger.warning("DexScan returned no valid data for %s %s", chain, address)
                continue
            out.append({
                "symbol": symbol,
                "chainName": chain,
                "tokenContractAddress": address,
                "currentPrice": price,
                "priceInfo": info,
                "liquidity": liquidity,
                "riskLabels": risk,
                "topHolders": holders,
            })
        return out

    def _resolve_include_trading_agents(self, include_trading_agents: Optional[bool]) -> bool:
        if include_trading_agents is not None:
            return bool(include_trading_agents)
        try:
            from web.config import config

            return bool(getattr(config, "use_trading_agents", False))
        except Exception:
            return False

    def _valuescan_context(self, symbol_context: Dict[str, Any]) -> Dict[str, Any]:
        chance = _first_dict(symbol_context.get("valueScanChanceMessages"))
        risk = _first_dict(symbol_context.get("valueScanRiskMessages"))
        funds = _first_dict(symbol_context.get("valueScanFundsMessages"))
        return {
            "fund": symbol_context.get("valueScanFund") or {},
            "fundRatio": symbol_context.get("valueScanFundRatio") or {},
            "flow": symbol_context.get("valueScanFlow") or {},
            "tokenFlow": symbol_context.get("valueScanFlow") or {},
            "whaleCost": symbol_context.get("valueScanWhaleCost") or [],
            "supportResistance": symbol_context.get("valueScanSupportResistance") or [],
            "sentiment": symbol_context.get("valueScanSentiment") or {},
            "aiSignals": {
                "chance": chance,
                "risk": risk,
                "funds": funds,
            },
        }

    def _signal_input(self, symbol_context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "symbol": symbol_context.get("symbol"),
            "pair": symbol_context.get("pair"),
            "market": symbol_context.get("marketStats") or {},
            "kline": symbol_context.get("kline") or {},
            "news": [],
            "onchain": {"summary": "", "extra": {}},
            "onchainMetrics": {},
            "valuescan": self._valuescan_context(symbol_context),
        }

    def _valuescan_fund_score(self, symbol_context: Dict[str, Any]) -> float:
        score = 0.0
        fund = symbol_context.get("valueScanFund") or {}
        for item in fund.get("spotGoodsList") or []:
            try:
                inflow = float(item.get("tradeInflow") or 0)
            except (TypeError, ValueError):
                continue
            if abs(inflow) > 5_000_000:
                score += 20 if inflow > 0 else -20
            elif abs(inflow) > 500_000:
                score += 10 if inflow > 0 else -10

        ratio = symbol_context.get("valueScanFundRatio") or {}
        try:
            total_inflow = float(ratio.get("totalTradeInflow") or 0)
        except (TypeError, ValueError):
            total_inflow = 0.0
        if abs(total_inflow) > 10_000_000:
            score += 15 if total_inflow > 0 else -15
        return max(-100.0, min(100.0, score))

    def _valuescan_sentiment_score(self, symbol_context: Dict[str, Any]) -> float:
        sentiment = symbol_context.get("valueScanSentiment") or {}
        try:
            bullish = float(sentiment.get("bullishRatio") or 0)
            bearish = float(sentiment.get("bearishRatio") or 0)
        except (TypeError, ValueError):
            return 0.0
        if bullish <= 0 and bearish <= 0:
            return 0.0
        return max(-100.0, min(100.0, (bullish - bearish) * 100))

    def _positioning_score(self, symbol_context: Dict[str, Any]) -> float:
        whale_cost = symbol_context.get("valueScanWhaleCost") or []
        latest = next((item for item in reversed(whale_cost) if isinstance(item, dict) and item.get("cost")), {})
        if not latest:
            return 0.0
        try:
            cost = float(latest.get("cost") or 0)
            price = float(latest.get("price") or (symbol_context.get("marketStats") or {}).get("last") or 0)
        except (TypeError, ValueError):
            return 0.0
        if cost <= 0 or price <= 0:
            return 0.0
        pnl_pct = (price - cost) / cost * 100
        if pnl_pct < -10:
            return 20.0
        if pnl_pct < 0:
            return 8.0
        if pnl_pct > 30:
            return -20.0
        if pnl_pct > 15:
            return -8.0
        return 0.0

    def _build_signal_quality(self, symbol_context: Dict[str, Any], dashboard_signal: Any) -> Dict[str, Any]:
        from signal_analysis.conflict_detector import compute_consensus, detect_conflicts
        from web.api.signal_schema import FactorBlock, FactorsBlock

        technical_score = float(getattr(dashboard_signal, "score", 0) or 0)
        onchain_score = self._valuescan_fund_score(symbol_context)
        news_score = 0.0
        positioning_score = self._positioning_score(symbol_context)
        sentiment_score = self._valuescan_sentiment_score(symbol_context)
        if sentiment_score:
            news_score = sentiment_score

        factors = FactorsBlock(
            technical=FactorBlock(
                direction=_direction_from_score(technical_score),
                score=technical_score,
                confidence=min(abs(technical_score) / 100, 1.0),
                highlights=list(getattr(dashboard_signal, "reasons", [])[:3]),
            ),
            onchain=FactorBlock(
                direction=_direction_from_score(onchain_score),
                score=onchain_score,
                confidence=min(abs(onchain_score) / 100, 1.0),
                highlights=["ValueScan 资金流与市值比"],
            ),
            news=FactorBlock(
                direction=_direction_from_score(news_score),
                score=news_score,
                confidence=min(abs(news_score) / 100, 1.0),
                highlights=["ValueScan 社媒情绪"] if news_score else [],
            ),
            positioning=FactorBlock(
                direction=_direction_from_score(positioning_score),
                score=positioning_score,
                confidence=min(abs(positioning_score) / 100, 1.0),
                highlights=["ValueScan 主力成本/筹码位置"] if positioning_score else [],
            ),
        )
        conflicts = detect_conflicts(factors)
        consensus = compute_consensus(factors, conflicts)
        return {
            "factors": _model_dump(factors),
            "consensus": _model_dump(consensus),
            "conflicts": [_model_dump(item) for item in conflicts],
        }

    def _compact_ta_evidence(self, ta_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not ta_data:
            return {"available": False}
        keys = (
            "available", "symbol", "dataSource", "latencyMs",
            "marketReport", "sentimentReport", "newsReport", "fundamentalsReport",
            "bullAnalystReport", "bearAnalystReport", "riskManagerReport",
            "traderPlan", "finalDecision",
        )
        out: Dict[str, Any] = {}
        for key in keys:
            if key not in ta_data:
                continue
            value = ta_data.get(key)
            out[key] = _compact_text(value) if isinstance(value, str) else value
        return out or {"available": False}

    def _build_dex_risk_evidence(self, dex_context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not dex_context:
            return []
        from signal_analysis.rug_detector import analyze_contract_risk, assess_rug_pull_risk

        results = []
        for item in dex_context:
            if not item.get("riskLabels"):
                results.append({
                    "available": False,
                    "symbol": item.get("symbol") or "",
                    "chain": item.get("chainName") or "",
                    "contract_address": item.get("tokenContractAddress") or "",
                    "reason": "DexScan risk labels unavailable; do not treat missing labels as safe.",
                })
                continue
            labels = _flatten_strings(item.get("riskLabels"))
            signal = analyze_contract_risk(risk_labels=labels)
            assessment = assess_rug_pull_risk(
                symbol=str(item.get("symbol") or ""),
                chain=str(item.get("chainName") or ""),
                contract_address=str(item.get("tokenContractAddress") or ""),
                signals=[signal],
            )
            results.append(_model_dump(assessment))
        return results

    async def _collect_evidence(
        self,
        symbol_list: List[str],
        market_context: List[Dict[str, Any]],
        dex_context: List[Dict[str, Any]],
        quote: str,
        include_signal_evidence: bool,
        include_trading_agents: Optional[bool],
        trading_agents_timeout_s: float,
    ) -> Dict[str, Any]:
        evidence: Dict[str, Any] = {
            "dashboardSignals": {},
            "signalQuality": {},
            "dexRisk": self._build_dex_risk_evidence(dex_context),
            "tradingAgents": {"enabled": False, "bySymbol": {}},
        }

        if include_signal_evidence:
            from web.api.signal_analyzer import compute_signal

            for item in market_context:
                symbol = str(item.get("symbol") or "").upper()
                if not symbol:
                    continue
                try:
                    dashboard_signal = compute_signal(self._signal_input(item))
                    evidence["dashboardSignals"][symbol] = {
                        "source": "web.api.signal_analyzer.compute_signal",
                        "symbol": symbol,
                        "pair": item.get("pair") or _spot_pair(symbol, quote),
                        "signal": dashboard_signal.signal,
                        "label": dashboard_signal.label,
                        "score": dashboard_signal.score,
                        "confidence": dashboard_signal.confidence,
                        "reasons": dashboard_signal.reasons[:8],
                        "summary": _compact_text(dashboard_signal.summary, 1600),
                        "tradePlan": dashboard_signal.trade_plan,
                    }
                    evidence["signalQuality"][symbol] = self._build_signal_quality(item, dashboard_signal)
                except Exception as exc:
                    logger.warning("dashboard signal evidence failed for %s: %s", symbol, exc)
                    evidence["dashboardSignals"][symbol] = {"available": False, "error": str(exc)}

        if self._resolve_include_trading_agents(include_trading_agents):
            from web.api.ta_signal_bridge import run_trading_agents_for_signal

            evidence["tradingAgents"]["enabled"] = True
            tasks = [
                _safe_call(run_trading_agents_for_signal(s, timeout_s=trading_agents_timeout_s), None)
                for s in symbol_list
            ]
            ta_results = await asyncio.gather(*tasks)
            for symbol, ta_data in zip(symbol_list, ta_results):
                base = _spot_pair(symbol, quote).split("-")[0]
                evidence["tradingAgents"]["bySymbol"][base] = self._compact_ta_evidence(ta_data)

        return evidence

    async def execute(
        self,
        symbols: Any,
        quote: str = "USDT",
        execute: bool = False,
        dry_run: bool = True,
        confirmation: str = "",
        include_account: bool = True,
        include_rag: bool = True,
        rag_size: int = 4,
        include_microstructure: bool = False,
        include_valuescan_messages: bool = False,
        include_signal_evidence: bool = True,
        include_trading_agents: Optional[bool] = None,
        trading_agents_timeout_s: float = 90.0,
        dex_tokens: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> ToolResult:
        symbol_list = _normalize_symbols(symbols)
        if not symbol_list:
            return ToolResult(success=False, error="symbols is required")
        if execute and not dry_run and confirmation != "CONFIRM":
            return ToolResult(
                success=False,
                error="Live execution requires confirmation='CONFIRM'.",
            )

        microstructure_enabled = bool(include_microstructure)
        market_context = await asyncio.gather(*[
            self._collect_symbol_context(
                s,
                quote,
                include_microstructure=microstructure_enabled,
                include_valuescan_messages=include_valuescan_messages,
            )
            for s in symbol_list
        ])
        dex_context, social_heat = await asyncio.gather(
            self._collect_dex_context(dex_tokens),
            _safe_call(get_social_heat({"symbols": symbol_list}), {}),
        )

        account_snapshot: Dict[str, Any] = {"available": False}
        trader = None
        if include_account or execute:
            try:
                trader = LiveTrader(dry_run=dry_run)
                account_snapshot = await trader.get_account_snapshot([_spot_pair(s, quote).replace("-", "/") for s in symbol_list])
                account_snapshot["available"] = True
            except Exception as exc:
                account_snapshot = {"available": False, "error": str(exc)}

        data_quality = {
            "dexScan": {
                "requested": bool(dex_tokens),
                "available": bool(dex_context),
                "reason": "ok" if dex_context else ("not_requested" if not dex_tokens else "no_valid_data_returned; check DexScan auth/base URL"),
            },
            "socialHeat": {
                "available": bool(social_heat),
                "reason": "ok" if social_heat else "no_valid_data_returned; check HengAn social auth/base URL",
            },
            "account": {
                "requested": bool(include_account or execute),
                "available": bool(account_snapshot.get("available")),
                "reason": "ok" if account_snapshot.get("available") else account_snapshot.get("error") or "not_requested",
            },
        }

        rag_docs = []
        if include_rag:
            doc_size = max(1, min(int(rag_size or 4), 8))
            market_docs, news_docs = await asyncio.gather(
                opensearch_rag.search_events(symbol_list, size=doc_size, index=opensearch_rag.index, source_types=["kline", "onchain"]),
                opensearch_rag.search_events(symbol_list, size=doc_size, index=opensearch_rag.news_index, source_types=["news", "twitter"]),
            )
            rag_docs = {
                "marketEvents": market_docs,
                "nonMarketEvents": news_docs,
            }

        evidence = await self._collect_evidence(
            symbol_list=symbol_list,
            market_context=market_context,
            dex_context=dex_context,
            quote=quote,
            include_signal_evidence=include_signal_evidence,
            include_trading_agents=include_trading_agents,
            trading_agents_timeout_s=trading_agents_timeout_s,
        )

        context = {
            "symbols": symbol_list,
            "marketContext": market_context,
            "dexContext": dex_context,
            "socialHeat": social_heat,
            "account": account_snapshot,
            "ragDocs": rag_docs,
            "evidence": evidence,
            "dataQuality": data_quality,
            "executionRequest": {
                "execute": execute,
                "dry_run": dry_run,
                "include_microstructure": microstructure_enabled,
                "include_valuescan_messages": include_valuescan_messages,
                "rag_size": max(1, min(int(rag_size or 4), 8)),
            },
        }

        decision_set: TradingDecisionSet = await make_trading_decision(context)
        payload = decision_set.model_dump(mode="json")

        cash = 0.0
        total_equity = 0.0
        total_position_value = 0.0
        try:
            balance = account_snapshot.get("balance") or {}
            total = balance.get("total") or {}
            free = balance.get("free") or {}
            cash = float(free.get(quote.upper()) or free.get(quote) or 0)
            total_equity = float(total.get(quote.upper()) or total.get(quote) or cash or 0)
            for pos in account_snapshot.get("positions") or []:
                total_position_value += abs(float(pos.get("notional") or pos.get("contracts") or 0))
        except Exception:
            pass

        risk_manager = RiskManager()
        if total_equity > 0:
            risk_manager.update_equity(total_equity)
        risk_results = []
        for decision in payload.get("decisions", []):
            result = risk_manager.check_trade(decision, cash, total_position_value, total_equity)
            if result.adjusted_quantity is not None:
                decision["quantity"] = result.adjusted_quantity
            decision["riskApproved"] = result.approved
            decision["riskReason"] = result.reason
            risk_results.append({"symbol": decision.get("symbol"), "approved": result.approved, "reason": result.reason})

        execution_results = []
        if execute:
            approved = [d for d in payload.get("decisions", []) if d.get("riskApproved")]
            if trader is None:
                trader = LiveTrader(dry_run=dry_run)
            current_prices = {
                item.get("pair", "").replace("-", "/"): float((item.get("marketStats") or {}).get("last") or 0)
                for item in market_context
            }
            execution_results = await trader.execute_decisions(approved, current_prices)
            await trader.close()
        elif trader is not None:
            await trader.close()

        payload["riskResults"] = risk_results
        payload["riskState"] = risk_manager.snapshot()
        payload["executionResults"] = execution_results
        payload["dataContext"] = context
        return ToolResult(success=True, data=payload, content=str(payload))
