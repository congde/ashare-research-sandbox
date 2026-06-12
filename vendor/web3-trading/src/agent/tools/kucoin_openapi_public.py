# -*- coding: utf-8 -*-
"""
KuCoin Public OpenAPI Tool

Local tool for direct calls to KuCoin public OpenAPI endpoints (GET only).
This tool is intended for public market/documentation style queries and
explicitly blocks private/authenticated endpoint patterns.
"""

import json
import logging
import re
from typing import Any, Dict, Optional

from agent.tools.base import BaseTool, ToolResult
from libs import http

logger = logging.getLogger(__name__)


class KucoinOpenApiPublicTool(BaseTool):
    # Strict whitelist of known public, unauthenticated GET endpoints only.
    # Grouped by domain; _is_whitelisted checks ALL lists for the given base URL.

    SPOT_PUBLIC_PATTERNS = [
        r"^/api/v3/announcements$",
        r"^/api/v3/currencies$",
        r"^/api/v3/currencies/[^/]+$",
        r"^/api/v2/symbols$",
        r"^/api/v2/symbols/[^/]+$",
        r"^/api/v1/markets$",
        r"^/api/v1/prices$",
        r"^/api/v1/market/stats$",
        r"^/api/v1/market/orderbook/level1$",
        r"^/api/v1/market/orderbook/level2_(?:20|100)$",
        r"^/api/v1/market/allTickers$",
        r"^/api/v1/market/histories$",
        r"^/api/v1/market/candles$",
        r"^/api/v1/market/orderbook/callauction/level2_(?:20|100)$",
        r"^/api/v1/market/callauctionData$",
    ]

    FUTURES_PUBLIC_PATTERNS = [
        r"^/api/v1/timestamp$",
        r"^/api/v1/status$",
        r"^/api/v1/contracts/active$",
        r"^/api/v1/contracts/[^/]+$",
        r"^/api/v1/ticker$",
        r"^/api/v1/allTickers$",
        r"^/api/v1/level2/snapshot$",
        r"^/api/v1/level2/depth(?:20|100)$",
        r"^/api/v1/trade/history$",
        r"^/api/v1/kline/query$",
        r"^/api/v1/index/query$",
        r"^/api/v1/interest/query$",
        r"^/api/v1/premium/query$",
        r"^/api/v1/mark-price/[^/]+/current$",
        r"^/api/v1/funding-rate/[^/]+/current$",
        r"^/api/v1/contract/funding-rates$",
    ]

    MARGIN_PUBLIC_PATTERNS = [
        r"^/api/v3/margin/symbols$",
        r"^/api/v1/isolated/symbols$",
        r"^/api/v3/etf/info$",
        r"^/api/v1/mark-price/[^/]+/current$",
        r"^/api/v1/margin/config$",
        r"^/api/v3/mark-price/all-symbols$",
        r"^/api/v3/margin/collateralRatio$",
    ]

    CONVERT_PUBLIC_PATTERNS = [
        r"^/api/v1/convert/currencies$",
        r"^/api/v1/convert/symbol$",
    ]

    @property
    def name(self) -> str:
        return "kucoin_openapi_public"

    @property
    def description(self) -> str:
        return (
            "Directly call KuCoin public OpenAPI endpoints (GET only) for market/public data. "
            "Supports spot and futures base URLs. "
            "Only no-auth whitelist endpoints are allowed; private/authenticated endpoints are blocked."
        )

    async def mcp_description(self) -> str:
        # Use local static description to avoid remote prompt cache dependency.
        return self.description

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language intent for this OpenAPI call.",
                },
                "endpoint": {
                    "type": "string",
                    "description": "KuCoin API path, e.g. /api/v1/market/allTickers",
                },
                "market_type": {
                    "type": "string",
                    "enum": ["spot", "future"],
                    "description": "Base URL selector: spot -> api.kucoin.com, future -> api-futures.kucoin.com",
                },
                "query_params": {
                    "type": "object",
                    "description": "Optional query parameters object for the endpoint.",
                },
            },
            "required": ["query", "endpoint"],
        }

    @staticmethod
    def _is_private_endpoint(endpoint: str) -> bool:
        private_segments = {
            "account",
            "accounts",
            "orders",
            "order",
            "hf",
            "fills",
            "stop-order",
            "oco",
            "withdraw",
            "withdrawals",
            "deposit-addresses",
            "transfer",
            "sub",
            "sub-accounts",
            "api-key",
            "api-keys",
            "borrow",
            "repay",
            "lending",
            "position",
            "positions",
            "rebate",
            "affiliate",
            "broker",
            "ledger",
            "ledgers",
            "fee",
            "fees",
        }
        segments = [s for s in endpoint.lower().split("/") if s]
        return any(seg in private_segments for seg in segments)

    @staticmethod
    def _is_whitelisted(endpoint: str, market_type: str) -> bool:
        if (market_type or "").lower() in {"future", "futures"}:
            patterns = KucoinOpenApiPublicTool.FUTURES_PUBLIC_PATTERNS
        else:
            patterns = (
                KucoinOpenApiPublicTool.SPOT_PUBLIC_PATTERNS
                + KucoinOpenApiPublicTool.MARGIN_PUBLIC_PATTERNS
                + KucoinOpenApiPublicTool.CONVERT_PUBLIC_PATTERNS
            )
        return any(re.match(p, endpoint) for p in patterns)

    async def execute(
        self,
        query: str,
        endpoint: str,
        market_type: str = "spot",
        query_params: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> ToolResult:
        _ = query  # query is useful for planning visibility but not needed in HTTP call.
        query_params = query_params or {}
        endpoint = (endpoint or "").strip()
        if not endpoint:
            return ToolResult(success=False, error="Missing endpoint")

        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return ToolResult(success=False, error="endpoint must be a path (e.g. /api/v1/market/allTickers), not a full URL")

        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"

        if not endpoint.startswith("/api/"):
            return ToolResult(success=False, error="Only /api/* paths are allowed")

        if self._is_whitelisted(endpoint, market_type):
            pass  # explicitly allowed -- skip private-segment check
        elif self._is_private_endpoint(endpoint):
            return ToolResult(
                success=False,
                error=(
                    "Blocked private/authenticated endpoint pattern. "
                    "Use public market/data endpoints only."
                ),
            )
        else:
            return ToolResult(
                success=False,
                error=(
                    "Endpoint is not in no-auth GET whitelist. "
                    "Use supported public endpoints only."
                ),
            )

        base_url = "https://api.kucoin.com"
        if (market_type or "").lower() in {"future", "futures"}:
            base_url = "https://api-futures.kucoin.com"

        url = f"{base_url}{endpoint}"
        try:
            resp = await http.get(url=url, params=query_params, timeout=15, retries=1)
        except Exception as e:
            logger.warning(f"[{self.name}] request failed: url={url}, error={e}")
            return ToolResult(success=False, error=f"KuCoin OpenAPI request failed: {e}")

        if isinstance(resp, dict) and str(resp.get("code", "")) not in {"", "200000"}:
            err = resp.get("msg") or resp.get("message") or "KuCoin API returned non-success code"
            return ToolResult(
                success=False,
                error=f"{err} (code={resp.get('code')})",
                data=resp,
            )

        payload = {
            "success": True,
            "source": "kucoin_openapi_public",
            "base_url": base_url,
            "endpoint": endpoint,
            "query_params": query_params,
            "result": resp,
        }
        return ToolResult(
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
            data=payload,
            metadata={"tool_name": self.name},
        )

