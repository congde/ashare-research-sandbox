# -*- coding: utf-8 -*-
"""
Unit tests for agent.lead_trader module.

Covers:
- metadata: LeadTraderProfile, StrategyVersion, LeadTraderRegistry
- signal_audit: SignalAuditRecord, SignalAuditStore, consistency checking
- constraints: StrategyConstraints, ConstraintChecker, ConstraintViolation
- observability: TraceContext, EventRecorder
- follow_deeplink: FollowDeeplink, DeeplinkFactory
- read_store: BacktestResultRecord, LeaderboardEntry, SignalBacktestReadStore

NOTE: These tests import lead_trader submodules directly to avoid the
heavy dependency chain in agent.__init__ (Redis, MongoDB, LLM config, etc.).
"""

import importlib
import os
import sys
import types

# Add src to path before any imports
_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

# -----------------------------------------------------------------------
# Prevent agent.__init__ from executing by pre-loading a stub agent package
# that only exposes lead_trader as a sub-package.
# -----------------------------------------------------------------------
# Remove any pre-existing agent package so we can install our stub
for key in list(sys.modules.keys()):
    if key.startswith("agent."):
        del sys.modules[key]
if "agent" in sys.modules:
    del sys.modules["agent"]

# Create a minimal agent package that does NOT auto-import heavy deps
_agent_pkg = types.ModuleType("agent")
_agent_pkg.__path__ = [os.path.join(_src, "agent")]
_agent_pkg.__package__ = "agent"
sys.modules["agent"] = _agent_pkg

# Create lead_trader sub-package
_lt_pkg = types.ModuleType("agent.lead_trader")
_lt_pkg.__path__ = [os.path.join(_src, "agent", "lead_trader")]
_lt_pkg.__package__ = "agent.lead_trader"
sys.modules["agent.lead_trader"] = _lt_pkg

import asyncio
import time
import pytest

# ---------------------------------------------------------------------------
# Metadata Tests
# ---------------------------------------------------------------------------
from agent.lead_trader.metadata import (
    LeadTraderProfile,
    StrategyVersion,
    RiskTier,
    StrategyStatus,
    LeadTraderType,
    LeadTraderRegistry,
    get_registry,
)


class TestStrategyVersion:
    def test_creation_defaults(self):
        sv = StrategyVersion(
            version_id="sv-001",
            strategy_id="strat-1",
            version_number=1,
        )
        assert sv.version_id == "sv-001"
        assert sv.status == StrategyStatus.DRAFT
        assert sv.max_position_pct == 30.0
        assert sv.max_leverage == 3
        assert sv.daily_loss_limit_pct == 5.0

    def test_backtest_gate_pass(self):
        sv = StrategyVersion(
            version_id="sv-002",
            strategy_id="strat-1",
            version_number=1,
            backtest_sharpe=1.5,
            backtest_max_drawdown=20.0,
        )
        assert LeadTraderProfile._check_backtest_gate(sv) is True

    def test_backtest_gate_fail_sharpe(self):
        sv = StrategyVersion(
            version_id="sv-003",
            strategy_id="strat-1",
            version_number=1,
            backtest_sharpe=-0.5,
            backtest_max_drawdown=20.0,
        )
        assert LeadTraderProfile._check_backtest_gate(sv) is False

    def test_backtest_gate_fail_drawdown(self):
        sv = StrategyVersion(
            version_id="sv-004",
            strategy_id="strat-1",
            version_number=1,
            backtest_sharpe=1.0,
            backtest_max_drawdown=60.0,
        )
        assert LeadTraderProfile._check_backtest_gate(sv) is False


class TestLeadTraderProfile:
    def _make_profile(self, trader_id="lt-001") -> LeadTraderProfile:
        return LeadTraderProfile(
            trader_id=trader_id,
            name="Test Trader",
            trader_type=LeadTraderType.AI,
            risk_tier=RiskTier.MODERATE,
        )

    def test_creation(self):
        profile = self._make_profile()
        assert profile.trader_id == "lt-001"
        assert profile.risk_tier == RiskTier.MODERATE
        assert profile.is_active is True

    def test_publish_version_requires_backtest_gate(self):
        profile = self._make_profile()
        bad_version = StrategyVersion(
            version_id="sv-bad",
            strategy_id="strat-1",
            version_number=1,
            backtest_sharpe=-1.0,
            backtest_max_drawdown=60.0,
        )
        profile.strategy_versions.append(bad_version)
        result = profile.publish_version("sv-bad")
        assert result is False

    def test_publish_version_success(self):
        profile = self._make_profile()
        good_version = StrategyVersion(
            version_id="sv-good",
            strategy_id="strat-1",
            version_number=1,
            backtest_sharpe=1.5,
            backtest_max_drawdown=20.0,
        )
        profile.strategy_versions.append(good_version)
        result = profile.publish_version("sv-good")
        assert result is True
        assert profile.active_strategy_version == "sv-good"
        assert profile.active_version is not None
        assert profile.active_version.status == StrategyStatus.PUBLISHED


class TestLeadTraderRegistry:
    def _make_registry(self) -> LeadTraderRegistry:
        reg = LeadTraderRegistry()
        profile = LeadTraderProfile(
            trader_id="lt-reg-001",
            name="Registry Trader",
            trader_type=LeadTraderType.AI,
            risk_tier=RiskTier.MODERATE,
        )
        reg.register(profile)
        return reg

    def test_register_and_get(self):
        reg = self._make_registry()
        profile = reg.get("lt-reg-001")
        assert profile is not None
        assert profile.name == "Registry Trader"

    def test_get_nonexistent(self):
        reg = self._make_registry()
        assert reg.get("lt-nonexistent") is None

    def test_filter_by_risk_tier(self):
        reg = LeadTraderRegistry()
        for i, tier in enumerate([RiskTier.CONSERVATIVE, RiskTier.AGGRESSIVE, RiskTier.CONSERVATIVE]):
            profile = LeadTraderProfile(
                trader_id=f"lt-tier-{i}",
                name=f"Trader {i}",
                trader_type=LeadTraderType.AI,
                risk_tier=tier,
            )
            reg.register(profile)

        conservative = reg.list_traders(risk_tier=RiskTier.CONSERVATIVE)
        assert len(conservative) == 2

    def test_singleton(self):
        reg1 = get_registry()
        reg2 = get_registry()
        assert reg1 is reg2


# ---------------------------------------------------------------------------
# Signal Audit Tests
# ---------------------------------------------------------------------------
from agent.lead_trader.signal_audit import (
    SignalAuditRecord,
    SignalAuditStore,
    SignalStatus,
    SignalOrigin,
    get_audit_store,
)


class TestSignalAuditRecord:
    def test_creation(self):
        record = SignalAuditRecord(
            signal_id="sig-001",
            audit_hash="",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="BTC",
            pair="BTC-USDT",
            direction="BUY",
            score=75.0,
            confidence=0.85,
            price_at_signal=50000.0,
        )
        assert record.signal_id == "sig-001"
        assert record.status == SignalStatus.PENDING
        assert record.origin == SignalOrigin.RULE_ENGINE

    def test_integrity_hash(self):
        record = SignalAuditRecord(
            signal_id="sig-002",
            audit_hash="",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="ETH",
            pair="ETH-USDT",
            direction="SELL",
            score=-60.0,
            confidence=0.7,
            price_at_signal=3000.0,
        )
        assert record.audit_hash != ""
        assert record.verify_integrity() is True


class TestSignalAuditStore:
    @pytest.fixture
    def store(self):
        return SignalAuditStore()

    @pytest.mark.asyncio
    async def test_append_and_get(self, store):
        record = SignalAuditRecord(
            signal_id="sig-store-001",
            audit_hash="",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="BTC",
            pair="BTC-USDT",
            direction="BUY",
            score=80.0,
            confidence=0.9,
            price_at_signal=50000.0,
        )
        await store.append(record)
        retrieved = await store.get("sig-store-001")
        assert retrieved is not None
        assert retrieved["pair"] == "BTC-USDT"

    @pytest.mark.asyncio
    async def test_append_only(self, store):
        record = SignalAuditRecord(
            signal_id="sig-dup",
            audit_hash="",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="BTC",
            pair="BTC-USDT",
            direction="BUY",
            score=80.0,
            confidence=0.9,
            price_at_signal=50000.0,
        )
        await store.append(record)
        with pytest.raises(ValueError, match="already exists"):
            await store.append(record)

    @pytest.mark.asyncio
    async def test_consistency_check(self, store):
        # Add audit record
        record = SignalAuditRecord(
            signal_id="sig-cons-001",
            audit_hash="",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="BTC",
            pair="BTC-USDT",
            direction="BUY",
            score=80.0,
            confidence=0.85,
            price_at_signal=50000.0,
        )
        await store.append(record)

        # Matching display record = consistent
        display_records = [{"signal_id": "sig-cons-001", "direction": "BUY", "score": 80.0, "confidence": 0.85, "price_at_signal": 50000.0}]
        result = await store.check_consistency("lt-001", display_records)
        assert result["is_consistent"] is True

        # Mismatching display record = inconsistent
        display_records2 = [{"signal_id": "sig-cons-001", "direction": "SELL", "score": -50.0, "confidence": 0.5, "price_at_signal": 3000.0}]
        result2 = await store.check_consistency("lt-001", display_records2)
        assert result2["is_consistent"] is False

    def test_singleton(self):
        s1 = get_audit_store()
        s2 = get_audit_store()
        assert s1 is s2


# ---------------------------------------------------------------------------
# Constraints Tests
# ---------------------------------------------------------------------------
from agent.lead_trader.constraints import (
    StrategyConstraints,
    ConstraintChecker,
    ConstraintViolation,
    ConstraintSeverity,
)


class TestStrategyConstraints:
    def test_from_risk_tier_conservative(self):
        c = StrategyConstraints.from_risk_tier(RiskTier.CONSERVATIVE)
        assert c.max_leverage == 1
        assert c.max_position_pct == 15.0
        assert c.daily_loss_limit_pct == 2.0

    def test_from_risk_tier_aggressive(self):
        c = StrategyConstraints.from_risk_tier(RiskTier.AGGRESSIVE)
        assert c.max_leverage == 5
        assert c.max_position_pct == 50.0

    def test_from_risk_tier_with_overrides(self):
        c = StrategyConstraints.from_risk_tier(RiskTier.MODERATE, max_leverage=2)
        assert c.max_leverage == 2
        assert c.max_position_pct == 30.0  # default for moderate


class TestConstraintChecker:
    def test_signal_passes_all_constraints(self):
        constraints = StrategyConstraints(
            max_position_pct=30.0,
            max_leverage=3,
            max_confidence_cap=90.0,
        )
        checker = ConstraintChecker(constraints)
        signal = {
            "symbol": "BTC",
            "pair": "BTC-USDT",
            "direction": "long",
            "position_pct": 20.0,
            "leverage": 2,
            "confidence": 80.0,
        }
        violations = checker.check_signal(signal)
        assert len(violations) == 0
        assert checker.is_signal_publishable(signal) is True

    def test_position_exceeds_limit(self):
        constraints = StrategyConstraints(max_position_pct=30.0)
        checker = ConstraintChecker(constraints)
        signal = {
            "symbol": "BTC",
            "pair": "BTC-USDT",
            "position_pct": 50.0,
            "leverage": 1,
        }
        violations = checker.check_signal(signal)
        assert len(violations) == 1
        assert violations[0].constraint_name == "max_position_pct"
        assert violations[0].severity == ConstraintSeverity.BLOCK

    def test_leverage_exceeds_limit(self):
        constraints = StrategyConstraints(max_leverage=3)
        checker = ConstraintChecker(constraints)
        signal = {
            "symbol": "BTC",
            "pair": "BTC-USDT",
            "position_pct": 10.0,
            "leverage": 10,
        }
        violations = checker.check_signal(signal)
        leverage_violations = [v for v in violations if v.constraint_name == "max_leverage"]
        assert len(leverage_violations) == 1
        assert leverage_violations[0].severity == ConstraintSeverity.BLOCK

    def test_blocked_pair(self):
        constraints = StrategyConstraints(blocked_pairs=["SCAM-USDT", "RUG-USDT"])
        checker = ConstraintChecker(constraints)
        signal = {"pair": "SCAM-USDT", "position_pct": 10.0, "leverage": 1}
        violations = checker.check_signal(signal)
        pair_violations = [v for v in violations if v.constraint_name == "blocked_pair"]
        assert len(pair_violations) == 1

    def test_allowed_pair_list(self):
        constraints = StrategyConstraints(allowed_pairs=["BTC-USDT", "ETH-USDT"])
        checker = ConstraintChecker(constraints)
        signal = {"pair": "DOGE-USDT", "position_pct": 10.0, "leverage": 1}
        violations = checker.check_signal(signal)
        pair_violations = [v for v in violations if v.constraint_name == "allowed_pair"]
        assert len(pair_violations) == 1

    def test_compliance_violation_promise_return(self):
        constraints = StrategyConstraints(block_promise_return=True)
        checker = ConstraintChecker(constraints)
        signal = {
            "pair": "BTC-USDT",
            "position_pct": 10.0,
            "leverage": 1,
            "content": "这个策略保证盈利，稳赚不赔！",
        }
        violations = checker.check_signal(signal)
        compliance_violations = [v for v in violations if v.constraint_name == "block_promise_return"]
        assert len(compliance_violations) == 1
        assert compliance_violations[0].severity == ConstraintSeverity.BLOCK

    def test_confidence_over_cap(self):
        constraints = StrategyConstraints(max_confidence_cap=90.0)
        checker = ConstraintChecker(constraints)
        signal = {
            "pair": "BTC-USDT",
            "position_pct": 10.0,
            "leverage": 1,
            "confidence": 98.0,
        }
        violations = checker.check_signal(signal)
        conf_violations = [v for v in violations if v.constraint_name == "max_confidence_cap"]
        assert len(conf_violations) == 1
        assert conf_violations[0].severity == ConstraintSeverity.WARNING  # Warning, not block

    def test_stop_loss_take_profit_unreasonable(self):
        constraints = StrategyConstraints(stop_loss_pct=3.0)
        checker = ConstraintChecker(constraints)
        signal = {
            "pair": "BTC-USDT",
            "position_pct": 10.0,
            "leverage": 1,
            "stop_loss_pct": 15.0,   # way too wide
            "take_profit_pct": 2.0,  # below stop loss
        }
        violations = checker.check_signal(signal)
        assert any(v.constraint_name == "stop_loss_too_wide" for v in violations)
        assert any(v.constraint_name == "take_profit_below_stop" for v in violations)


# ---------------------------------------------------------------------------
# Observability Tests
# ---------------------------------------------------------------------------
from agent.lead_trader.observability import (
    TraceContext,
    EventRecorder,
    EventType,
    init_trace_context,
    get_trace_context,
)


class TestTraceContext:
    def test_init_and_get(self):
        ctx = init_trace_context(trace_id="tr-test-001", user_id="u-001")
        assert ctx.trace_id == "tr-test-001"
        assert ctx.user_id == "u-001"

        retrieved = get_trace_context()
        assert retrieved is not None
        assert retrieved.trace_id == "tr-test-001"

    def test_auto_generate_trace_id(self):
        ctx = init_trace_context()
        assert ctx.trace_id.startswith("tr-")

    def test_elapsed_ms(self):
        ctx = init_trace_context()
        time.sleep(0.05)
        assert ctx.elapsed_ms > 0

    def test_add_event(self):
        ctx = init_trace_context()
        ctx.add_event("test.event", key="value")
        assert len(ctx.events) == 1
        assert ctx.events[0]["key"] == "value"


class TestEventRecorder:
    def test_record_sync(self):
        recorded = []
        recorder = EventRecorder(handlers=[lambda e: recorded.append(e)])
        recorder.record(EventType.SIGNAL_GENERATED, symbol="BTC", direction="long")
        assert len(recorded) == 1
        assert recorded[0]["symbol"] == "BTC"

    def test_record_convenience_methods(self):
        recorded = []
        recorder = EventRecorder(handlers=[lambda e: recorded.append(e)])
        recorder.record_signal_event("BTC-USDT", "BUY", score=75.0, confidence=0.9)
        assert len(recorded) == 1

    def test_record_tool_event(self):
        recorded = []
        recorder = EventRecorder(handlers=[lambda e: recorded.append(e)])
        recorder.record_tool_event("valueScan_api", success=True, duration_ms=150)
        assert len(recorded) == 1


# ---------------------------------------------------------------------------
# Follow Deeplink Tests
# ---------------------------------------------------------------------------
from agent.lead_trader.follow_deeplink import FollowDeeplink, DeeplinkFactory


class TestFollowDeeplink:
    def test_generate_pre_check_token(self):
        dl = FollowDeeplink(
            trader_id="lt-001",
            strategy_version_id="sv-001",
            risk_tier=RiskTier.MODERATE,
            base_url="https://trade.kucoin.com",
        )
        token = dl.generate_pre_check_token(secret_key="test-secret", ttl_seconds=3600)
        assert token != ""
        assert dl.pre_check_expiry > 0

    def test_generate_signature(self):
        dl = FollowDeeplink(
            trader_id="lt-001",
            strategy_version_id="sv-001",
            risk_tier=RiskTier.MODERATE,
            base_url="https://trade.kucoin.com",
        )
        sig = dl.generate_signature(secret_key="test-secret")
        assert sig != ""

    def test_verify_signature(self):
        dl = FollowDeeplink(
            trader_id="lt-001",
            strategy_version_id="sv-001",
            risk_tier=RiskTier.MODERATE,
            base_url="https://trade.kucoin.com",
        )
        dl.generate_signature(secret_key="test-secret")
        assert dl.verify_signature(secret_key="test-secret") is True
        assert dl.verify_signature(secret_key="wrong-secret") is False

    def test_to_url(self):
        dl = FollowDeeplink(
            trader_id="lt-001",
            strategy_version_id="sv-001",
            risk_tier=RiskTier.MODERATE,
            source="feed",
            base_url="https://trade.kucoin.com",
        )
        url = dl.to_url()
        assert "trader_id=lt-001" in url
        assert "strategy_version_id=sv-001" in url
        assert "risk_tier=moderate" in url
        assert "source=feed" in url

    def test_from_url_roundtrip(self):
        dl = FollowDeeplink(
            trader_id="lt-001",
            strategy_version_id="sv-001",
            risk_tier=RiskTier.AGGRESSIVE,
            source="push",
            signal_id="sig-001",
            base_url="https://trade.kucoin.com",
        )
        dl.generate_pre_check_token("secret", 3600)
        dl.generate_signature("secret")
        url = dl.to_url()
        parsed = FollowDeeplink.from_url(url)
        assert parsed.trader_id == "lt-001"
        assert parsed.strategy_version_id == "sv-001"
        assert parsed.risk_tier == RiskTier.AGGRESSIVE
        assert parsed.source == "push"

    def test_expiry(self):
        dl = FollowDeeplink(
            trader_id="lt-001",
            strategy_version_id="sv-001",
            risk_tier=RiskTier.MODERATE,
        )
        dl.pre_check_expiry = int(time.time()) - 10  # expired
        assert dl.is_expired() is True

        dl.pre_check_expiry = int(time.time()) + 3600  # not expired
        assert dl.is_expired() is False


class TestDeeplinkFactory:
    def test_create_deeplink(self):
        factory = DeeplinkFactory(
            secret_key="test-key",
            base_url="https://trade.kucoin.com",
        )
        dl = factory.create(
            trader_id="lt-001",
            strategy_version_id="sv-001",
            risk_tier=RiskTier.MODERATE,
            source="feed",
        )
        assert dl.trader_id == "lt-001"
        assert dl.pre_check_token != ""
        assert dl.signature != ""

    def test_verify_valid_deeplink(self):
        factory = DeeplinkFactory(
            secret_key="test-key",
            base_url="https://trade.kucoin.com",
            token_ttl_seconds=3600,
        )
        dl = factory.create(trader_id="lt-001", strategy_version_id="sv-001")
        result = factory.verify(dl)
        assert result["valid"] is True

    def test_verify_expired_deeplink(self):
        factory = DeeplinkFactory(secret_key="test-key", base_url="https://trade.kucoin.com")
        dl = factory.create(trader_id="lt-001", strategy_version_id="sv-001")
        dl.pre_check_expiry = int(time.time()) - 10  # expired
        result = factory.verify(dl)
        assert result["valid"] is False
        assert any("过期" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Read Store Tests
# ---------------------------------------------------------------------------
from agent.lead_trader.read_store import (
    BacktestResultRecord,
    LeaderboardEntry,
    SignalBacktestReadStore,
    get_read_store,
)


class TestBacktestResultRecord:
    def test_creation(self):
        record = BacktestResultRecord(
            result_id="bt-001",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="BTC",
            pair="BTC-USDT",
        )
        assert record.result_id == "bt-001"
        assert record.gate_passed is False

    def test_auto_generate_id(self):
        record = BacktestResultRecord(
            result_id="",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="ETH",
            pair="ETH-USDT",
        )
        assert record.result_id.startswith("bt-")

    def test_check_gate_pass(self):
        record = BacktestResultRecord(
            result_id="bt-gate-pass-test",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="BTC",
            pair="BTC-USDT",
            sharpe_ratio=1.5,
            max_drawdown_pct=20.0,
            total_trades=50,
            win_rate=0.55,
        )
        assert record.check_gate() is True
        assert record.gate_passed is True

    def test_check_gate_fail(self):
        record = BacktestResultRecord(
            result_id="bt-gate-fail-test",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="BTC",
            pair="BTC-USDT",
            sharpe_ratio=-0.5,
            max_drawdown_pct=60.0,
            total_trades=5,
            win_rate=0.2,
        )
        assert record.check_gate() is False
        assert len(record.gate_details.get("failures", [])) > 0


class TestLeaderboardEntry:
    def test_compute_composite_score(self):
        entry = LeaderboardEntry(
            rank=1,
            trader_id="lt-001",
            trader_name="Test Trader",
            strategy_version_id="sv-001",
            risk_tier="moderate",
            total_return_pct=30.0,
            sharpe_ratio=1.5,
            sortino_ratio=2.0,
            max_drawdown_pct=15.0,
            win_rate=0.6,
            signal_hit_rate=0.7,
        )
        score = entry.compute_composite_score()
        assert 0 <= score <= 100
        assert entry.composite_score == score

    def test_higher_sharpe_higher_score(self):
        entry_high = LeaderboardEntry(
            rank=1, trader_id="lt-high", trader_name="High", strategy_version_id="sv-001",
            risk_tier="moderate", sharpe_ratio=2.0, sortino_ratio=2.5,
            total_return_pct=40.0, max_drawdown_pct=10.0, signal_hit_rate=0.8,
        )
        entry_low = LeaderboardEntry(
            rank=2, trader_id="lt-low", trader_name="Low", strategy_version_id="sv-002",
            risk_tier="moderate", sharpe_ratio=0.5, sortino_ratio=0.7,
            total_return_pct=5.0, max_drawdown_pct=40.0, signal_hit_rate=0.4,
        )
        entry_high.compute_composite_score()
        entry_low.compute_composite_score()
        assert entry_high.composite_score > entry_low.composite_score


class TestSignalBacktestReadStore:
    @pytest.fixture
    def store(self):
        return SignalBacktestReadStore()

    @pytest.mark.asyncio
    async def test_save_and_get(self, store):
        record = BacktestResultRecord(
            result_id="bt-store-001",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="BTC",
            pair="BTC-USDT",
            sharpe_ratio=1.2,
            max_drawdown_pct=25.0,
        )
        await store.save_backtest_result(record)
        retrieved = await store.get_backtest_result("bt-store-001")
        assert retrieved is not None
        assert retrieved["symbol"] == "BTC"

    @pytest.mark.asyncio
    async def test_append_only(self, store):
        record = BacktestResultRecord(
            result_id="bt-dup",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="BTC",
            pair="BTC-USDT",
        )
        await store.save_backtest_result(record)
        with pytest.raises(ValueError, match="already exists"):
            await store.save_backtest_result(record)

    @pytest.mark.asyncio
    async def test_query_by_trader(self, store):
        for i, tid in enumerate(["lt-A", "lt-A", "lt-B"]):
            record = BacktestResultRecord(
                result_id=f"bt-q-{i}",
                trader_id=tid,
                strategy_version_id="sv-001",
                strategy_id="strat-1",
                symbol="BTC",
                pair="BTC-USDT",
            )
            await store.save_backtest_result(record)

        results = await store.query_backtest_results(trader_id="lt-A")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_query_gate_passed_only(self, store):
        record_pass = BacktestResultRecord(
            result_id="bt-gate-pass",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="BTC",
            pair="BTC-USDT",
            sharpe_ratio=1.5,
            max_drawdown_pct=20.0,
            total_trades=50,
            win_rate=0.55,
        )
        record_pass.check_gate()
        await store.save_backtest_result(record_pass)

        record_fail = BacktestResultRecord(
            result_id="bt-gate-fail",
            trader_id="lt-001",
            strategy_version_id="sv-001",
            strategy_id="strat-1",
            symbol="ETH",
            pair="ETH-USDT",
            sharpe_ratio=-0.5,
            max_drawdown_pct=60.0,
        )
        record_fail.check_gate()
        await store.save_backtest_result(record_fail)

        results = await store.query_backtest_results(gate_passed_only=True)
        assert len(results) == 1
        assert results[0]["result_id"] == "bt-gate-pass"

    @pytest.mark.asyncio
    async def test_leaderboard(self, store):
        for i in range(5):
            record = BacktestResultRecord(
                result_id=f"bt-lb-{i}",
                trader_id=f"lt-lb-{i}",
                strategy_version_id="sv-001",
                strategy_id="strat-1",
                symbol="BTC",
                pair="BTC-USDT",
                sharpe_ratio=float(i) * 0.5,
                max_drawdown_pct=30.0 - i * 5,
                total_trades=50,
                win_rate=0.5 + i * 0.05,
            )
            record.check_gate()
            await store.save_backtest_result(record)

        leaderboard = await store.get_leaderboard(top_k=3)
        assert len(leaderboard) <= 3
        if len(leaderboard) >= 2:
            # Higher sharpe should have better composite score
            assert leaderboard[0].composite_score >= leaderboard[1].composite_score

    def test_singleton(self):
        s1 = get_read_store()
        s2 = get_read_store()
        assert s1 is s2
