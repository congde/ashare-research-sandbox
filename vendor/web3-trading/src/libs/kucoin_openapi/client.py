# -*- coding: utf-8 -*-
"""KuCoin OpenAPI async client — K-line + derivatives, public-only, no auth.

Design:
  - Single class owns caching and all endpoint methods.
  - Pydantic models (models.py) for response typing.
  - httpx for all HTTP I/O (direct, no wrapper).
  - TTL cache for K-line data (per-instance).
  - All endpoints are public GET — no API key required.
  - Supports Spot (K-line) and Futures (K-line, funding rate, open interest).

Usage::

    from libs.kucoin_openapi import KuCoinClient
    client = KuCoinClient()
    candles = await client.get_kline("BTC-USDT", "15min")
    fr = await client.get_current_funding_rate("XBTUSDTM")
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from pydantic import TypeAdapter

from .enums import FuturesKlineGranularity, KlineGranularity, MarketType
from .exceptions import (
    KuCoinConnectionError,
    KuCoinError,
    KuCoinTimeoutError,
)
from .models import (
    CurrentFundingRate,
    FundingRateItem,
    FuturesKlineCandle,
    KlineCandle,
    OpenInterestStats,
)

logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_SPOT_BASE = "https://api.kucoin.com"
_FUTURES_BASE = "https://api-futures.kucoin.com"


# ---------------------------------------------------------------------------
# TTL cache
# ---------------------------------------------------------------------------
class _TTLCache:
    """Minimal in-memory TTL cache — key → (expires_at, value)."""

    def __init__(self, default_ttl: int = 300) -> None:
        self._store: Dict[str, Tuple[float, Any]] = {}
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self._store[key] = (time.time() + (ttl if ttl is not None else self.default_ttl), value)

    def clear(self) -> None:
        self._store.clear()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class KuCoinClient:
    """Async client for KuCoin public market data (K-line + derivatives).

    Usage:
        client = KuCoinClient()
        candles = await client.get_kline("BTC-USDT", "15min")
        fr = await client.get_current_funding_rate("XBTUSDTM")
    """

    def __init__(
        self,
        *,
        timeout: int = 30,
        cache_ttl: int = 300,
        max_retries: int = 3,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._cache = _TTLCache(default_ttl=cache_ttl)

        self._client = httpx.AsyncClient(
            verify=False,
            timeout=httpx.Timeout(connect=10.0, read=float(timeout), write=float(timeout), pool=5.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Core request
    # ------------------------------------------------------------------
    async def _get(
        self,
        path: str,
        *,
        market: MarketType = MarketType.SPOT,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Low-level GET with retries and error handling."""
        base = _SPOT_BASE if market == MarketType.SPOT else _FUTURES_BASE
        query = ""
        if params:
            sorted_items = sorted(params.items())
            query = "?" + "&".join(f"{k}={v}" for k, v in sorted_items)
        url = f"{base}{path}{query}"
        headers = {"Content-Type": "application/json"}

        for attempt in range(self._max_retries):
            t0 = time.perf_counter()
            try:
                resp = await self._client.get(url, headers=headers)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                resp.raise_for_status()
                data = resp.json()

                if not isinstance(data, dict):
                    raise KuCoinError(message="Unexpected response type", detail={"path": path})

                code = str(data.get("code", ""))
                if code not in ("", "200000"):
                    msg = data.get("msg", "unknown error")
                    logger.warning(
                        "KuCoin path=%s code=%s msg=%s attempt=%d/%d elapsed=%dms",
                        path, code, msg, attempt + 1, self._max_retries, int(elapsed_ms),
                    )
                    raise KuCoinError(message=msg, code=code)

                logger.info(
                    "KuCoin GET path=%s code=200000 attempt=%d/%d elapsed=%dms",
                    path, attempt + 1, self._max_retries, int(elapsed_ms),
                )
                return data

            except httpx.TimeoutException as e:
                if attempt == self._max_retries - 1:
                    raise KuCoinTimeoutError(
                        message=f"Request timed out after {self._max_retries} retries: {url}",
                    ) from e
                wait = 2 ** attempt
                logger.warning(
                    "KuCoin path=%s timeout attempt=%d/%d retry_in=%ds",
                    path, attempt + 1, self._max_retries, wait,
                )
                await asyncio.sleep(wait)

            except httpx.ConnectError as e:
                if attempt == self._max_retries - 1:
                    raise KuCoinConnectionError(
                        message=f"Connection failed after {self._max_retries} retries: {url}",
                    ) from e
                wait = 2 ** attempt
                logger.warning(
                    "KuCoin path=%s connect_error attempt=%d/%d retry_in=%ds",
                    path, attempt + 1, self._max_retries, wait,
                )
                await asyncio.sleep(wait)

            except (KuCoinError,):
                raise
            except Exception as exc:
                logger.warning(
                    "KuCoin path=%s unexpected_error attempt=%d/%d error=%s",
                    path, attempt + 1, self._max_retries, exc,
                    exc_info=True,
                )
                raise KuCoinConnectionError(message=f"Request failed: {exc}") from exc

        raise KuCoinConnectionError(message="Exhausted retries")

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_obj(data: Any, model_type: type) -> Any:
        if not isinstance(data, dict):
            return None
        return model_type.model_validate(data)

    @staticmethod
    def _parse_list(data: Any, model_type: type) -> List[Any]:
        if not isinstance(data, list):
            return []
        adapter = TypeAdapter(List[model_type])
        return adapter.validate_python(data)

    @staticmethod
    def _parse_kline(raw: Any, model_type: type) -> List[Any]:
        """Parse KuCoin K-line flat list of string arrays into candle models.

        Raw format: [[time, open, close, high, low, volume, turnover], ...]
        """
        if not isinstance(raw, list):
            return []
        result: List[Any] = []
        for row in raw:
            if not isinstance(row, list) or len(row) < 7:
                continue
            try:
                result.append(model_type(
                    time=int(row[0]),
                    open=float(row[1]),
                    close=float(row[2]),
                    high=float(row[3]),
                    low=float(row[4]),
                    volume=float(row[5]),
                    turnover=float(row[6]),
                ))
            except (ValueError, TypeError):
                continue
        return result

    # ------------------------------------------------------------------
    # Spot K-line
    # ------------------------------------------------------------------
    async def get_kline(
        self,
        symbol: str,
        granularity: KlineGranularity = KlineGranularity.H1,
        *,
        start_at: Optional[int] = None,
        end_at: Optional[int] = None,
        ttl: int = 60,
    ) -> List[KlineCandle]:
        """获取现货 K线。 GET /api/v1/market/candles"""
        cache_key = f"spot_kline:{symbol}:{granularity.value}:{start_at or 0}:{end_at or 0}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        params: Dict[str, Any] = {"symbol": symbol, "type": granularity.value}
        if start_at is not None:
            params["startAt"] = start_at
        if end_at is not None:
            params["endAt"] = end_at

        resp = await self._get("/api/v1/market/candles", params=params)
        candles = self._parse_kline(resp.get("data"), KlineCandle)
        candles.reverse()
        self._cache.set(cache_key, candles, ttl=ttl)
        return candles

    async def get_multi_tf_kline(
        self,
        symbol: str,
        granularities: Optional[List[KlineGranularity]] = None,
        *,
        ttl: int = 60,
    ) -> Dict[str, List[KlineCandle]]:
        """并发拉取多周期现货 K线。默认 [15min, 1H, 4H, 1D]。"""
        if granularities is None:
            granularities = [
                KlineGranularity.M15,
                KlineGranularity.H1,
                KlineGranularity.H4,
                KlineGranularity.D1,
            ]

        async def _fetch_one(g: KlineGranularity) -> Tuple[str, List[KlineCandle]]:
            candles = await self.get_kline(symbol, g, ttl=ttl)
            return g.value, candles

        results = await asyncio.gather(*(_fetch_one(g) for g in granularities))
        return dict(results)

    # ------------------------------------------------------------------
    # Futures K-line
    # ------------------------------------------------------------------
    async def get_futures_kline(
        self,
        symbol: str,
        granularity: FuturesKlineGranularity = FuturesKlineGranularity.H1,
        *,
        start_at: Optional[int] = None,
        end_at: Optional[int] = None,
        ttl: int = 60,
    ) -> List[FuturesKlineCandle]:
        """获取合约 K线。 GET /api/v1/kline/query"""
        cache_key = f"futures_kline:{symbol}:{granularity.value}:{start_at or 0}:{end_at or 0}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        params: Dict[str, Any] = {"symbol": symbol, "granularity": granularity.value}
        if start_at is not None:
            params["from"] = start_at
        if end_at is not None:
            params["to"] = end_at

        resp = await self._get("/api/v1/kline/query", market=MarketType.FUTURES, params=params)
        candles = self._parse_kline(resp.get("data"), FuturesKlineCandle)
        candles.reverse()
        self._cache.set(cache_key, candles, ttl=ttl)
        return candles

    async def get_futures_multi_tf_kline(
        self,
        symbol: str,
        granularities: Optional[List[FuturesKlineGranularity]] = None,
        *,
        ttl: int = 60,
    ) -> Dict[str, List[FuturesKlineCandle]]:
        """并发拉取多周期合约 K线。"""
        if granularities is None:
            granularities = [
                FuturesKlineGranularity.M15,
                FuturesKlineGranularity.H1,
                FuturesKlineGranularity.H4,
                FuturesKlineGranularity.D1,
            ]

        async def _fetch_one(g: FuturesKlineGranularity) -> Tuple[str, List[FuturesKlineCandle]]:
            candles = await self.get_futures_kline(symbol, g, ttl=ttl)
            return g.value, candles

        results = await asyncio.gather(*(_fetch_one(g) for g in granularities))
        return dict(results)

    # ------------------------------------------------------------------
    # Futures — Funding rate
    # ------------------------------------------------------------------
    async def get_current_funding_rate(self, symbol: str) -> Optional[CurrentFundingRate]:
        """获取当前资金费率。 GET /api/v1/funding-rate/{symbol}/current"""
        resp = await self._get(
            f"/api/v1/funding-rate/{symbol}/current",
            market=MarketType.FUTURES,
        )
        return self._parse_obj(resp.get("data"), CurrentFundingRate)

    async def get_funding_rate_history(
        self,
        symbol: str,
        *,
        start_at: Optional[int] = None,
        end_at: Optional[int] = None,
    ) -> List[FundingRateItem]:
        """获取资金费率历史。 GET /api/v1/contract/funding-rates

        ``from`` / ``to`` 为合约 API 必填参数，不传时默认取最近 7 天。
        """
        now_ms = int(time.time() * 1000)
        params: Dict[str, Any] = {
            "symbol": symbol,
            "from": start_at or (now_ms - 7 * 86_400_000),
            "to": end_at or now_ms,
        }

        resp = await self._get(
            "/api/v1/contract/funding-rates",
            market=MarketType.FUTURES,
            params=params,
        )
        items = self._parse_list(resp.get("data"), FundingRateItem)
        items.reverse()
        return items

    # ------------------------------------------------------------------
    # Futures — Open Interest
    # ------------------------------------------------------------------
    async def get_open_interest(self, symbol: str) -> Optional[OpenInterestStats]:
        """获取实时持仓量。 GET /api/v1/interest/query"""
        resp = await self._get(
            "/api/v1/interest/query",
            market=MarketType.FUTURES,
            params={"symbol": symbol},
        )
        data = resp.get("data")
        if not isinstance(data, dict):
            return None
        return OpenInterestStats(
            symbol=symbol,
            open_interest=float(data.get("value", 0)),
            timestamp=int(time.time() * 1000),
        )
