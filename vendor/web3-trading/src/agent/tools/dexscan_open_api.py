# -*- coding: utf-8 -*-
"""
DexScan Open API — local agent tool.

Wraps ``web.api.dexscan_service`` so chat/DAG can query DEX on-chain data.
Tool name ``dexScan_api`` matches ``conf/skills/dexScan.yaml`` sub_tools.

Supported chains: SOL, BSC, ETH, Base, Arbitrum, Avalanche, Polygon, Optimism, Monad.
Auth: api_key query parameter (configured via dexscan_api_key in default.yaml / env DEX_API_KEY).
"""

import json
import logging
from typing import Any, Dict, List, Optional

from agent.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class DexScanOpenAPITool(BaseTool):
    """Unified DexScan DEX data API access for the agent."""

    _OPS: List[str] = [
        "current_price",
        "kline_history",
        "token_stats",
        "coin_infos",
        "price_info",
        "coin_market_cap",
        "coin_liquidity",
        "coin_risk_labels",
        "coin_rank",
        "top_holders",
        "top_pools",
        "trade_scroll",
        "liquidity_changes",
        "alpha_coin_infos",
        "social_heat",
        "dex_overview",
    ]

    @property
    def name(self) -> str:
        return "dexScan_api"

    @property
    def description(self) -> str:
        return (
            "DexScan DEX on-chain data API: token price, K-line, stats (change%/volume/high/low), "
            "liquidity, market cap, risk labels, coin rankings, top holders, top pools, trade records, "
            "liquidity changes, Alpha tokens, social heat. Covers SOL/BSC/ETH/Base/Arbitrum/Avalanche/"
            "Polygon/Optimism/Monad chains. Use operation to select dataset; pass chain + address or symbol."
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
                    "description": "Which DexScan dataset to fetch.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Token symbol (e.g. BONK, WIF, SOL). Used to resolve chain+address automatically.",
                },
                "chain": {
                    "type": "string",
                    "description": "Chain name: solana, ethereum, bsc, base, arbitrum, avalanche, polygon, optimism, monad.",
                },
                "address": {
                    "type": "string",
                    "description": "Token contract address on the specified chain.",
                },
                "extras": {
                    "type": "object",
                    "description": (
                        "Optional parameters. Keys: interval (K-line: 1s/1m/5m/15m/30m/1h/4h/1d/1w), "
                        "limit (int, max bars), timeframe (24h/1h/5m for rankings), "
                        "sort_by (volume/price/change etc.), sort_order (asc/desc), "
                        "page (int), page_size (int), action_type (add/remove for liquidity changes)."
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
        chain: str = "",
        address: str = "",
        extras: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        _ = query
        extras = extras or {}

        from web.api import dexscan_service as ds

        op = (operation or "").strip()
        if op not in self._OPS:
            return ToolResult(success=False, error=f"Unknown operation: {operation}")

        # Resolve chain + address from symbol if not explicitly provided
        resolved_chain = (chain or "").strip()
        resolved_address = (address or "").strip()
        sym = (symbol or "").strip().upper()

        if sym and not resolved_address:
            resolved_chain, resolved_address = ds.resolve_chain_address(sym)
        elif not resolved_chain:
            resolved_chain = "SOL"

        try:
            data = await self._dispatch(ds, op, resolved_chain, resolved_address, sym, extras)
        except Exception as e:
            logger.exception("dexScan_api %s failed", op)
            return ToolResult(success=False, error=f"{type(e).__name__}: {e}")

        payload = {"ok": True, "operation": op, "data": data}
        return ToolResult(
            success=True,
            content=json.dumps(payload, ensure_ascii=False, default=str),
            data=payload,
            metadata={"tool_name": self.name},
        )

    async def _dispatch(
        self, ds: Any, op: str, chain: str, address: str, symbol: str, extras: Dict[str, Any]
    ) -> Any:
        if op == "current_price":
            if not address:
                return {"error": "address required (or provide symbol)"}
            return await ds.get_current_price(chain, address)

        if op == "kline_history":
            if not address:
                return {"error": "address required (or provide symbol)"}
            interval = str(extras.get("interval") or "1h")
            limit = int(extras.get("limit") or 200)
            return await ds.get_kline_history(chain, address, interval=interval, limit=limit)

        if op == "token_stats":
            if not address:
                return {"error": "address required (or provide symbol)"}
            return await ds.get_token_stats(chain, [address])

        if op == "coin_infos":
            if not address:
                return {"error": "address required (or provide symbol)"}
            return await ds.get_coin_infos(chain, address)

        if op == "price_info":
            if not address:
                return {"error": "address required (or provide symbol)"}
            return await ds.get_price_info(chain, address)

        if op == "coin_market_cap":
            if not address:
                return {"error": "address required (or provide symbol)"}
            return await ds.get_coin_market_cap(chain, address)

        if op == "coin_liquidity":
            if not address:
                return {"error": "address required (or provide symbol)"}
            return await ds.get_coin_liquidity(chain, address)

        if op == "coin_risk_labels":
            if not address:
                return {"error": "address required (or provide symbol)"}
            return await ds.get_coin_risk_labels(chain, address)

        if op == "coin_rank":
            rank_chain = chain or str(extras.get("chain") or "SOL")
            bar = str(extras.get("bar") or extras.get("timeframe") or "24h")
            order_column = str(extras.get("order_column") or extras.get("sort_by") or "value")
            order_asc = bool(extras.get("order_asc") or (extras.get("sort_order") == "asc"))
            page = int(extras.get("page") or 1)
            page_size = int(extras.get("page_size") or 20)
            min_liquid = extras.get("min_liquid")
            min_value = extras.get("min_value")
            return await ds.get_coin_rank(
                chain=rank_chain, bar=bar,
                order_column=order_column, order_asc=order_asc,
                page=page, page_size=page_size,
                min_liquid=min_liquid, min_value=min_value,
            )

        if op == "top_holders":
            if not address:
                return {"error": "address required (or provide symbol)"}
            page = int(extras.get("page") or 1)
            page_size = int(extras.get("page_size") or 20)
            return await ds.get_top_holders(chain, address, page=page, page_size=page_size)

        if op == "top_pools":
            if not address:
                return {"error": "address required (or provide symbol)"}
            return await ds.get_top_pools(chain, address)

        if op == "trade_scroll":
            if not address:
                return {"error": "address required (or provide symbol)"}
            size = int(extras.get("size") or extras.get("page_size") or 20)
            swap_types = extras.get("swap_types")
            cursor = extras.get("cursor")
            return await ds.get_trade_scroll(
                chain, address, size=size, swap_types=swap_types, cursor=cursor,
            )

        if op == "liquidity_changes":
            if not address:
                return {"error": "address required (or provide symbol)"}
            action_type = str(extras.get("action_type") or "")
            size = int(extras.get("size") or extras.get("page_size") or 20)
            cursor = extras.get("cursor")
            return await ds.get_liquidity_changes(
                chain, address, action_type=action_type, size=size, cursor=cursor,
            )

        if op == "alpha_coin_infos":
            if not address:
                return {"error": "address required (or provide symbol)"}
            return await ds.get_alpha_coin_infos(chain, address)

        if op == "social_heat":
            if not address:
                return {"error": "address required (or provide symbol)"}
            return await ds.get_social_heat(chain, address)

        if op == "dex_overview":
            if not symbol:
                return {"error": "symbol required"}
            return await ds.get_dex_overview(symbol)

        return {"error": f"Unhandled operation: {op}"}
