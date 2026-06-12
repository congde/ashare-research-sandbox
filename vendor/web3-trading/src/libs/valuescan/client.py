# -*- coding: utf-8 -*-
"""ValueScan async client — class-based, typed, senior-architect style.

Design:
  - Single class owns config, signing, caching, and all endpoint methods.
  - Pydantic models (models.py) for request/response typing.
  - libs.http.post for all HTTP I/O.
  - TTL cache for token/coin-key resolution (per-instance, injectable).
  - Boundary: raw dict → Pydantic model conversion happens inside each method.
"""

from __future__ import annotations

import os
import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from pydantic import TypeAdapter

from .exceptions import (
    ValueScanAuthError,
    ValueScanConnectionError,
    ValueScanError,
    ValueScanTimeoutError,
)
from .models import (
    BalanceTrendItem,
    ChanceCoinItem,
    CoinTradeCostItem,
    CoinTradeFlowData,
    DenseAreaItem,
    FundData,
    FundMarketCapRatioData,
    FundsCoinItem,
    HoldPageItem,
    KlineItem,
    LargeTransactionItem,
    PriceMarketItem,
    ProfitLossTrendItem,
    RiskCoinItem,
    SectorCoinTradeItem,
    SectorFundItem,
    SocialSentimentData,
    TokenDetail,
    TokenInfo,
    TradeCountTrendItem,
)

logger = logging.getLogger(__name__)

# httpx logs every request at INFO level — too noisy for production
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_MS_PER_DAY: int = 86_400_000

# API root only — endpoint paths in this client include ``open/v1/``.
_DEFAULT_API_ROOT = "https://api.valuescan.io/api"
_OPEN_V1_SUFFIX = "/open/v1"


def normalize_valuescan_api_root(base_url: str) -> str:
    """Normalize VS_OPEN_API_BASE_URL for ValueScanClient.

    Accepts either API root (``.../api``) or full open/v1 base (``.../api/open/v1``),
    as used by ``valuescan_service.vs_post``.
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return _DEFAULT_API_ROOT
    if base.endswith(_OPEN_V1_SUFFIX):
        base = base[: -len(_OPEN_V1_SUFFIX)].rstrip("/")
    return base or _DEFAULT_API_ROOT


# ---------------------------------------------------------------------------
# TTL cache (per-instance, injectable for testing)
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
class ValueScanClient:
    """Async client for the full ValueScan Open API surface.

    Usage:
        client = ValueScanClient.from_env()
        token = await client.search_token("BTC")
        flow = await client.get_token_flow(token.id)
    """

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        base_url: str,
        timeout: int = 30,
        cache_ttl: int = 300,
        max_retries: int = 3,
        proxies: Optional[dict[str, str]] = None
    ) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._base_url = normalize_valuescan_api_root(base_url)
        self._timeout = timeout
        self._max_retries = max_retries
        self._cache = _TTLCache(default_ttl=cache_ttl)

        proxies = proxies or {}
        mapped_proxies = {
            "http://": proxies.get("http", os.getenv("VALUESCAN_HTTP_PROXY")),
            "https://": proxies.get("https", os.getenv("VALUESCAN_HTTPS_PROXY")),
        }
        mapped_proxies = {key: value for key, value in mapped_proxies.items() if value}
        logger.info(f"Initializing ValueScanClient with proxies: {mapped_proxies}")
        proxy_mounts = (
            {scheme: httpx.AsyncHTTPTransport(proxy=proxy) for scheme, proxy in mapped_proxies.items()}
            if mapped_proxies
            else None
        )

        self._client = httpx.AsyncClient(
            verify=False,
            timeout=httpx.Timeout(connect=10.0, read=float(timeout), write=float(timeout), pool=5.0),
            mounts=proxy_mounts
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls, prefix: str = "VS_OPEN_") -> "ValueScanClient":
        import os

        return cls(
            api_key=os.environ.get(f"{prefix}API_KEY", ""),
            secret_key=os.environ.get(f"{prefix}SECRET_KEY", ""),
            base_url=os.environ.get(f"{prefix}API_BASE_URL", _DEFAULT_API_ROOT),
            timeout=20,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _now_ms(self) -> str:
        return str(int(time.time() * 1000))

    def _sign(self, timestamp: str, raw_body: str) -> str:
        sign_str = timestamp + raw_body
        return hmac.new(
            self._secret_key.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def _post(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Low-level POST with signing, error handling, JSON parsing, and retries."""
        body_dict = body or {}
        raw_body = json.dumps(body_dict, separators=(",", ":"))
        url = f"{self._base_url}/{path.lstrip('/')}"

        for attempt in range(self._max_retries):
            ts = self._now_ms()
            signature = self._sign(ts, raw_body)
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "X-API-KEY": self._api_key,
                "X-TIMESTAMP": ts,
                "X-SIGN": signature,
            }
            t0 = time.perf_counter()
            try:
                resp = await self._client.post(url, content=raw_body, headers=headers)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                resp.raise_for_status()
                data = resp.json()

                if not isinstance(data, dict):
                    raise ValueScanError(
                        message="Unexpected response type", detail={"path": path}
                    )

                code = data.get("code")
                if code != 200:
                    msg = data.get("message", "unknown error")
                    logger.warning(
                        "ValueScan POST path=%s code=%s msg=%s attempt=%d/%d elapsed=%dms",
                        path, code, msg, attempt + 1, self._max_retries, int(elapsed_ms),
                    )
                    if code in (401, 403):
                        raise ValueScanAuthError(
                            message=msg, code=code,
                        ) from None
                    if code == 60001 and attempt < self._max_retries - 1:
                        wait = 2 ** attempt
                        logger.warning(
                            "ValueScan rate limit on %s — retry in %ds",
                            path,
                            wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    raise ValueScanError(
                        message=msg, code=code,
                    )

                logger.info(
                    "ValueScan POST path=%s code=200 attempt=%d/%d elapsed=%dms",
                    path, attempt + 1, self._max_retries, int(elapsed_ms),
                )
                return data

            except httpx.TimeoutException as e:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                if attempt == self._max_retries - 1:
                    logger.error(
                        "ValueScan POST path=%s timeout_exhausted retries=%d last_elapsed=%dms url=%s",
                        path, self._max_retries, int(elapsed_ms), url,
                    )
                    raise ValueScanTimeoutError(
                        message=f"Request timed out after {self._max_retries} retries: {url}",
                    ) from e
                wait = 2 ** attempt
                logger.warning(
                    "ValueScan POST path=%s timeout attempt=%d/%d elapsed=%dms retry_in=%ds url=%s",
                    path, attempt + 1, self._max_retries, int(elapsed_ms), wait, url,
                )
                await asyncio.sleep(wait)

            except httpx.ConnectError as e:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                if attempt == self._max_retries - 1:
                    logger.error(
                        "ValueScan POST path=%s connect_exhausted retries=%d last_elapsed=%dms url=%s",
                        path, self._max_retries, int(elapsed_ms), url,
                    )
                    raise ValueScanConnectionError(
                        message=f"Connection failed after {self._max_retries} retries: {url}",
                    ) from e
                wait = 2 ** attempt
                logger.warning(
                    "ValueScan POST path=%s connect_error attempt=%d/%d elapsed=%dms retry_in=%ds url=%s",
                    path, attempt + 1, self._max_retries, int(elapsed_ms), wait, url,
                )
                await asyncio.sleep(wait)

            except (ValueScanError, ValueScanAuthError):
                raise  # re-raise our own errors
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                logger.warning(
                    "ValueScan POST path=%s unexpected_error attempt=%d/%d elapsed=%dms error=%s url=%s",
                    path, attempt + 1, self._max_retries, int(elapsed_ms), exc, url,
                    exc_info=True,
                )
                raise ValueScanConnectionError(
                    message=f"Request failed: {exc}", code=None,
                ) from exc

        # Should not reach here, but just in case
        raise ValueScanConnectionError(message="Exhausted retries")  # noqa: B904

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()

    def _parse_list(self, data: Any, item_type: type) -> List[Any]:
        """Parse a response whose data field is a list of item_type."""
        if not isinstance(data, list):
            return []
        adapter = TypeAdapter(List[item_type])
        return adapter.validate_python(data)

    def _parse_obj(self, data: Any, obj_type: type) -> Any:
        if not isinstance(data, dict):
            return None
        return obj_type.model_validate(data)

    # ------------------------------------------------------------------
    # Token resolution (cached)
    # ------------------------------------------------------------------
    async def search_token(self, symbol: str) -> List[TokenInfo]:
        key = f"token:{symbol.strip().upper()}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        resp = await self._post("/open/v1/vs-token/list", {"search": symbol.strip()})
        items = self._parse_list(resp.get("data"), TokenInfo)
        self._cache.set(key, items, ttl=600)
        return items

    async def get_token_by_symbol(self, symbol: str) -> Optional[TokenInfo]:
        """Return best-match TokenInfo for a symbol string."""
        tokens = await self.search_token(symbol)
        if not tokens:
            return None
        sym = symbol.strip().upper()
        return next((t for t in tokens if t.symbol.upper() == sym), tokens[0])

    async def get_vs_token_id(self, symbol: str) -> Optional[str]:
        token = await self.get_token_by_symbol(symbol)
        return token.id if token else None

    async def get_token_detail(self, vs_token_id: str) -> Optional[TokenDetail]:
        key = f"detail:{vs_token_id}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        resp = await self._post("/open/v1/vs-token/detail", {"vsTokenId": vs_token_id})
        detail = self._parse_obj(resp.get("data"), TokenDetail)
        if detail:
            self._cache.set(key, detail, ttl=600)
        return detail

    async def get_coin_key(self, vs_token_id: str) -> str:
        key = f"coinkey:{vs_token_id}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        detail = await self.get_token_detail(vs_token_id)
        if not detail or not detail.chain_addresses:
            return ""
        coin_key = detail.chain_addresses[0].coin_key
        if coin_key:
            self._cache.set(key, coin_key, ttl=3600)
        return coin_key

    async def resolve_symbol(self, symbol: str) -> Tuple[Optional[str], str]:
        """Resolve symbol → (vsTokenId, coinKey)."""
        token = await self.get_token_by_symbol(symbol)
        if not token:
            return None, ""
        return token.id, await self.get_coin_key(token.id)

    # ------------------------------------------------------------------
    # Exchange fund monitoring
    # ------------------------------------------------------------------
    async def get_token_flow(self, vs_token_id: str) -> Optional[CoinTradeFlowData]:
        resp = await self._post("/open/v1/trade/getCoinTradeFlow", {"vsTokenId": vs_token_id})
        return self._parse_obj(resp.get("data"), CoinTradeFlowData)

    async def get_realtime_fund(self, vs_token_id: str) -> Optional[FundData]:
        resp = await self._post("/open/v1/trade/getCoinTrade", {"vsTokenId": vs_token_id})
        return self._parse_obj(resp.get("data"), FundData)

    async def get_fund_snapshot(
        self, vs_token_id: str, date_ms: Optional[int] = None
    ) -> Optional[FundData]:
        now = int(time.time() * 1000)
        resp = await self._post("/open/v1/trade/getCoinTradeSnapshot", {
            "vsTokenId": vs_token_id,
            "date": date_ms or now,
        })
        return self._parse_obj(resp.get("data"), FundData)

    async def get_fund_market_cap_ratio(self, vs_token_id: str) -> Optional[FundMarketCapRatioData]:
        resp = await self._post(
            "/open/v1/trade/getCoinTradeInflowMarketCapRatio", {"vsTokenId": vs_token_id}
        )
        return self._parse_obj(resp.get("data"), FundMarketCapRatioData)

    async def get_sector_fund_list(self, trade_type: int = 1) -> List[SectorFundItem]:
        resp = await self._post("/open/v1/trade/categories/getTradeList", {"tradeType": trade_type})
        return self._parse_list(resp.get("data"), SectorFundItem)

    async def get_sector_coin_trade_list(
        self, tag: str, trade_type: int = 1
    ) -> List[SectorCoinTradeItem]:
        resp = await self._post(
            "/open/v1/trade/categories/CoinTradeList", {"tag": tag, "tradeType": trade_type}
        )
        return self._parse_list(resp.get("data"), SectorCoinTradeItem)

    async def get_kline(
        self,
        vs_token_id: str,
        bucket_type: str = "1h",
        days: int = 7,
    ) -> List[KlineItem]:
        now = int(time.time() * 1000)
        resp = await self._post("/open/v1/trade/kline/getTradeKLineList", {
            "vsTokenId": vs_token_id,
            "bucketType": bucket_type,
            "startTime": now - days * _MS_PER_DAY,
            "endTime": now,
        })
        return self._parse_list(resp.get("data"), KlineItem)

    # ------------------------------------------------------------------
    # On-chain data — whale cost, flow
    # ------------------------------------------------------------------
    async def get_whale_cost(
        self, vs_token_id: str, days: int = 30
    ) -> List[CoinTradeCostItem]:
        now = int(time.time() * 1000)
        resp = await self._post("/open/v1/trade/getCoinTradeCost", {
            "vsTokenId": vs_token_id,
            "startTime": now - days * _MS_PER_DAY,
            "endTime": now,
        })
        return self._parse_list(resp.get("data"), CoinTradeCostItem)

    # ------------------------------------------------------------------
    # On-chain whale — requires coinKey
    # ------------------------------------------------------------------
    async def get_large_transactions(
        self,
        vs_token_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> List[LargeTransactionItem]:
        coin_key = await self.get_coin_key(vs_token_id)
        if not coin_key:
            return []
        resp = await self._post("/open/v1/chain/trade/large", {
            "vsTokenId": vs_token_id,
            "coinKey": coin_key,
            "page": page,
            "pageSize": page_size,
        })
        return self._parse_list(resp.get("data"), LargeTransactionItem)

    async def get_holder_list(
        self,
        vs_token_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> List[HoldPageItem]:
        coin_key = await self.get_coin_key(vs_token_id)
        if not coin_key:
            return []
        resp = await self._post("/open/v1/chain/trade/token/holdPage", {
            "vsTokenId": vs_token_id,
            "coinKey": coin_key,
            "page": page,
            "pageSize": page_size,
        })
        return self._parse_list(resp.get("data"), HoldPageItem)

    async def _address_trend(
        self,
        vs_token_id: str,
        address: str,
        endpoint: str,
        days: int = 30,
    ) -> List[Any]:
        coin_key = await self.get_coin_key(vs_token_id)
        if not coin_key:
            return []
        now = int(time.time() * 1000)
        # Map endpoint → model type
        model_map = {
            "/open/v1/chain/trade/token/balanceTrend": BalanceTrendItem,
            "/open/v1/chain/trade/token/profitLossTrend": ProfitLossTrendItem,
            "/open/v1/chain/trade/token/tradeCountTrend": TradeCountTrendItem,
            "/open/v1/chain/trade/token/holdTrend": BalanceTrendItem,  # reuse
        }
        model_type = model_map.get(endpoint, Dict[str, Any])
        resp = await self._post(endpoint, {
            "vsTokenId": vs_token_id,
            "coinKey": coin_key,
            "address": address,
            "startTime": now - days * _MS_PER_DAY,
            "endTime": now,
        })
        if model_type is Dict:
            return resp.get("data") or []
        return self._parse_list(resp.get("data"), model_type)

    async def get_address_balance_trend(
        self, vs_token_id: str, address: str, days: int = 30
    ) -> List[BalanceTrendItem]:
        return await self._address_trend(
            vs_token_id, address, "/open/v1/chain/trade/token/balanceTrend", days
        )

    async def get_address_profit_loss_trend(
        self, vs_token_id: str, address: str, days: int = 30
    ) -> List[ProfitLossTrendItem]:
        return await self._address_trend(
            vs_token_id, address, "/open/v1/chain/trade/token/profitLossTrend", days
        )

    async def get_address_trade_count_trend(
        self, vs_token_id: str, address: str, days: int = 30
    ) -> List[TradeCountTrendItem]:
        return await self._address_trend(
            vs_token_id, address, "/open/v1/chain/trade/token/tradeCountTrend", days
        )

    async def get_address_hold_trend(
        self, vs_token_id: str, address: str, days: int = 30
    ) -> List[BalanceTrendItem]:
        return await self._address_trend(
            vs_token_id, address, "/open/v1/chain/trade/token/holdTrend", days
        )

    # ------------------------------------------------------------------
    # Market indicators
    # ------------------------------------------------------------------
    async def get_price_indicators(
        self, vs_token_id: str, days: int = 30
    ) -> List[PriceMarketItem]:
        now = int(time.time() * 1000)
        resp = await self._post("/open/v1/indicator/getPriceMarketList", {
            "vsTokenId": vs_token_id,
            "startTime": now - days * _MS_PER_DAY,
            "endTime": now,
        })
        return self._parse_list(resp.get("data"), PriceMarketItem)

    async def get_support_resistance(
        self, vs_token_id: str, days: int = 7
    ) -> List[DenseAreaItem]:
        now = int(time.time() * 1000)
        resp = await self._post("/open/v1/indicator/getDenseAreaList", {
            "vsTokenId": vs_token_id,
            "startTime": now - days * _MS_PER_DAY,
            "endTime": now,
        })
        return self._parse_list(resp.get("data"), DenseAreaItem)

    async def get_social_sentiment(
        self, vs_token_id: str
    ) -> Optional[SocialSentimentData]:
        resp = await self._post(
            "/open/v1/social-sentiment/getCoinSocialSentiment", {"vsTokenId": vs_token_id}
        )
        return self._parse_obj(resp.get("data"), SocialSentimentData)

    # ------------------------------------------------------------------
    # AI smart picks & signals
    # ------------------------------------------------------------------
    async def get_chance_coin_list(self) -> List[ChanceCoinItem]:
        resp = await self._post("/open/v1/ai/getChanceCoinList", {})
        return self._parse_list(resp.get("data"), ChanceCoinItem)

    async def get_risk_coin_list(self) -> List[RiskCoinItem]:
        resp = await self._post("/open/v1/ai/getRiskCoinList", {})
        return self._parse_list(resp.get("data"), RiskCoinItem)

    async def get_funds_coin_list(self) -> List[FundsCoinItem]:
        resp = await self._post("/open/v1/ai/getFundsCoinList", {})
        return self._parse_list(resp.get("data"), FundsCoinItem)

    _AI_MSG_PATHS = {
        "chance": "/open/v1/ai/getChanceCoinMessageList",
        "risk": "/open/v1/ai/getRiskCoinMessageList",
        "funds": "/open/v1/ai/getFundsCoinMessageList",
    }

    async def get_ai_messages(
        self, vs_token_id: str, msg_type: str = "chance"
    ) -> List[Dict[str, Any]]:
        path = self._AI_MSG_PATHS.get(msg_type, self._AI_MSG_PATHS["chance"])
        resp = await self._post(path, {"vsTokenId": vs_token_id})
        return resp.get("data") or []

    async def get_ai_market_analyse_history(
        self,
        page: int = 1,
        page_size: int = 20,
        begin_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        body: Dict[str, Any] = {"page": page, "pageSize": min(page_size, 100)}
        if begin_time:
            body["beginTime"] = str(begin_time)
        if end_time:
            body["endTime"] = str(end_time)
        resp = await self._post("/open/v1/ai/getAiTokenAnalyseResultList", body)
        data = resp.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("list") or data.get("records") or []
        return []
