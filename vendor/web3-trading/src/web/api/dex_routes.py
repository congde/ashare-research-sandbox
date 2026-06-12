# -*- coding: utf-8 -*-
"""
DexScan DEX data routes.

Provides dashboard API endpoints for DEX (decentralized exchange) data:
- /dashboard/dex/overview  — composite token overview
- /dashboard/dex/trending  — trending DEX tokens
- /dashboard/dex/kline     — DEX K-line data
- /dashboard/dex/trades    — recent DEX trades
- /dashboard/dex/pools     — top liquidity pools
- /dashboard/dex/holders   — top holders
- /dashboard/dex/heat      — social heat
- /dashboard/dex/risk      — risk labels
"""

import asyncio
import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from web.router import BaseRouter
from web.api import dexscan_service as dex

logger = logging.getLogger(__name__)


def _ok(**kwargs: Any) -> JSONResponse:
    return JSONResponse({"ok": True, **kwargs})


def _err(msg: str, status: int = 500) -> JSONResponse:
    return JSONResponse({"ok": False, "message": msg}, status_code=status)


class DexRoutes(BaseRouter):
    """All /dashboard/dex/* endpoints for DexScan data."""

    def __init__(self):
        super().__init__()

        # ── Composite Overview ───────────────────────────────────────
        @self._router.get("/dashboard/dex/overview")
        async def dex_overview(request: Request, symbol: str = "SOL"):
            try:
                sym = symbol.strip().upper()
                data = await dex.get_dex_overview(sym)
                return _ok(**data)
            except Exception as e:
                logger.exception("dex/overview error")
                return _err(str(e))

        # ── Trending DEX Tokens ──────────────────────────────────────
        @self._router.get("/dashboard/dex/trending")
        async def dex_trending(request: Request, chain: str = "SOL", limit: int = 20):
            try:
                limit = max(1, min(50, limit))
                data = await dex.get_dex_trending(chain=chain, limit=limit)
                # data is {total, list, extend}
                tokens = data.get("list", []) if isinstance(data, dict) else data
                return _ok(chain=chain, tokens=tokens, total=data.get("total", 0) if isinstance(data, dict) else len(tokens))
            except Exception as e:
                logger.exception("dex/trending error")
                return _err(str(e))

        # ── DEX K-line ───────────────────────────────────────────────
        @self._router.get("/dashboard/dex/kline")
        async def dex_kline(request: Request, symbol: str = "SOL", interval: str = "1h", limit: int = 200):
            try:
                sym = symbol.strip().upper()
                limit = max(10, min(500, limit))
                data = await dex.get_dex_kline(sym, interval=interval, limit=limit)
                return _ok(**data)
            except Exception as e:
                logger.exception("dex/kline error")
                return _err(str(e))

        # ── Recent DEX Trades ────────────────────────────────────────
        @self._router.get("/dashboard/dex/trades")
        async def dex_trades(request: Request, symbol: str = "SOL", page: int = 1, page_size: int = 20):
            try:
                sym = symbol.strip().upper()
                chain, address = dex.resolve_chain_address(sym)
                if not address:
                    return _err(f"No DEX address mapped for {sym}", 404)
                data = await dex.get_trade_scroll(chain, address, page=page, page_size=page_size)
                return _ok(symbol=sym, chain=chain, trades=data)
            except Exception as e:
                logger.exception("dex/trades error")
                return _err(str(e))

        # ── Top Liquidity Pools ──────────────────────────────────────
        @self._router.get("/dashboard/dex/pools")
        async def dex_pools(request: Request, symbol: str = "SOL"):
            try:
                sym = symbol.strip().upper()
                chain, address = dex.resolve_chain_address(sym)
                if not address:
                    return _err(f"No DEX address mapped for {sym}", 404)
                data = await dex.get_top_pools(chain, address)
                return _ok(symbol=sym, chain=chain, pools=data)
            except Exception as e:
                logger.exception("dex/pools error")
                return _err(str(e))

        # ── Top Holders ──────────────────────────────────────────────
        @self._router.get("/dashboard/dex/holders")
        async def dex_holders(request: Request, symbol: str = "SOL", page_size: int = 20):
            try:
                sym = symbol.strip().upper()
                chain, address = dex.resolve_chain_address(sym)
                if not address:
                    return _err(f"No DEX address mapped for {sym}", 404)
                data = await dex.get_top_holders(chain, address, page_size=page_size)
                return _ok(symbol=sym, chain=chain, holders=data)
            except Exception as e:
                logger.exception("dex/holders error")
                return _err(str(e))

        # ── Social Heat ──────────────────────────────────────────────
        @self._router.get("/dashboard/dex/heat")
        async def dex_heat(request: Request, symbol: str = "SOL"):
            try:
                sym = symbol.strip().upper()
                chain, address = dex.resolve_chain_address(sym)
                if not address:
                    return _err(f"No DEX address mapped for {sym}", 404)
                data = await dex.get_social_heat(chain, address)
                return _ok(symbol=sym, chain=chain, heat=data)
            except Exception as e:
                logger.exception("dex/heat error")
                return _err(str(e))

        # ── Risk Labels ──────────────────────────────────────────────
        @self._router.get("/dashboard/dex/risk")
        async def dex_risk(request: Request, symbol: str = "SOL"):
            try:
                sym = symbol.strip().upper()
                chain, address = dex.resolve_chain_address(sym)
                if not address:
                    return _err(f"No DEX address mapped for {sym}", 404)
                data = await dex.get_coin_risk_labels(chain, address)
                return _ok(symbol=sym, chain=chain, risk=data)
            except Exception as e:
                logger.exception("dex/risk error")
                return _err(str(e))

        # ── Token Info ───────────────────────────────────────────────
        @self._router.get("/dashboard/dex/info")
        async def dex_info(request: Request, symbol: str = "SOL"):
            try:
                sym = symbol.strip().upper()
                chain, address = dex.resolve_chain_address(sym)
                if not address:
                    return _err(f"No DEX address mapped for {sym}", 404)
                info, liq, mcap = await asyncio.gather(
                    dex.get_coin_infos(chain, address),
                    dex.get_coin_liquidity(chain, address),
                    dex.get_coin_market_cap(chain, address),
                    return_exceptions=True,
                )
                return _ok(
                    symbol=sym, chain=chain, address=address,
                    info=info if not isinstance(info, Exception) else {},
                    liquidity=liq if not isinstance(liq, Exception) else {},
                    marketCap=mcap if not isinstance(mcap, Exception) else {},
                )
            except Exception as e:
                logger.exception("dex/info error")
                return _err(str(e))

        # ── Liquidity Changes ────────────────────────────────────────
        @self._router.get("/dashboard/dex/liquidity-changes")
        async def dex_liquidity_changes(
            request: Request, symbol: str = "SOL", action_type: str = "", page: int = 1, page_size: int = 20
        ):
            try:
                sym = symbol.strip().upper()
                chain, address = dex.resolve_chain_address(sym)
                if not address:
                    return _err(f"No DEX address mapped for {sym}", 404)
                data = await dex.get_liquidity_changes(
                    chain, address, action_type=action_type, page=page, page_size=page_size
                )
                return _ok(symbol=sym, chain=chain, changes=data)
            except Exception as e:
                logger.exception("dex/liquidity-changes error")
                return _err(str(e))

        # ── Coin Rank ────────────────────────────────────────────────
        @self._router.get("/dashboard/dex/rank")
        async def dex_rank(
            request: Request, chain: str = "solana", timeframe: str = "24h",
            sort_by: str = "volume", page: int = 1, page_size: int = 20
        ):
            try:
                data = await dex.get_coin_rank(
                    chain=chain, timeframe=timeframe, sort_by=sort_by,
                    page=page, page_size=max(1, min(50, page_size)),
                )
                return _ok(chain=chain, timeframe=timeframe, sortBy=sort_by, tokens=data)
            except Exception as e:
                logger.exception("dex/rank error")
                return _err(str(e))
