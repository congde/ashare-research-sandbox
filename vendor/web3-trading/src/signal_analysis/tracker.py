# -*- coding: utf-8 -*-
"""
Signal Tracker — Phase 1.2

Tracks signal outcomes for feedback loop:
1. Records each generated signal with token/direction/confidence/timestamp
2. Schedules T+1h/4h/24h price checks to compute hit rate
3. Provides historical accuracy stats per dimension for weight adaptation

Storage: MongoDB collection ``signal_tracking`` via dao.mongo.
Falls back to in-memory store if MongoDB is unavailable.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
class SignalDirection(str, Enum):
    BUY = "BUY"
    WEAK_BUY = "WEAK_BUY"
    NEUTRAL = "NEUTRAL"
    WEAK_SELL = "WEAK_SELL"
    SELL = "SELL"


@dataclass
class TrackedSignal:
    """A recorded signal pending outcome verification."""
    signal_id: str
    symbol: str
    pair: str
    signal: str                       # BUY / SELL / NEUTRAL etc.
    score: float                      # -100 ~ 100
    confidence: float                 # 0 ~ 95
    price_at_signal: float            # price when signal was generated
    timestamp: str                    # ISO-8601
    factors: Dict[str, Any] = field(default_factory=dict)
    conflicts: List[Dict] = field(default_factory=list)
    # Outcome fields (filled by check_outcome)
    price_1h: Optional[float] = None
    price_4h: Optional[float] = None
    price_24h: Optional[float] = None
    hit_1h: Optional[bool] = None
    hit_4h: Optional[bool] = None
    hit_24h: Optional[bool] = None
    checked: bool = False


# ---------------------------------------------------------------------------
# In-memory fallback store
# ---------------------------------------------------------------------------
class _MemoryStore:
    """Simple in-memory signal store for environments without MongoDB."""

    def __init__(self, max_size: int = 5000):
        self._signals: Dict[str, Dict] = {}
        self._max_size = max_size

    async def save(self, signal: TrackedSignal) -> None:
        if len(self._signals) >= self._max_size:
            # evict oldest 20%
            keys = sorted(
                self._signals,
                key=lambda k: self._signals[k].get("timestamp", ""),
            )
            for k in keys[: self._max_size // 5]:
                del self._signals[k]
        self._signals[signal.signal_id] = asdict(signal)

    async def get(self, signal_id: str) -> Optional[Dict]:
        return self._signals.get(signal_id)

    async def update(self, signal_id: str, updates: Dict) -> None:
        if signal_id in self._signals:
            self._signals[signal_id].update(updates)

    async def get_unchecked(self, horizon: str, before_ts: str) -> List[Dict]:
        """Get signals not yet checked for a given horizon."""
        results = []
        field_key = f"price_{horizon}"
        for sig in self._signals.values():
            if sig.get(field_key) is not None:
                continue  # already checked
            if sig.get("timestamp", "") < before_ts:
                results.append(sig)
        return results

    async def get_recent(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        signals = list(self._signals.values())
        if symbol:
            signals = [s for s in signals if s.get("symbol") == symbol]
        signals.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
        return signals[:limit]


# ---------------------------------------------------------------------------
# Signal Tracker
# ---------------------------------------------------------------------------
class SignalTracker:
    """
    Tracks signal generation and outcomes.

    Usage:
        tracker = SignalTracker()
        await tracker.record(signal_data)
        # ... later, via cron or scheduled task ...
        await tracker.check_outcomes("1h", current_prices)
        stats = await tracker.get_accuracy_stats("BTC")
    """

    def __init__(self, mongo_collection=None):
        self._mongo = mongo_collection
        self._memory = _MemoryStore()
        self._store = self._mongo if self._mongo else self._memory

    async def record(
        self,
        signal_id: str,
        symbol: str,
        pair: str,
        signal: str,
        score: float,
        confidence: float,
        price_at_signal: float,
        factors: Optional[Dict] = None,
        conflicts: Optional[List[Dict]] = None,
    ) -> TrackedSignal:
        """Record a newly generated signal for tracking."""
        tracked = TrackedSignal(
            signal_id=signal_id,
            symbol=symbol,
            pair=pair,
            signal=signal,
            score=score,
            confidence=confidence,
            price_at_signal=price_at_signal,
            timestamp=datetime.now(timezone.utc).isoformat(),
            factors=factors or {},
            conflicts=conflicts or [],
        )

        if self._mongo:
            await self._mongo.insert_one(asdict(tracked))
        else:
            await self._memory.save(tracked)

        logger.info(
            "Signal tracked: %s %s score=%.1f conf=%.1f price=%.6f",
            symbol, signal, score, confidence, price_at_signal,
        )
        return tracked

    async def check_outcomes(
        self,
        horizon: str,
        current_prices: Dict[str, float],
    ) -> int:
        """
        Check outcomes for signals that haven't been verified yet.

        Args:
            horizon: "1h", "4h", or "24h"
            current_prices: Dict of symbol -> current price

        Returns:
            Number of signals updated.
        """
        # Determine the minimum age for this horizon
        horizon_seconds = {"1h": 3600, "4h": 14400, "24h": 86400}.get(
            horizon, 3600
        )
        cutoff = datetime.fromtimestamp(
            time.time() - horizon_seconds, tz=timezone.utc
        ).isoformat()

        if self._mongo:
            price_field = f"price_{horizon}"
            cursor = self._mongo.find({
                price_field: None,
                "timestamp": {"$lt": cutoff},
            })
            signals = await cursor.to_list(length=500)
        else:
            signals = await self._memory.get_unchecked(horizon, cutoff)

        updated = 0
        for sig in signals:
            symbol = sig.get("symbol", "")
            if symbol not in current_prices:
                continue

            current_price = current_prices[symbol]
            signal_price = sig.get("price_at_signal", 0)
            signal_dir = sig.get("signal", "NEUTRAL")

            if signal_price <= 0:
                continue

            # Compute price change
            pct_change = (current_price - signal_price) / signal_price * 100

            # Determine if signal was correct
            hit = False
            if signal_dir in ("BUY", "WEAK_BUY") and pct_change > 0:
                hit = True
            elif signal_dir in ("SELL", "WEAK_SELL") and pct_change < 0:
                hit = True
            elif signal_dir == "NEUTRAL" and abs(pct_change) < 2:
                hit = True  # neutral was correct if price didn't move much

            updates = {
                f"price_{horizon}": current_price,
                f"hit_{horizon}": hit,
            }

            # Check if all horizons done
            all_checked = all(
                sig.get(f"price_{h}") is not None or h == horizon
                for h in ("1h", "4h", "24h")
            )
            if all_checked:
                updates["checked"] = True

            if self._mongo:
                await self._mongo.update_one(
                    {"signal_id": sig["signal_id"]},
                    {"$set": updates},
                )
            else:
                await self._memory.update(sig["signal_id"], updates)

            updated += 1

        logger.info("Checked %d signal outcomes for horizon=%s", updated, horizon)
        return updated

    async def get_accuracy_stats(
        self,
        symbol: Optional[str] = None,
        horizon: str = "4h",
        limit: int = 200,
    ) -> Dict[str, Any]:
        """
        Get accuracy statistics for signals.

        Returns:
            Dict with overall hit rate and per-dimension accuracy.
        """
        if self._mongo:
            query = {f"hit_{horizon}": {"$ne": None}}
            if symbol:
                query["symbol"] = symbol
            cursor = self._mongo.find(query).sort("timestamp", -1).limit(limit)
            signals = await cursor.to_list(length=limit)
        else:
            signals = await self._memory.get_recent(symbol=symbol, limit=limit)
            signals = [
                s for s in signals if s.get(f"hit_{horizon}") is not None
            ]

        if not signals:
            return {
                "total": 0,
                "hit_rate": 0.0,
                "per_direction": {},
                "per_dimension_accuracy": {},
            }

        hit_field = f"hit_{horizon}"
        total = len(signals)
        hits = sum(1 for s in signals if s.get(hit_field))
        hit_rate = hits / total if total > 0 else 0

        # Per-direction stats
        per_dir: Dict[str, Dict] = {}
        for s in signals:
            d = s.get("signal", "NEUTRAL")
            if d not in per_dir:
                per_dir[d] = {"total": 0, "hits": 0}
            per_dir[d]["total"] += 1
            if s.get(hit_field):
                per_dir[d]["hits"] += 1
        for d in per_dir:
            t = per_dir[d]["total"]
            per_dir[d]["hit_rate"] = per_dir[d]["hits"] / t if t > 0 else 0

        # Per-dimension accuracy (from factor directions)
        dim_stats: Dict[str, Dict] = {}
        for s in signals:
            factors = s.get("factors", {})
            was_hit = s.get(hit_field, False)
            for dim_name in ("technical", "onchain", "news", "positioning"):
                dim_data = factors.get(dim_name, {})
                dim_dir = dim_data.get("direction", "neutral")
                if dim_name not in dim_stats:
                    dim_stats[dim_name] = {"total": 0, "correct": 0}
                dim_stats[dim_name]["total"] += 1

                # Check if this dimension's direction aligned with outcome
                sig_dir = s.get("signal", "NEUTRAL")
                dim_aligned = (
                    (dim_dir in ("bullish", "positive") and sig_dir in ("BUY", "WEAK_BUY"))
                    or (dim_dir in ("bearish", "negative") and sig_dir in ("SELL", "WEAK_SELL"))
                )
                if dim_aligned and was_hit:
                    dim_stats[dim_name]["correct"] += 1
                elif not dim_aligned and not was_hit:
                    dim_stats[dim_name]["correct"] += 1

        for dim in dim_stats:
            t = dim_stats[dim]["total"]
            dim_stats[dim]["accuracy"] = (
                dim_stats[dim]["correct"] / t if t > 0 else 0
            )

        return {
            "total": total,
            "hit_rate": round(hit_rate, 4),
            "per_direction": per_dir,
            "per_dimension_accuracy": dim_stats,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_tracker: Optional[SignalTracker] = None


def get_signal_tracker(mongo_collection=None) -> SignalTracker:
    """Get or create the module-level SignalTracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = SignalTracker(mongo_collection=mongo_collection)
    return _tracker