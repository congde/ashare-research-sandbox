# -*- coding: utf-8 -*-
"""
ToolResultCompressor — smart compression for tool return values.

Reduces token consumption from tool results by:
1. Schema aliasing: long field names → short aliases
2. Field filtering: keep only fields relevant to the agent's intent
3. Numeric precision trimming: truncate unnecessary decimal places

Config: conf/default.yaml → tool_compression section

Typical savings: 30-60% fewer tokens per tool result.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ── Field alias mappings ──────────────────────────────────────────────────────
# Common KuCoin API field names that consume significant tokens when repeated.

_FIELD_ALIASES: Dict[str, str] = {
    # Balance / Account
    "availableBalance": "ab",
    "frozenBalance": "fb",
    "totalBalance": "tb",
    "holds": "hd",
    "currency": "c",
    "balance": "b",
    "accountId": "aid",
    "accountName": "an",
    # Order / Trade
    "orderId": "oid",
    "orderType": "ot",
    "tradeId": "tid",
    "clientOid": "coid",
    "createdAt": "cat",
    "updatedAt": "uat",
    "cancelExist": "ce",
    "isIsolated": "ii",
    # Price / Size
    "price": "p",
    "size": "s",
    "dealSize": "ds",
    "dealFunds": "df",
    "remainSize": "rs",
    "remainFunds": "rf",
    "funds": "f",
    "fee": "fe",
    "feeRate": "fr",
    "minFunds": "mf",
    # Symbol / Market
    "symbol": "sym",
    "baseCurrency": "bc",
    "quoteCurrency": "qc",
    "baseIncrement": "bi",
    "quoteIncrement": "qi",
    "baseMinSize": "bms",
    "quoteMinSize": "qms",
    "name": "n",
    "displayName": "dn",
    "description": "desc",
    # Status / Type
    "status": "st",
    "side": "sd",
    "type": "tp",
    "timeInForce": "tif",
    "stopPrice": "sp",
    "stop": "stop",
    "isActive": "ia",
    "isMarginEnabled": "ime",
    # Pagination
    "currentPage": "cp",
    "pageSize": "ps",
    "totalNum": "tn",
    "totalPage": "tp",
    # Timestamps
    "startTime": "stt",
    "endTime": "et",
    "timestamp": "ts",
}

# Reverse mapping for decompression
_REVERSE_ALIASES: Dict[str, str] = {v: k for k, v in _FIELD_ALIASES.items()}

# Intent → required fields mapping for smart field selection
_INTENT_FIELDS: Dict[str, Set[str]] = {
    "price_query": {"p", "sym", "c", "st", "ts"},  # price, symbol, currency, status, timestamp
    "balance_query": {"ab", "fb", "tb", "c"},  # available, frozen, total, currency
    "order_query": {"oid", "sym", "sd", "p", "s", "st", "cat", "tp", "tif"},  # order details
    "trade_query": {"tid", "sym", "sd", "p", "s", "fe", "cat"},  # trade details
    "market_query": {"sym", "p", "s", "bc", "qc", "ia"},  # market/symbol info
    "kline_query": {"ts", "p", "s"},  # time, price, size
}

# Intent detection keywords (Chinese + English)
_INTENT_KEYWORDS: Dict[str, List[str]] = {
    "price_query": ["价格", "price", "行情", "ticker", "多少", "how much", "费率", "fee rate"],
    "balance_query": ["余额", "balance", "账户", "account", "资产", "asset", "持仓", "holding"],
    "order_query": ["订单", "order", "委托", "成交", "trade", "挂单", "open order"],
    "trade_query": ["交易", "trade", "成交记录", "fill", "成交额"],
    "market_query": ["币对", "symbol", "交易对", "市场", "market", "上架"],
    "kline_query": ["K线", "kline", "candle", "走势", "trend", "图表", "chart"],
}


@dataclass
class ToolCompressionConfig:
    """Tool result compression configuration."""

    enabled: bool = True
    # Schema aliasing
    use_field_aliases: bool = True
    # Field filtering
    use_smart_fields: bool = True
    # Numeric precision: max decimal places for prices/amounts
    max_decimal_places: int = 8
    # Max result size after compression (chars). 0 = no limit
    max_compressed_chars: int = 8000
    # Whether to include alias legend in compressed output
    include_alias_legend: bool = False

    @classmethod
    def from_config(cls, config_obj: Any) -> "ToolCompressionConfig":
        """Load from application config object."""
        try:
            raw = getattr(config_obj, "tool_compression", None)
            if raw is None:
                return cls()

            def _get(key: str, default: Any) -> Any:
                if isinstance(raw, dict):
                    return raw.get(key, default)
                return getattr(raw, key, default)

            return cls(
                enabled=bool(_get("enabled", True)),
                use_field_aliases=bool(_get("use_field_aliases", True)),
                use_smart_fields=bool(_get("use_smart_fields", True)),
                max_decimal_places=int(_get("max_decimal_places", 8)),
                max_compressed_chars=int(_get("max_compressed_chars", 8000)),
                include_alias_legend=bool(_get("include_alias_legend", False)),
            )
        except Exception as exc:
            logger.warning("ToolCompressionConfig.from_config failed: %s", exc)
            return cls()


class ToolResultCompressor:
    """
    Compresses tool return values to reduce token consumption.

    Usage::

        compressor = ToolResultCompressor(config)
        compressed = compressor.compress(result, intent="balance_query")
        # ... send to LLM ...
        original = compressor.decompress(compressed)
    """

    def __init__(self, config: Optional[ToolCompressionConfig] = None):
        self._cfg = config or ToolCompressionConfig()
        self._aliases_used: Dict[str, str] = {}  # track which aliases were applied

    def compress(self, result: Any, intent: str = "", tool_name: str = "") -> Any:
        """
        Compress a tool result.

        Parameters
        ----------
        result : Any
            Tool return value (dict, list, or string).
        intent : str
            Detected intent for smart field selection.
        tool_name : str
            Tool name for Prometheus metrics.

        Returns
        -------
        Any
            Compressed result (same type as input).
        """
        if not self._cfg.enabled:
            return result

        try:
            if isinstance(result, str):
                compressed = self._compress_string(result, intent)
            elif isinstance(result, dict):
                compressed = self._compress_dict(result, intent)
            elif isinstance(result, list):
                compressed = self._compress_list(result, intent)
            else:
                return result

            # Prometheus: estimate token savings (rough: 4 chars ≈ 1 token)
            if tool_name:
                try:
                    from vendor_runtime_sdk.libs.agent_metrics import record_tool_compression_savings
                    orig_len = len(json.dumps(result, default=str)) if not isinstance(result, str) else len(result)
                    comp_len = len(json.dumps(compressed, default=str)) if not isinstance(compressed, str) else len(compressed)
                    tokens_saved = max(0, (orig_len - comp_len) // 4)
                    if tokens_saved > 0:
                        record_tool_compression_savings(tool_name, tokens_saved)
                except Exception:
                    pass

            return compressed
        except Exception as exc:
            logger.debug("ToolResultCompressor.compress failed: %s, returning original", exc)
            return result

    def decompress(self, compressed: Any) -> Any:
        """
        Decompress a previously compressed result.

        Restores original field names from aliases.
        """
        try:
            if isinstance(compressed, dict):
                return self._decompress_dict(compressed)
            elif isinstance(compressed, list):
                return [self.decompress(item) for item in compressed]
            return compressed
        except Exception:
            return compressed

    def detect_intent(self, query: str) -> str:
        """
        Detect the user intent from a query string for smart field selection.

        Returns the best-matching intent key, or "" if no match.
        """
        if not query:
            return ""
        q_lower = query.lower()
        best_intent = ""
        best_score = 0
        for intent, keywords in _INTENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in q_lower)
            if score > best_score:
                best_score = score
                best_intent = intent
        return best_intent if best_score > 0 else ""

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compress_dict(self, d: Dict[str, Any], intent: str = "") -> Dict[str, Any]:
        """Compress a single dict by aliasing fields and filtering."""
        result = {}

        # Determine which fields to keep based on intent
        keep_fields = self._get_keep_fields(d, intent)

        for key, value in d.items():
            # Field filtering
            if keep_fields is not None and key not in keep_fields and key not in _FIELD_ALIASES:
                # Keep fields that are in the keep set OR have known aliases
                if key not in keep_fields:
                    continue

            # Alias the key
            new_key = _FIELD_ALIASES.get(key, key) if self._cfg.use_field_aliases else key

            # Recursively compress nested structures
            if isinstance(value, dict):
                new_value = self._compress_dict(value, intent)
            elif isinstance(value, list):
                new_value = self._compress_list(value, intent)
            elif isinstance(value, (int, float)):
                new_value = self._trim_numeric(value)
            else:
                new_value = value

            result[new_key] = new_value

        return result

    def _compress_list(self, lst: List[Any], intent: str = "") -> List[Any]:
        """Compress a list of items."""
        if not lst:
            return lst
        # For lists of dicts, compress each element
        if isinstance(lst[0], dict):
            return [self._compress_dict(item, intent) for item in lst]
        return lst

    def _compress_string(self, s: str, intent: str = "") -> str:
        """Compress a string result (try JSON parse first)."""
        try:
            parsed = json.loads(s)
            compressed = self.compress(parsed, intent)
            result = json.dumps(compressed, ensure_ascii=False, separators=(",", ":"))
            # Apply char limit
            if self._cfg.max_compressed_chars > 0 and len(result) > self._cfg.max_compressed_chars:
                head = result[: self._cfg.max_compressed_chars * 7 // 10]
                tail = result[-self._cfg.max_compressed_chars * 3 // 10 :]
                result = head + '...[truncated]...' + tail
            return result
        except (json.JSONDecodeError, TypeError):
            # Not JSON — just apply char limit
            if self._cfg.max_compressed_chars > 0 and len(s) > self._cfg.max_compressed_chars:
                head = s[: self._cfg.max_compressed_chars * 7 // 10]
                tail = s[-self._cfg.max_compressed_chars * 3 // 10 :]
                return head + "...[truncated]..." + tail
            return s

    def _decompress_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Restore original field names from aliases."""
        result = {}
        for key, value in d.items():
            original_key = _REVERSE_ALIASES.get(key, key)
            if isinstance(value, dict):
                result[original_key] = self._decompress_dict(value)
            elif isinstance(value, list):
                result[original_key] = [
                    self._decompress_dict(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[original_key] = value
        return result

    def _get_keep_fields(self, d: Dict[str, Any], intent: str) -> Optional[Set[str]]:
        """
        Get the set of fields to keep based on intent.

        Returns None if all fields should be kept (no filtering).
        """
        if not self._cfg.use_smart_fields or not intent:
            return None

        alias_fields = _INTENT_FIELDS.get(intent)
        if alias_fields is None:
            return None

        # Map alias fields back to original names
        keep = set()
        for alias in alias_fields:
            original = _REVERSE_ALIASES.get(alias, alias)
            keep.add(original)
            keep.add(alias)  # also keep the alias form in case it's a direct key

        return keep

    @staticmethod
    def _trim_numeric(value: Any) -> Any:
        """Trim numeric precision to avoid unnecessary decimal places."""
        if isinstance(value, float):
            # Remove trailing zeros by converting to string and back
            s = f"{value:.8g}"
            try:
                return float(s)
            except ValueError:
                return value
        return value


# ── Tool Result Cache ────────────────────────────────────────────────────────


@dataclass
class ToolCacheConfig:
    """Tool result cache configuration."""

    enabled: bool = True
    # Default TTL by tool category (seconds)
    market_data_ttl: int = 30      # prices change fast
    account_data_ttl: int = 10     # balance updates frequently
    historical_data_ttl: int = 300  # historical data doesn't change
    default_ttl: int = 30
    # Max cached entries per workspace
    max_entries_per_workspace: int = 1000

    @classmethod
    def from_config(cls, config_obj: Any) -> "ToolCacheConfig":
        """Load from application config object."""
        try:
            raw = getattr(config_obj, "tool_cache", None)
            if raw is None:
                return cls()

            def _get(key: str, default: Any) -> Any:
                if isinstance(raw, dict):
                    return raw.get(key, default)
                return getattr(raw, key, default)

            return cls(
                enabled=bool(_get("enabled", True)),
                market_data_ttl=int(_get("market_data_ttl", 30)),
                account_data_ttl=int(_get("account_data_ttl", 10)),
                historical_data_ttl=int(_get("historical_data_ttl", 300)),
                default_ttl=int(_get("default_ttl", 30)),
                max_entries_per_workspace=int(_get("max_entries_per_workspace", 1000)),
            )
        except Exception:
            return cls()


class ToolResultCache:
    """
    Short-lived cache for tool results.

    Reduces redundant API calls when the same data is requested within
    a short time window (e.g., user asks "BTC价格" then "ETH价格"
    then "BTC价格" again — the second BTC query hits cache).

    Storage: Redis with TTL, keyed by tool_name + params hash.
    Fallback: in-memory dict if Redis is unavailable.

    Follows project convention: Redis is cache-only. Cache misses
    are handled gracefully — the tool API is always the source of truth.
    """

    def __init__(self, config: Optional[ToolCacheConfig] = None):
        self._cfg = config or ToolCacheConfig()
        self._memory_cache: Dict[str, tuple] = {}  # key → (result, expiry_time)

    async def get(
        self, tool_name: str, params: Dict[str, Any], workspace_id: str = ""
    ) -> Optional[Any]:
        """
        Get cached tool result.

        Returns None on cache miss (caller should invoke the actual tool).
        """
        if not self._cfg.enabled:
            return None

        cache_key = self._make_key(tool_name, params, workspace_id)
        ttl = self._get_ttl(tool_name)

        # Try Redis first.
        # PR-E5 — route via BackendClientProvider seam instead of
        # importing web.component directly (engine SDK extraction).
        try:
            from vendor_runtime_sdk.runtime.protocols.backend_provider import get_backend_provider

            redis = await get_backend_provider().get_redis_client()
            if redis:
                import json as _json

                cached = await redis.get(cache_key)
                if cached:
                    return _json.loads(cached)
        except Exception:
            pass

        # Fallback to in-memory cache
        import time

        entry = self._memory_cache.get(cache_key)
        if entry is not None:
            result, expiry = entry
            if time.time() < expiry:
                # Prometheus: tool cache hit
                try:
                    from vendor_runtime_sdk.libs.agent_metrics import record_tool_cache_hit
                    record_tool_cache_hit(tool_name)
                except Exception:
                    pass
                return result
            del self._memory_cache[cache_key]

        return None

    async def set(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: Any,
        workspace_id: str = "",
        ttl: Optional[int] = None,
    ) -> None:
        """Cache a tool result."""
        if not self._cfg.enabled:
            return

        cache_key = self._make_key(tool_name, params, workspace_id)
        if ttl is None:
            ttl = self._get_ttl(tool_name)

        # Try Redis first.
        # PR-E5 — route via BackendClientProvider seam instead of
        # importing web.component directly (engine SDK extraction).
        try:
            from vendor_runtime_sdk.runtime.protocols.backend_provider import get_backend_provider

            redis = await get_backend_provider().get_redis_client()
            if redis:
                import json as _json

                await redis.setex(cache_key, ttl, _json.dumps(result, ensure_ascii=False, default=str))
                return
        except Exception:
            pass

        # Fallback to in-memory cache
        import time

        self._memory_cache[cache_key] = (result, time.time() + ttl)

        # Evict old entries if cache is too large
        if len(self._memory_cache) > self._cfg.max_entries_per_workspace:
            now = time.time()
            expired_keys = [k for k, (_, exp) in self._memory_cache.items() if now >= exp]
            for k in expired_keys:
                del self._memory_cache[k]

    def _get_ttl(self, tool_name: str) -> int:
        """Get TTL for a tool based on its category."""
        name_lower = tool_name.lower()
        if any(kw in name_lower for kw in ("ticker", "price", "orderbook", "market", "kline")):
            return self._cfg.market_data_ttl
        if any(kw in name_lower for kw in ("balance", "account", "position")):
            return self._cfg.account_data_ttl
        if any(kw in name_lower for kw in ("history", "fills", "ledger")):
            return self._cfg.historical_data_ttl
        return self._cfg.default_ttl

    @staticmethod
    def _make_key(tool_name: str, params: Dict[str, Any], workspace_id: str) -> str:
        """Generate a deterministic cache key."""
        import hashlib
        import json as _json

        params_str = _json.dumps(params, sort_keys=True, default=str)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()[:12]
        prefix = f"ws:{workspace_id}:" if workspace_id else ""
        return f"{prefix}tool_cache:{tool_name}:{params_hash}"


# ── Module-level convenience functions ────────────────────────────────────────

_compressor: Optional[ToolResultCompressor] = None
_cache: Optional[ToolResultCache] = None


def get_tool_compressor() -> ToolResultCompressor:
    """Get or create the singleton ToolResultCompressor."""
    global _compressor
    if _compressor is None:
        try:
            from web.config import config as _cfg

            _compressor = ToolResultCompressor(ToolCompressionConfig.from_config(_cfg))
        except Exception:
            _compressor = ToolResultCompressor()
    return _compressor


def get_tool_cache() -> ToolResultCache:
    """Get or create the singleton ToolResultCache."""
    global _cache
    if _cache is None:
        try:
            from web.config import config as _cfg

            _cache = ToolResultCache(ToolCacheConfig.from_config(_cfg))
        except Exception:
            _cache = ToolResultCache()
    return _cache
