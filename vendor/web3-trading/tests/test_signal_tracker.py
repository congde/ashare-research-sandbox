# -*- coding: utf-8 -*-
"""
Tests for src/signal/tracker.py

Tests cover:
1. Recording signals
2. Memory store CRUD operations
3. Outcome checking (hit/miss logic)
4. Accuracy statistics computation
5. Eviction when store is full
6. Edge cases: zero price, neutral signals
"""

import sys
import os
import asyncio
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from signal_analysis.tracker import SignalTracker, TrackedSignal, _MemoryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def run(coro):
    """Run async coroutine synchronously."""
    return asyncio.run(coro)


@pytest.fixture
def tracker():
    return SignalTracker(mongo_collection=None)


@pytest.fixture
def memory_store():
    return _MemoryStore(max_size=10)


# ---------------------------------------------------------------------------
# _MemoryStore tests
# ---------------------------------------------------------------------------
class TestMemoryStore:
    def test_save_and_get(self, memory_store):
        sig = TrackedSignal(
            signal_id="test-1", symbol="BTC", pair="BTC-USDT",
            signal="BUY", score=50.0, confidence=70.0,
            price_at_signal=50000.0, timestamp="2025-04-25T10:00:00Z",
        )
        run(memory_store.save(sig))
        result = run(memory_store.get("test-1"))
        assert result is not None
        assert result["symbol"] == "BTC"
        assert result["signal"] == "BUY"
        assert result["score"] == 50.0

    def test_update(self, memory_store):
        sig = TrackedSignal(
            signal_id="test-2", symbol="ETH", pair="ETH-USDT",
            signal="SELL", score=-40.0, confidence=60.0,
            price_at_signal=3000.0, timestamp="2025-04-25T10:00:00Z",
        )
        run(memory_store.save(sig))
        run(memory_store.update("test-2", {"price_1h": 2950.0, "hit_1h": True}))
        result = run(memory_store.get("test-2"))
        assert result["price_1h"] == 2950.0
        assert result["hit_1h"] is True

    def test_get_nonexistent(self, memory_store):
        result = run(memory_store.get("nonexistent"))
        assert result is None

    def test_eviction_on_overflow(self):
        store = _MemoryStore(max_size=5)
        for i in range(6):
            sig = TrackedSignal(
                signal_id=f"sig-{i}", symbol="BTC", pair="BTC-USDT",
                signal="BUY", score=50.0, confidence=70.0,
                price_at_signal=50000.0,
                timestamp=f"2025-04-25T{10+i:02d}:00:00Z",
            )
            run(store.save(sig))
        # Should have evicted oldest 20% (1 item) when hitting 5
        assert len(store._signals) <= 5

    def test_get_recent(self, memory_store):
        for i in range(5):
            sig = TrackedSignal(
                signal_id=f"recent-{i}", symbol="BTC", pair="BTC-USDT",
                signal="BUY", score=50.0, confidence=70.0,
                price_at_signal=50000.0,
                timestamp=f"2025-04-25T{10+i:02d}:00:00Z",
            )
            run(memory_store.save(sig))
        results = run(memory_store.get_recent(limit=3))
        assert len(results) == 3
        # Should be sorted by timestamp descending
        assert results[0]["timestamp"] >= results[1]["timestamp"]

    def test_get_recent_with_symbol_filter(self, memory_store):
        for sym in ["BTC", "ETH", "BTC"]:
            sig = TrackedSignal(
                signal_id=f"filter-{sym}-{id(sym)}", symbol=sym, pair=f"{sym}-USDT",
                signal="BUY", score=50.0, confidence=70.0,
                price_at_signal=50000.0,
                timestamp="2025-04-25T10:00:00Z",
            )
            run(memory_store.save(sig))
        results = run(memory_store.get_recent(symbol="BTC"))
        assert all(r["symbol"] == "BTC" for r in results)

    def test_get_unchecked(self, memory_store):
        sig = TrackedSignal(
            signal_id="unchecked-1", symbol="BTC", pair="BTC-USDT",
            signal="BUY", score=50.0, confidence=70.0,
            price_at_signal=50000.0,
            timestamp="2025-01-01T00:00:00Z",  # old enough
        )
        run(memory_store.save(sig))
        results = run(memory_store.get_unchecked("1h", "2025-04-25T00:00:00Z"))
        assert len(results) == 1


# ---------------------------------------------------------------------------
# SignalTracker.record tests
# ---------------------------------------------------------------------------
class TestSignalTrackerRecord:
    def test_record_signal(self, tracker):
        result = run(tracker.record(
            signal_id="rec-1", symbol="BTC", pair="BTC-USDT",
            signal="BUY", score=60.0, confidence=75.0,
            price_at_signal=50000.0,
        ))
        assert isinstance(result, TrackedSignal)
        assert result.signal_id == "rec-1"
        assert result.symbol == "BTC"
        assert result.timestamp  # should be set

    def test_record_with_factors(self, tracker):
        factors = {"technical": {"direction": "bullish", "score": 50}}
        result = run(tracker.record(
            signal_id="rec-2", symbol="ETH", pair="ETH-USDT",
            signal="SELL", score=-40.0, confidence=60.0,
            price_at_signal=3000.0,
            factors=factors,
        ))
        assert result.factors == factors


# ---------------------------------------------------------------------------
# SignalTracker.check_outcomes tests
# ---------------------------------------------------------------------------
class TestSignalTrackerOutcomes:
    def test_buy_signal_hit(self, tracker):
        # Record a BUY signal
        run(tracker.record(
            signal_id="outcome-1", symbol="BTC", pair="BTC-USDT",
            signal="BUY", score=60.0, confidence=75.0,
            price_at_signal=50000.0,
        ))
        # Manually backdate the timestamp
        tracker._memory._signals["outcome-1"]["timestamp"] = "2020-01-01T00:00:00Z"

        # Check with higher price → should be hit
        updated = run(tracker.check_outcomes("1h", {"BTC": 51000.0}))
        assert updated == 1
        sig = run(tracker._memory.get("outcome-1"))
        assert sig["hit_1h"] is True
        assert sig["price_1h"] == 51000.0

    def test_buy_signal_miss(self, tracker):
        run(tracker.record(
            signal_id="outcome-2", symbol="BTC", pair="BTC-USDT",
            signal="BUY", score=60.0, confidence=75.0,
            price_at_signal=50000.0,
        ))
        tracker._memory._signals["outcome-2"]["timestamp"] = "2020-01-01T00:00:00Z"

        # Check with lower price → should be miss
        updated = run(tracker.check_outcomes("1h", {"BTC": 49000.0}))
        assert updated == 1
        sig = run(tracker._memory.get("outcome-2"))
        assert sig["hit_1h"] is False

    def test_sell_signal_hit(self, tracker):
        run(tracker.record(
            signal_id="outcome-3", symbol="ETH", pair="ETH-USDT",
            signal="SELL", score=-50.0, confidence=65.0,
            price_at_signal=3000.0,
        ))
        tracker._memory._signals["outcome-3"]["timestamp"] = "2020-01-01T00:00:00Z"

        updated = run(tracker.check_outcomes("4h", {"ETH": 2800.0}))
        assert updated == 1
        sig = run(tracker._memory.get("outcome-3"))
        assert sig["hit_4h"] is True

    def test_neutral_signal_hit_when_stable(self, tracker):
        run(tracker.record(
            signal_id="outcome-4", symbol="BTC", pair="BTC-USDT",
            signal="NEUTRAL", score=0.0, confidence=50.0,
            price_at_signal=50000.0,
        ))
        tracker._memory._signals["outcome-4"]["timestamp"] = "2020-01-01T00:00:00Z"

        # Price barely moved → neutral was correct
        updated = run(tracker.check_outcomes("1h", {"BTC": 50500.0}))
        assert updated == 1
        sig = run(tracker._memory.get("outcome-4"))
        assert sig["hit_1h"] is True  # <2% change

    def test_skips_unknown_symbol(self, tracker):
        run(tracker.record(
            signal_id="outcome-5", symbol="XYZ", pair="XYZ-USDT",
            signal="BUY", score=60.0, confidence=75.0,
            price_at_signal=1.0,
        ))
        tracker._memory._signals["outcome-5"]["timestamp"] = "2020-01-01T00:00:00Z"

        updated = run(tracker.check_outcomes("1h", {"BTC": 50000.0}))
        assert updated == 0  # XYZ not in current_prices

    def test_skips_zero_price(self, tracker):
        run(tracker.record(
            signal_id="outcome-6", symbol="BTC", pair="BTC-USDT",
            signal="BUY", score=60.0, confidence=75.0,
            price_at_signal=0.0,
        ))
        tracker._memory._signals["outcome-6"]["timestamp"] = "2020-01-01T00:00:00Z"

        updated = run(tracker.check_outcomes("1h", {"BTC": 50000.0}))
        assert updated == 0


# ---------------------------------------------------------------------------
# SignalTracker.get_accuracy_stats tests
# ---------------------------------------------------------------------------
class TestSignalTrackerStats:
    def test_empty_stats(self, tracker):
        stats = run(tracker.get_accuracy_stats())
        assert stats["total"] == 0
        assert stats["hit_rate"] == 0.0

    def test_stats_with_data(self, tracker):
        # Record and check 3 signals: 2 hits, 1 miss
        for i, (sig_type, price, check_price, expected_hit) in enumerate([
            ("BUY", 100.0, 110.0, True),
            ("BUY", 100.0, 90.0, False),
            ("SELL", 100.0, 90.0, True),
        ]):
            run(tracker.record(
                signal_id=f"stats-{i}", symbol="BTC", pair="BTC-USDT",
                signal=sig_type, score=50.0 if sig_type == "BUY" else -50.0,
                confidence=70.0, price_at_signal=price,
            ))
            tracker._memory._signals[f"stats-{i}"]["timestamp"] = "2020-01-01T00:00:00Z"

        run(tracker.check_outcomes("4h", {"BTC": 110.0}))
        # First BUY: 100→110 hit, Second BUY: 100→110 hit (price went up),
        # SELL: 100→110 miss (price went up, but SELL expected down)
        stats = run(tracker.get_accuracy_stats(horizon="4h"))
        assert stats["total"] == 3
        assert stats["hit_rate"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])