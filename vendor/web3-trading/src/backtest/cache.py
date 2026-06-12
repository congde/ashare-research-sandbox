# -*- coding: utf-8 -*-
"""
Backtest result caching — hash-based cache to avoid re-running identical backtests.

Analogous to Claude Code's session_store.ts — persists state across invocations
using a content-addressable scheme (hash of inputs → cached result).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional

from backtest.models import BacktestResult

logger = logging.getLogger(__name__)

# In-memory cache (could be replaced with Redis/file-based cache)
_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _make_key(
    symbol: str,
    kline_type: str,
    limit: int,
    strategy_name: str,
    params_hash: str,
    stop_loss: float,
    take_profit: float,
) -> str:
    """Generate a deterministic cache key from backtest parameters."""
    raw = f"{symbol}:{kline_type}:{limit}:{strategy_name}:{params_hash}:{stop_loss}:{take_profit}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _hash_params(params: Dict[str, Any]) -> str:
    """Deterministic hash of strategy parameters."""
    serialized = json.dumps(params, sort_keys=True, default=str)
    return hashlib.md5(serialized.encode()).hexdigest()[:8]


def cache_get(
    symbol: str,
    kline_type: str,
    limit: int,
    strategy_name: str,
    params: Dict[str, Any],
    stop_loss: float,
    take_profit: float,
) -> Optional[BacktestResult]:
    """Look up a cached backtest result. Returns None on cache miss."""
    key = _make_key(symbol, kline_type, limit, strategy_name, _hash_params(params), stop_loss, take_profit)
    entry = _cache.get(key)
    if entry is None:
        return None
    if time.time() - entry["ts"] > _CACHE_TTL_SECONDS:
        del _cache[key]
        return None
    logger.debug("Cache hit: %s", key)
    return entry["result"]


def cache_put(
    symbol: str,
    kline_type: str,
    limit: int,
    strategy_name: str,
    params: Dict[str, Any],
    stop_loss: float,
    take_profit: float,
    result: BacktestResult,
) -> None:
    """Store a backtest result in the cache."""
    key = _make_key(symbol, kline_type, limit, strategy_name, _hash_params(params), stop_loss, take_profit)
    _cache[key] = {"result": result, "ts": time.time()}

    # Evict oldest entries if cache is too large
    if len(_cache) > 100:
        oldest_key = min(_cache, key=lambda k: _cache[k]["ts"])
        del _cache[oldest_key]


def cache_clear() -> int:
    """Clear all cached results. Returns number of entries removed."""
    count = len(_cache)
    _cache.clear()
    return count
