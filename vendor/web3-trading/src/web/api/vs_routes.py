# -*- coding: utf-8 -*-
"""
ValueScan dashboard routes.

Separated from dashboard_api.py for maintainability.
Each endpoint follows the pattern: resolve symbol → gather data → return JSON.
"""

import asyncio
import logging
from typing import Any, Dict

from fastapi import Request
from fastapi.responses import JSONResponse

from web.router import BaseRouter
from web.api import valuescan_service as vs

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers — eliminate per-handler boilerplate
# ---------------------------------------------------------------------------
def _ok(**kwargs: Any) -> JSONResponse:
    return JSONResponse({"ok": True, **kwargs})


def _err(msg: str, status: int = 500) -> JSONResponse:
    return JSONResponse({"ok": False, "message": msg}, status_code=status)


async def _resolve_or_404(symbol: str):
    """Resolve symbol → vsTokenId, returning (vs_id, err_response).
    If resolution fails, err_response is a JSONResponse to return immediately."""
    vs_id = await vs.get_vs_token_id(symbol)
    if not vs_id:
        return None, _err(f"Token {symbol} not found in ValueScan", 404)
    return vs_id, None


def _safe(items, expected_type):
    """Guard asyncio.gather results against exceptions."""
    return items if isinstance(items, expected_type) else expected_type()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
class VsRoutes(BaseRouter):
    """All /dashboard/vs/* endpoints for ValueScan data."""

    def __init__(self):
        super().__init__()

        # ── AI Smart Picks ──────────────────────────────────────────
        @self._router.get("/dashboard/vs/ai-picks")
        async def ai_picks(request: Request):
            try:
                chance, risk, funds = await asyncio.gather(
                    vs.get_chance_coin_list(),
                    vs.get_risk_coin_list(),
                    vs.get_funds_coin_list(),
                    return_exceptions=True,
                )
                return _ok(
                    chance=_safe(chance, list),
                    risk=_safe(risk, list),
                    funds=_safe(funds, list),
                )
            except Exception as e:
                logger.exception("vs/ai-picks error")
                return _err(str(e))

        @self._router.get("/dashboard/vs/ai-messages")
        async def ai_messages(request: Request, symbol: str = "BTC", msg_type: str = "chance"):
            try:
                vs_id, err = await _resolve_or_404(symbol)
                if err:
                    return err
                msgs = await vs.get_ai_messages(vs_id, msg_type)
                return _ok(symbol=symbol, type=msg_type, messages=msgs)
            except Exception as e:
                logger.exception("vs/ai-messages error")
                return _err(str(e))

        # ── Exchange Fund Monitoring ────────────────────────────────
        @self._router.get("/dashboard/vs/token-fund")
        async def token_fund(request: Request, symbol: str = "BTC"):
            try:
                vs_id, err = await _resolve_or_404(symbol)
                if err:
                    return err
                fund, ratio, sentiment, sr = await asyncio.gather(
                    vs.get_realtime_fund(vs_id),
                    vs.get_fund_market_cap_ratio(vs_id),
                    vs.get_social_sentiment(vs_id),
                    vs.get_support_resistance(vs_id),
                    return_exceptions=True,
                )
                return _ok(
                    symbol=symbol, vsTokenId=vs_id,
                    fund=_safe(fund, dict),
                    fundMarketCapRatio=_safe(ratio, dict),
                    sentiment=_safe(sentiment, dict),
                    supportResistance=_safe(sr, list),
                )
            except Exception as e:
                logger.exception("vs/token-fund error")
                return _err(str(e))

        @self._router.get("/dashboard/vs/fund-snapshot")
        async def fund_snapshot(request: Request, symbol: str = "BTC"):
            try:
                vs_id, err = await _resolve_or_404(symbol)
                if err:
                    return err
                data = await vs.get_fund_snapshot(vs_id)
                return _ok(symbol=symbol, snapshot=data)
            except Exception as e:
                logger.exception("vs/fund-snapshot error")
                return _err(str(e))

        @self._router.get("/dashboard/vs/whale-cost")
        async def whale_cost(request: Request, symbol: str = "BTC"):
            try:
                vs_id, err = await _resolve_or_404(symbol)
                if err:
                    return err
                cost, flow = await asyncio.gather(
                    vs.get_whale_cost(vs_id),
                    vs.get_token_flow(vs_id),
                    return_exceptions=True,
                )
                return _ok(
                    symbol=symbol, vsTokenId=vs_id,
                    whaleCost=_safe(cost, list),
                    tokenFlow=_safe(flow, dict),
                )
            except Exception as e:
                logger.exception("vs/whale-cost error")
                return _err(str(e))

        # ── Sector Fund Rotation ────────────────────────────────────
        @self._router.get("/dashboard/vs/sector-fund")
        async def sector_fund(request: Request, trade_type: int = 1):
            try:
                data = await vs.get_sector_fund_list(trade_type)
                return _ok(tradeType=trade_type, sectors=data)
            except Exception as e:
                logger.exception("vs/sector-fund error")
                return _err(str(e))

        @self._router.get("/dashboard/vs/sector-coins")
        async def sector_coins(request: Request, tag: str = "", trade_type: int = 1):
            if not tag:
                return _err("tag is required", 400)
            try:
                data = await vs.get_sector_coin_trade_list(tag, trade_type)
                return _ok(tag=tag, tradeType=trade_type, coins=data)
            except Exception as e:
                logger.exception("vs/sector-coins error")
                return _err(str(e))

        # ── On-chain Whale ──────────────────────────────────────────
        @self._router.get("/dashboard/vs/whale-onchain")
        async def whale_onchain(request: Request, symbol: str = "BTC", page: int = 1):
            try:
                vs_id, err = await _resolve_or_404(symbol)
                if err:
                    return err
                large, holders = await asyncio.gather(
                    vs.get_large_transactions(vs_id, page=page, page_size=20),
                    vs.get_holder_list(vs_id, page=1, page_size=20),
                    return_exceptions=True,
                )
                return _ok(
                    symbol=symbol, vsTokenId=vs_id,
                    largeTxns=_safe(large, list),
                    holders=_safe(holders, list),
                )
            except Exception as e:
                logger.exception("vs/whale-onchain error")
                return _err(str(e))

        @self._router.get("/dashboard/vs/address-detail")
        async def address_detail(request: Request, symbol: str = "BTC", address: str = ""):
            if not address:
                return _err("address is required", 400)
            try:
                vs_id, err = await _resolve_or_404(symbol)
                if err:
                    return err
                balance, pnl, hold, trade_count = await asyncio.gather(
                    vs.get_address_balance_trend(vs_id, address),
                    vs.get_address_profit_loss_trend(vs_id, address),
                    vs.get_address_hold_trend(vs_id, address),
                    vs.get_address_trade_count_trend(vs_id, address),
                    return_exceptions=True,
                )
                return _ok(
                    symbol=symbol, address=address,
                    balanceTrend=_safe(balance, list),
                    profitLossTrend=_safe(pnl, list),
                    holdTrend=_safe(hold, list),
                    tradeCountTrend=_safe(trade_count, list),
                )
            except Exception as e:
                logger.exception("vs/address-detail error")
                return _err(str(e))

        # ── Market Indicators ───────────────────────────────────────
        @self._router.get("/dashboard/vs/price-indicators")
        async def price_indicators(request: Request, symbol: str = "BTC"):
            try:
                vs_id, err = await _resolve_or_404(symbol)
                if err:
                    return err
                data = await vs.get_price_indicators(vs_id)
                return _ok(symbol=symbol, indicators=data)
            except Exception as e:
                logger.exception("vs/price-indicators error")
                return _err(str(e))

        @self._router.get("/dashboard/vs/market-analyse")
        async def market_analyse(request: Request, page: int = 1, page_size: int = 20):
            try:
                data = await vs.get_ai_market_analyse_history(page=page, page_size=page_size)
                return _ok(page=page, pageSize=page_size, items=data)
            except Exception as e:
                logger.exception("vs/market-analyse error")
                return _err(str(e))

        @self._router.get("/dashboard/vs/full")
        async def full_bundle(request: Request, symbol: str = "BTC"):
            try:
                data = await vs.fetch_full_token_data(symbol)
                return _ok(symbol=symbol, data=data)
            except Exception as e:
                logger.exception("vs/full error")
                return _err(str(e))

        # ── K-line ──────────────────────────────────────────────────
        @self._router.get("/dashboard/vs/kline")
        async def kline(request: Request, symbol: str = "BTC", bucket: str = "1h"):
            try:
                vs_id, err = await _resolve_or_404(symbol)
                if err:
                    return err
                data = await vs.get_kline(vs_id, bucket)
                return _ok(symbol=symbol, bucket=bucket, kline=data)
            except Exception as e:
                logger.exception("vs/kline error")
                return _err(str(e))
