# -*- coding: utf-8 -*-
"""
ValueScan Open API — local agent tool.

Wraps ``web.api.valuescan_service`` so chat/DAG can call ValueScan without MCP.
Tool name ``valueScan_api`` matches ``conf/skills/valueScan.yaml`` sub_tools.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from agent.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_CUSTOM_PATH_PREFIXES = (
    "/vs-token/",
    "/trade/",
    "/ai/",
    "/chain/",
    "/indicator/",
    "/social-sentiment/",
)


def _safe_custom_path(path: str) -> bool:
    p = (path or "").strip()
    if not p.startswith("/"):
        p = "/" + p
    return any(p.startswith(pref) for pref in _CUSTOM_PATH_PREFIXES)


class ValueScanOpenAPITool(BaseTool):
    """Unified ValueScan Open API access for the agent."""

    _OPS: List[str] = [
        "search_token",
        "token_detail",
        "chance_coin_list",
        "risk_coin_list",
        "funds_coin_list",
        "ai_messages",
        "realtime_fund",
        "fund_market_cap_ratio",
        "fund_snapshot",
        "whale_cost",
        "token_flow",
        "sector_fund_list",
        "sector_coin_trade",
        "large_transactions",
        "holder_list",
        "address_trends",
        "kline",
        "social_sentiment",
        "support_resistance",
        "price_indicators",
        "market_analyse_history",
        "fetch_full",
        "custom_post",
    ]

    @property
    def name(self) -> str:
        return "valueScan_api"

    @property
    def description(self) -> str:
        return (
            "ValueScan blockchain analytics API: exchange fund flows, AI smart picks (chance/risk/funds), "
            "on-chain whale/large txs, sector rotation, K-line, sentiment, support/resistance, price indicators. "
            "Use operation to select the dataset; pass symbol (e.g. BTC) when required. "
            "For address-level trends use operation address_trends with extras.address. "
            "custom_post is for advanced calls: extras.path + extras.body only under allowed API prefixes."
        )

    async def mcp_description(self) -> str:
        return self.description

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Short restatement of user intent (for traceability).",
                },
                "operation": {
                    "type": "string",
                    "enum": self._OPS,
                    "description": "Which ValueScan dataset to fetch.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Token symbol, e.g. BTC, ETH. Required for most per-token operations.",
                },
                "extras": {
                    "type": "object",
                    "description": (
                        "Optional. Keys: msg_type (chance|risk|funds), trade_type (1 spot, 2 futures), "
                        "tag (sector string), bucket (K-line e.g. 1h), address (for address_trends), "
                        "page, page_size, days, path, body (object, for custom_post)."
                    ),
                },
            },
            "required": ["query", "operation"],
        }

    async def execute(
        self,
        query: str,
        operation: str,
        symbol: str = "",
        extras: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        _ = query
        extras = extras or {}
        extras = {k: v for k, v in extras.items() if k not in ("user_id", "userId", "detect_language")}

        from web.api import valuescan_service as vs

        op = (operation or "").strip()
        if op not in self._OPS:
            return ToolResult(success=False, error=f"Unknown operation: {operation}")

        sym = (symbol or extras.get("symbol") or "").strip().upper()
        try:
            data = await self._dispatch(vs, op, sym, extras)
        except Exception as e:
            logger.exception("valueScan_api %s failed", op)
            return ToolResult(success=False, error=f"{type(e).__name__}: {e}")

        payload = {"ok": True, "operation": op, "data": data}
        return ToolResult(
            success=True,
            content=json.dumps(payload, ensure_ascii=False, default=str),
            data=payload,
            metadata={"tool_name": self.name},
        )

    async def _dispatch(self, vs: Any, op: str, sym: str, extras: Dict[str, Any]) -> Any:
        if op == "search_token":
            if not sym:
                return {"error": "symbol required"}
            return await vs.search_token(sym)

        if op == "token_detail":
            if not sym:
                return {"error": "symbol required"}
            vs_id = await vs.get_vs_token_id(sym)
            if not vs_id:
                return {"error": f"token not found: {sym}"}
            return await vs.get_token_detail(vs_id)

        if op == "chance_coin_list":
            return await vs.get_chance_coin_list()
        if op == "risk_coin_list":
            return await vs.get_risk_coin_list()
        if op == "funds_coin_list":
            return await vs.get_funds_coin_list()

        if op == "ai_messages":
            if not sym:
                return {"error": "symbol required"}
            vs_id = await vs.get_vs_token_id(sym)
            if not vs_id:
                return {"error": f"token not found: {sym}"}
            mt = str(extras.get("msg_type") or "chance").lower()
            if mt not in ("chance", "risk", "funds"):
                mt = "chance"
            return await vs.get_ai_messages(vs_id, mt)

        vs_id = await vs.get_vs_token_id(sym) if sym else None
        if op in ("market_analyse_history", "fetch_full"):
            if op == "market_analyse_history":
                page = int(extras.get("page") or 1)
                ps = int(extras.get("page_size") or 20)
                return await vs.get_ai_market_analyse_history(
                    page=page,
                    page_size=ps,
                    begin_time=extras.get("begin_time"),
                    end_time=extras.get("end_time"),
                )
            if not sym:
                return {"error": "symbol required for fetch_full"}
            return await vs.fetch_full_token_data(sym)

        if op not in ("custom_post", "sector_fund_list", "sector_coin_trade"):
            if not vs_id:
                return {"error": f"symbol required / token not found: {sym or '?'}"}

        if op == "realtime_fund":
            return await vs.get_realtime_fund(vs_id)
        if op == "fund_market_cap_ratio":
            return await vs.get_fund_market_cap_ratio(vs_id)
        if op == "fund_snapshot":
            return await vs.get_fund_snapshot(vs_id, extras.get("date_ms"))
        if op == "whale_cost":
            days = int(extras.get("days") or 30)
            return await vs.get_whale_cost(vs_id, days=days)
        if op == "token_flow":
            return await vs.get_token_flow(vs_id)

        if op == "sector_fund_list":
            tt = int(extras.get("trade_type") or 1)
            return await vs.get_sector_fund_list(trade_type=tt)

        if op == "sector_coin_trade":
            tag = str(extras.get("tag") or "").strip()
            if not tag:
                return {"error": "extras.tag required"}
            tt = int(extras.get("trade_type") or 1)
            return await vs.get_sector_coin_trade_list(tag, trade_type=tt)

        if op == "large_transactions":
            page = int(extras.get("page") or 1)
            ps = int(extras.get("page_size") or 20)
            return await vs.get_large_transactions(vs_id, page=page, page_size=ps)

        if op == "holder_list":
            page = int(extras.get("page") or 1)
            ps = int(extras.get("page_size") or 20)
            return await vs.get_holder_list(vs_id, page=page, page_size=ps)

        if op == "address_trends":
            addr = str(extras.get("address") or "").strip()
            if not addr:
                return {"error": "extras.address required"}
            bal, pnl, hold, tc = await asyncio.gather(
                vs.get_address_balance_trend(vs_id, addr),
                vs.get_address_profit_loss_trend(vs_id, addr),
                vs.get_address_hold_trend(vs_id, addr),
                vs.get_address_trade_count_trend(vs_id, addr),
                return_exceptions=True,
            )
            return {
                "balanceTrend": bal if isinstance(bal, list) else str(bal),
                "profitLossTrend": pnl if isinstance(pnl, list) else str(pnl),
                "holdTrend": hold if isinstance(hold, list) else str(hold),
                "tradeCountTrend": tc if isinstance(tc, list) else str(tc),
            }

        if op == "kline":
            bucket = str(extras.get("bucket") or "1h")
            days = int(extras.get("days") or 7)
            return await vs.get_kline(vs_id, bucket_type=bucket, days=days)

        if op == "social_sentiment":
            return await vs.get_social_sentiment(vs_id)

        if op == "support_resistance":
            days = int(extras.get("days") or 7)
            return await vs.get_support_resistance(vs_id, days=days)

        if op == "price_indicators":
            days = int(extras.get("days") or 30)
            return await vs.get_price_indicators(vs_id, days=days)

        if op == "custom_post":
            path = str(extras.get("path") or "").strip()
            body = extras.get("body")
            if body is None:
                body = {}
            if not isinstance(body, dict):
                return {"error": "extras.body must be a JSON object"}
            if not path or not _safe_custom_path(path):
                return {"error": "invalid or disallowed path for custom_post"}
            return await vs.vs_post(path if path.startswith("/") else f"/{path}", body)

        return {"error": "unhandled operation"}

