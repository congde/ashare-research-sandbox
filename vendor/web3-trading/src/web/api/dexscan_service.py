# -*- coding: utf-8 -*-
"""
DexScan DEX Data service layer.

Wraps DexScan REST API (https://kcapi.dexscan.trade) for DEX market data:
- Token price, stats, liquidity, market cap
- K-line / candlestick data
- DEX trade records
- Top holders, top liquidity pools
- Risk labels, coin info
- Social heat (热度)
- Alpha token info
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from libs import http

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEX_BASE_URL = os.environ.get("DEX_BASE_URL", "https://kcapi.dexscan.trade")
DEX_API_KEY = os.environ.get("DEX_API_KEY", "")

# DexScan API 要求链名使用特定大小写 (supported: SOL/BSC/ETH/Base/Arbitrum/Avalanche/Polygon/Optimism/Monad)
_CHAIN_NAME_MAP = {
    "solana": "SOL",
    "sol": "SOL",
    "ethereum": "ETH",
    "eth": "ETH",
    "bsc": "BSC",
    "base": "Base",
    "arbitrum": "Arbitrum",
    "avalanche": "Avalanche",
    "polygon": "Polygon",
    "optimism": "Optimism",
    "monad": "Monad",
}


def _normalize_chain(chain: str) -> str:
    """Normalize chain name to DexScan API expected format."""
    c = (chain or "").strip()
    return _CHAIN_NAME_MAP.get(c.lower(), c)


# ---------------------------------------------------------------------------
# TTL cache (shared with ValueScan pattern)
# ---------------------------------------------------------------------------
class _TTLCache:
    """Simple in-memory cache with per-key TTL (seconds)."""

    def __init__(self, default_ttl: int = 300):
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self._store[key] = (time.time() + (ttl or self._default_ttl), value)

    def clear(self) -> None:
        self._store.clear()


_cache = _TTLCache(default_ttl=120)


# ---------------------------------------------------------------------------
# Base request helper
# ---------------------------------------------------------------------------
def _get_api_key() -> str:
    """Resolve API key: env var > config > module-level default."""
    if DEX_API_KEY:
        return DEX_API_KEY
    try:
        from web.config import config as _cfg
        if _cfg and getattr(_cfg, "dexscan_api_key", None):
            return _cfg.dexscan_api_key
    except Exception:
        pass
    return ""


async def dex_post(path: str, body: Any = None) -> Dict[str, Any]:
    """POST to DexScan API with API-KEY header authentication.

    Args:
        path: API path (e.g. /v3/dex/market/trade-scroll)
        body: Request body — can be dict or list depending on endpoint.
    """
    api_key = _get_api_key()
    url = f"{DEX_BASE_URL.rstrip('/')}{path}"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["API-KEY"] = api_key
    raw_body = body if body is not None else {}
    try:
        data = await http.post(url, json=raw_body, headers=headers, timeout=20)
    except Exception as exc:
        logger.warning("Dex API %s request error: %s", path, exc)
        return {"code": -1, "message": str(exc)}
    if isinstance(data, dict) and data.get("code") and str(data.get("code")) not in ("0", "200"):
        logger.warning("Dex API %s error: %s", path, data.get("msg") or data.get("message"))
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Token identification — resolve chain + contract from symbol
# ---------------------------------------------------------------------------
# Common chains for popular symbols — chain names use DexScan API format
_DEFAULT_CHAINS = {
    "ETH": ("ETH", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),  # WETH
    "BTC": ("ETH", "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599"),  # WBTC on Ethereum
    "USDT": ("ETH", "0xdAC17F958D2ee523a2206206994597C13D831ec7"),
    "USDC": ("ETH", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
    "SOL": ("SOL", "So11111111111111111111111111111111111111112"),
    "BNB": ("BSC", "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"),
    "AVAX": ("Avalanche", "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7"),
    "MATIC": ("Polygon", "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270"),  # WPOL
    "POL": ("Polygon", "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270"),
}

# Popular meme / DeFi tokens on Solana
_SOL_TOKENS = {
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "WIF": "EKpQGSJtjMFqWZLfhQdANtvKahSjmFJQmNqECMn2KQ24",
    "JTO": "qz9N6s55zRnkjEtLEsLhP4X9CfrGrLh7MeMhyh3gPFJ",
    "RAY": "4k3Dyjzvzp8eMZWvxbs4uEKn9zBSR3KTykePMcGmX2Rn",
    "ORCA": "orcaEKTdK7BKzBFBaAqt9P6LDnJk5k9KxnNtWTbNMpj",
    "MANGO": "MangoCz7363OZX9bPn5sVK6VA8bPtJjNgj3g5prZkTK",
    "PYTH": "HZ1JovNiVv9GN3qAVXd2gYbB9b6GadoFU6TNpZHH8c9W",
    "RENDER": "rnd1KTkQ5NqLP2gBzpLv6Fsw55D3SxoRq2pWkeXoEBW",
}

# Popular tokens on BSC
_BSC_TOKENS = {
    "CAKE": "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
    "BNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
}

# Supported chains set for validation
_SUPPORTED_CHAINS = {"SOL", "BSC", "ETH", "Base", "Arbitrum", "Avalanche", "Polygon", "Optimism", "Monad"}


def resolve_chain_address(symbol: str) -> Tuple[str, str]:
    """Return (chainName, tokenContractAddress) for a given symbol.

    Chain names are returned in DexScan API format (SOL, ETH, BSC, Polygon, etc.).
    Falls back to ('SOL', '') if unknown — caller should handle empty address.
    """
    sym = symbol.strip().upper()
    if sym in _DEFAULT_CHAINS:
        return _DEFAULT_CHAINS[sym]
    if sym in _SOL_TOKENS:
        return ("SOL", _SOL_TOKENS[sym])
    if sym in _BSC_TOKENS:
        return ("BSC", _BSC_TOKENS[sym])
    # Unknown symbol — default to Solana (most DEX tokens are on Solana)
    return ("SOL", "")


# ---------------------------------------------------------------------------
# 1. Price & K-line
# ---------------------------------------------------------------------------
async def get_current_price(chain: str, address: str) -> Dict:
    """Get the latest price for a DEX token."""
    if not address:
        return {}
    chain = _normalize_chain(chain)
    # API expects array body: [{chainName, tokenContractAddress}]
    resp = await dex_post("/v3/dex/market/current-price", [
        {"chainName": chain, "tokenContractAddress": address},
    ])
    data = resp.get("data")
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


async def get_kline_history(
    chain: str, address: str, interval: str = "1h", limit: int = 200
) -> List[Dict]:
    """Get historical K-line data."""
    if not address:
        return []
    chain = _normalize_chain(chain)
    resp = await dex_post("/v3/dex/market/kline-history", {
        "chainName": chain, "tokenContractAddress": address,
        "interval": interval, "limit": limit,
    })
    data = resp.get("data") or []
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# 2. Token Stats & Info
# ---------------------------------------------------------------------------
async def get_token_stats(chain: str, addresses: List[str]) -> List[Dict]:
    """Batch get token statistics (change%, volume, high, low)."""
    if not addresses:
        return []
    chain = _normalize_chain(chain)
    # API expects array of coin keys
    body = [{"chainName": chain, "tokenContractAddress": addr} for addr in addresses]
    resp = await dex_post("/v3/dex/market/stats", body)
    data = resp.get("data") or []
    return data if isinstance(data, list) else []


async def get_coin_infos(chain: str, address: str) -> Dict:
    """Get token info (price, supply, holders, etc.)."""
    if not address:
        return {}
    chain = _normalize_chain(chain)
    # API expects array body
    resp = await dex_post("/v3/dex/market/coin-infos", [
        {"chainName": chain, "tokenContractAddress": address},
    ])
    data = resp.get("data")
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


async def get_price_info(chain: str, address: str) -> Dict:
    """Get price info including market cap and multi-timeframe change/volume."""
    if not address:
        return {}
    chain = _normalize_chain(chain)
    resp = await dex_post("/v3/dex/market/price-info", {
        "chainName": chain, "tokenContractAddress": address,
    })
    return resp.get("data") or {}


async def get_coin_market_cap(chain: str, address: str) -> Dict:
    """Get token market cap."""
    if not address:
        return {}
    chain = _normalize_chain(chain)
    resp = await dex_post("/v3/dex/market/coin-market-cap", {
        "chainName": chain, "tokenContractAddress": address,
    })
    return resp.get("data") or {}


async def get_coin_liquidity(chain: str, address: str) -> Dict:
    """Get token liquidity."""
    if not address:
        return {}
    chain = _normalize_chain(chain)
    resp = await dex_post("/v3/dex/market/coin-liquid", {
        "chainName": chain, "tokenContractAddress": address,
    })
    return resp.get("data") or {}


async def get_coin_risk_labels(chain: str, address: str) -> Dict:
    """Get token risk labels."""
    if not address:
        return {}
    chain = _normalize_chain(chain)
    # API expects array body
    resp = await dex_post("/v3/dex/market/coin-risk-labels", [
        {"chainName": chain, "tokenContractAddress": address},
    ])
    data = resp.get("data")
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


# ---------------------------------------------------------------------------
# 3. Rankings & Top Holders
# ---------------------------------------------------------------------------
async def get_coin_rank(
    chain: str = "SOL",
    bar: str = "24h",
    order_column: str = "value",
    order_asc: bool = False,
    page: int = 1,
    page_size: int = 20,
    min_liquid: Optional[float] = None,
    min_value: Optional[float] = None,
) -> Dict[str, Any]:
    """Get token ranking list.

    Args:
        bar: Time window — 5m, 1h, 4h, 24h, 7d, 30d
        order_column: Sort field — closePrice, priceChange, tradeCount, addressCount,
                      value, volume, marketCap, holderCount, liquid, createTime
        order_asc: True for ascending, False for descending
        min_liquid: Minimum liquidity filter
        min_value: Minimum trade value filter
    """
    chain = _normalize_chain(chain)
    body: Dict[str, Any] = {
        "chainName": chain, "bar": bar,
        "order": [{"column": order_column, "asc": order_asc}],
        "page": page, "pageSize": page_size,
    }
    if min_liquid is not None:
        body["minLiquid"] = min_liquid
    if min_value is not None:
        body["minValue"] = min_value
    resp = await dex_post("/v3/dex/market/coin-rank", body)
    data = resp.get("data") or {}
    if isinstance(data, dict):
        return data  # {total, list, extend}
    return {"total": 0, "list": data if isinstance(data, list) else []}


async def get_top_holders(chain: str, address: str, page: int = 1, page_size: int = 20) -> List[Dict]:
    """Get Top 100 holders."""
    if not address:
        return []
    chain = _normalize_chain(chain)
    resp = await dex_post("/v3/dex/market/coin-balance-top", {
        "chainName": chain, "tokenContractAddress": address,
        "page": page, "pageSize": page_size,
    })
    data = resp.get("data") or []
    return data if isinstance(data, list) else []


async def get_top_pools(chain: str, address: str) -> List[Dict]:
    """Get Top 5 liquidity pools."""
    if not address:
        return []
    chain = _normalize_chain(chain)
    resp = await dex_post("/v3/dex/market/liquid-pool-top", {
        "chainName": chain, "tokenContractAddress": address,
    })
    data = resp.get("data") or []
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# 4. Trade Records & Liquidity Changes
# ---------------------------------------------------------------------------
async def get_trade_scroll(
    chain: str, address: str, size: int = 20, swap_types: Optional[List[int]] = None,
    time_desc: bool = True, cursor: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Get DEX trade records (cursor-based pagination).

    Args:
        swap_types: [1=BUY, 2=SELL, 4=ADDLIQUID, 5=REMOVELIQUID], None for all.
        cursor: {blockTime, blockHeight, transIndex, instIndex} for pagination.
    """
    if not address:
        return {"list": [], "cursor": None}
    chain = _normalize_chain(chain)
    body: Dict[str, Any] = {
        "chainName": chain, "tokenContractAddress": address,
        "size": size, "timeDesc": time_desc,
    }
    if swap_types:
        body["swapTypes"] = swap_types
    if cursor:
        body["cursor"] = cursor
    resp = await dex_post("/v3/dex/market/trade-scroll", body)
    data = resp.get("data") or {}
    if isinstance(data, dict):
        return data
    return {"list": data if isinstance(data, list) else [], "cursor": None}


async def get_liquidity_changes(
    chain: str, address: str, action_type: str = "", size: int = 20,
    cursor: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Get liquidity change records (cursor-based pagination)."""
    if not address:
        return {"list": [], "cursor": None}
    chain = _normalize_chain(chain)
    body: Dict[str, Any] = {
        "chainName": chain, "tokenContractAddress": address,
        "size": size,
    }
    if action_type:
        body["actionType"] = action_type
    if cursor:
        body["cursor"] = cursor
    resp = await dex_post("/v3/dex/market/liquid-change-scroll", body)
    data = resp.get("data") or {}
    if isinstance(data, dict):
        return data
    return {"list": data if isinstance(data, list) else [], "cursor": None}


# ---------------------------------------------------------------------------
# 5. Social Heat
# ---------------------------------------------------------------------------
_HEAT_BASE_URL = os.environ.get("HENGAN_SOCIAL_BASE_URL", "")


async def get_social_heat(chain: str, address: str) -> Dict:
    """Get social heat data for a token.

    Note: This endpoint uses a separate base URL (hengan_social_base_url).
    If not configured, falls back to main DexScan URL with /v3/dex path.
    """
    if not address:
        return {}
    chain = _normalize_chain(chain)
    # Social heat endpoint may be on a separate host
    heat_base = _HEAT_BASE_URL
    if not heat_base:
        try:
            from web.config import config as _cfg
            if _cfg and getattr(_cfg, "hengan_social_base_url", None):
                heat_base = _cfg.hengan_social_base_url
        except Exception:
            pass
    if not heat_base:
        # Fallback: try DexScan base with social heat path
        heat_base = DEX_BASE_URL

    api_key = _get_api_key()
    url = f"{heat_base.rstrip('/')}/v3/dex/social/heatList"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["API-KEY"] = api_key
    body = [{"chainName": chain, "tokenContractAddress": address}]
    try:
        data = await http.post(url, json=body, headers=headers, timeout=20)
    except Exception as exc:
        logger.warning("Social heat API request error: %s", exc)
        return {}
    if isinstance(data, dict):
        result = data.get("data") or {}
        if isinstance(result, list):
            return result[0] if result else {}
        return result
    return {}


# ---------------------------------------------------------------------------
# 6. Alpha Token Info
# ---------------------------------------------------------------------------
async def get_alpha_coin_infos(chain: str, address: str) -> Dict:
    """Get Alpha token info."""
    if not address:
        return {}
    chain = _normalize_chain(chain)
    resp = await dex_post("/v3/dex/alpha/coin-infos", [
        {"chainName": chain, "tokenContractAddress": address},
    ])
    data = resp.get("data")
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


# ---------------------------------------------------------------------------
# Composite: DEX Overview for a symbol (used by dashboard)
# ---------------------------------------------------------------------------
async def get_dex_overview(symbol: str) -> Dict[str, Any]:
    """Fetch a composite DEX overview for the given symbol.

    Returns: {
        symbol, chain, address,
        price, stats, info, liquidity, riskLabels,
        topPools, topHolders, socialHeat, recentTrades
    }
    """
    chain, address = resolve_chain_address(symbol)
    if not address:
        return {
            "symbol": symbol, "chain": chain, "address": "",
            "error": f"No DEX contract address mapped for {symbol}",
        }

    # Parallel fetch
    import asyncio
    price_task = get_current_price(chain, address)
    info_task = get_coin_infos(chain, address)
    liq_task = get_coin_liquidity(chain, address)
    risk_task = get_coin_risk_labels(chain, address)
    pools_task = get_top_pools(chain, address)
    holders_task = get_top_holders(chain, address, page_size=10)
    heat_task = get_social_heat(chain, address)
    trades_task = get_trade_scroll(chain, address, size=15)

    price, info, liq, risk, pools, holders, heat, trades = await asyncio.gather(
        price_task, info_task, liq_task, risk_task,
        pools_task, holders_task, heat_task, trades_task,
        return_exceptions=True,
    )

    def _safe(val, default):
        return val if not isinstance(val, Exception) else default

    trades_data = _safe(trades, {})
    return {
        "symbol": symbol,
        "chain": chain,
        "address": address,
        "price": _safe(price, {}),
        "info": _safe(info, {}),
        "liquidity": _safe(liq, {}),
        "riskLabels": _safe(risk, {}),
        "topPools": _safe(pools, []),
        "topHolders": _safe(holders, []),
        "socialHeat": _safe(heat, {}),
        "recentTrades": trades_data.get("list", []) if isinstance(trades_data, dict) else [],
    }


# ---------------------------------------------------------------------------
# Composite: DEX Trending tokens (hot meme coins on Solana)
# ---------------------------------------------------------------------------
async def get_dex_trending(chain: str = "SOL", limit: int = 20) -> Dict[str, Any]:
    """Get trending DEX tokens by volume."""
    return await get_coin_rank(chain=chain, bar="24h", order_column="value", page_size=limit)


# ---------------------------------------------------------------------------
# Composite: DEX K-line for charting
# ---------------------------------------------------------------------------
async def get_dex_kline(symbol: str, interval: str = "1h", limit: int = 200) -> Dict[str, Any]:
    """Fetch DEX K-line data for a given symbol."""
    chain, address = resolve_chain_address(symbol)
    if not address:
        return {"symbol": symbol, "chain": chain, "kline": [], "error": f"No DEX address for {symbol}"}
    kline = await get_kline_history(chain, address, interval=interval, limit=limit)
    return {"symbol": symbol, "chain": chain, "interval": interval, "kline": kline}
