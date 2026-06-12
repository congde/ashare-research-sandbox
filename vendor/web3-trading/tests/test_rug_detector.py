# -*- coding: utf-8 -*-
"""
Tests for src/signal/rug_detector.py
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from signal_analysis.rug_detector import (
    analyze_liquidity_risk,
    analyze_holder_concentration,
    analyze_social_risk,
    analyze_contract_risk,
    assess_rug_pull_risk,
    RugRiskSignal,
    RugPullAssessment,
)


class TestAnalyzeLiquidityRisk:
    def test_stable_tvl_low_risk(self):
        sig = analyze_liquidity_risk(1_000_000, 1_000_000, 1_000_000)
        assert sig.score < 0.25
        assert sig.severity == "low"

    def test_24h_tvl_drop_50pct_high_risk(self):
        # -50% hits the "< -0.5" boundary → score 0.6 (the < -0.3 branch)
        sig = analyze_liquidity_risk(500_000, 1_000_000, 1_200_000)
        assert sig.score >= 0.55  # includes 7d drop too
        assert sig.severity in ("medium", "high", "critical")

    def test_24h_tvl_drop_over_50pct_high_risk(self):
        # -60% clearly exceeds -0.5 threshold → score 0.9
        sig = analyze_liquidity_risk(400_000, 1_000_000, 1_200_000)
        assert sig.score >= 0.85
        assert sig.severity in ("high", "critical")

    def test_24h_tvl_drop_30pct_medium_risk(self):
        # -30% hits "< -0.3" but NOT "< -0.5" → score 0.35 (the < -0.15 branch)
        sig = analyze_liquidity_risk(700_000, 1_000_000, 1_000_000)
        assert sig.score >= 0.3
        assert sig.severity in ("low", "medium")

    def test_24h_tvl_drop_35pct_medium_risk(self):
        # -35% exceeds -0.3 threshold → score 0.6
        sig = analyze_liquidity_risk(650_000, 1_000_000, 1_000_000)
        assert sig.score >= 0.55
        assert sig.severity in ("medium", "high")

    def test_7d_tvl_drop_70pct(self):
        # 24h: -40% (< -0.3 → 0.6), 7d: -70% (< -0.7 → 0.85 but max with 24h 0.6)
        # The 7d change is exactly -0.7 which is NOT < -0.7 (strict)
        sig = analyze_liquidity_risk(300_000, 500_000, 1_000_000)
        assert sig.score >= 0.55

    def test_7d_tvl_drop_over_70pct(self):
        # -75% clearly exceeds 0.7 → score 0.85
        sig = analyze_liquidity_risk(250_000, 500_000, 1_000_000)
        assert sig.score >= 0.8

    def test_large_lp_removals(self):
        changes = [
            {"type": "remove", "amountUsd": "100000"},
            {"type": "remove", "amountUsd": "80000"},
            {"type": "remove", "amountUsd": "60000"},
        ]
        sig = analyze_liquidity_risk(800_000, 1_000_000, 1_000_000, changes)
        assert sig.score >= 0.6

    def test_zero_tvl_24h_ago(self):
        sig = analyze_liquidity_risk(100_000, 0, 0)
        assert sig.dimension == "liquidity"

    def test_evidence_populated(self):
        sig = analyze_liquidity_risk(400_000, 1_000_000, 1_000_000)
        assert "TVL" in sig.evidence


class TestAnalyzeHolderConcentration:
    def test_distributed_holders_low_risk(self):
        sig = analyze_holder_concentration(30, 28, 5000)
        assert sig.score < 0.25

    def test_top10_above_90pct_critical(self):
        sig = analyze_holder_concentration(92, 90, 100)
        assert sig.score >= 0.8

    def test_top10_above_80pct_high(self):
        sig = analyze_holder_concentration(85, 83, 500)
        assert sig.score >= 0.55

    def test_concentration_spike(self):
        sig = analyze_holder_concentration(70, 50, 1000)
        assert sig.score >= 0.7
        assert "上升" in sig.evidence

    def test_very_few_holders(self):
        sig = analyze_holder_concentration(40, 38, 30)
        assert sig.score >= 0.6
        assert "30" in sig.evidence

    def test_moderate_holders(self):
        sig = analyze_holder_concentration(40, 38, 150)
        assert sig.score >= 0.25


class TestAnalyzeSocialRisk:
    def test_stable_heat_low_risk(self):
        sig = analyze_social_risk(100, 95)
        assert sig.score < 0.25

    def test_heat_drop_80pct(self):
        sig = analyze_social_risk(10, 100)
        assert sig.score >= 0.5
        assert "骤降" in sig.evidence

    def test_no_project_update_30d(self):
        sig = analyze_social_risk(50, 50, last_project_update_hours=800)
        assert sig.score >= 0.6
        assert "未更新" in sig.evidence

    def test_no_project_update_14d(self):
        sig = analyze_social_risk(50, 50, last_project_update_hours=400)
        assert sig.score >= 0.3

    def test_zero_heat_previous(self):
        sig = analyze_social_risk(50, 0)
        assert sig.dimension == "social"


class TestAnalyzeContractRisk:
    def test_clean_contract_low_risk(self):
        sig = analyze_contract_risk(
            is_open_source=True, has_audit=True,
        )
        assert sig.score < 0.1

    def test_honeypot_critical(self):
        sig = analyze_contract_risk(is_honeypot=True)
        assert sig.score == 1.0
        assert "蜜罐" in sig.evidence

    def test_mint_authority_high(self):
        sig = analyze_contract_risk(has_mint_authority=True)
        assert sig.score >= 0.6

    def test_blacklist_medium(self):
        sig = analyze_contract_risk(has_blacklist=True)
        assert sig.score >= 0.4

    def test_not_open_source_and_no_audit(self):
        sig = analyze_contract_risk(is_open_source=False, has_audit=False)
        assert sig.score >= 0.5

    def test_risk_labels_with_rug(self):
        sig = analyze_contract_risk(risk_labels=["possible_rug_pull"])
        assert sig.score >= 0.85

    def test_pause_function(self):
        sig = analyze_contract_risk(has_pause_function=True)
        assert sig.score >= 0.3


class TestAssessRugPullRisk:
    def test_all_safe_signals(self):
        signals = [
            RugRiskSignal(dimension="liquidity", score=0.1, severity="low", evidence="ok"),
            RugRiskSignal(dimension="holders", score=0.1, severity="low", evidence="ok"),
            RugRiskSignal(dimension="contract", score=0.05, severity="low", evidence="ok"),
            RugRiskSignal(dimension="social", score=0.1, severity="low", evidence="ok"),
        ]
        result = assess_rug_pull_risk("TEST", "ethereum", "0x123", signals)
        assert result.risk_level == "safe"
        assert not result.should_block_signal
        assert "✅" in result.recommendation

    def test_high_risk_blocks_signal(self):
        signals = [
            RugRiskSignal(dimension="liquidity", score=0.9, severity="critical", evidence="TVL crashed"),
            RugRiskSignal(dimension="holders", score=0.7, severity="high", evidence="concentrated"),
            RugRiskSignal(dimension="contract", score=0.8, severity="high", evidence="mint authority"),
            RugRiskSignal(dimension="social", score=0.6, severity="high", evidence="silence"),
        ]
        result = assess_rug_pull_risk("SCAM", "bsc", "0xdead", signals)
        assert result.risk_level in ("high", "critical")
        assert result.should_block_signal is True

    def test_critical_signal_overrides(self):
        # Even with only one critical signal
        signals = [
            RugRiskSignal(dimension="contract", score=0.95, severity="critical",
                          evidence="honeypot"),
            RugRiskSignal(dimension="liquidity", score=0.1, severity="low", evidence="ok"),
        ]
        result = assess_rug_pull_risk("TRAP", "solana", "abc", signals)
        assert result.composite_score >= 0.8
        assert result.should_block_signal is True

    def test_medium_risk_recommendation(self):
        signals = [
            RugRiskSignal(dimension="liquidity", score=0.5, severity="medium",
                          evidence="TVL下降30%"),
            RugRiskSignal(dimension="holders", score=0.4, severity="medium",
                          evidence="集中度偏高"),
        ]
        result = assess_rug_pull_risk("MID", "ethereum", "0x456", signals)
        assert result.risk_level in ("medium", "low")
        assert not result.should_block_signal

    def test_empty_signals(self):
        result = assess_rug_pull_risk("EMPTY", "ethereum", "0x789", [])
        assert result.risk_level == "safe"
        assert result.composite_score == 0

    def test_result_has_timestamp(self):
        signals = [
            RugRiskSignal(dimension="liquidity", score=0.1, severity="low", evidence="ok"),
        ]
        result = assess_rug_pull_risk("TIME", "ethereum", "0xabc", signals)
        assert result.timestamp > 0

    def test_result_fields(self):
        signals = [
            RugRiskSignal(dimension="liquidity", score=0.3, severity="medium",
                          evidence="some drop"),
        ]
        result = assess_rug_pull_risk("FIELD", "bsc", "0xdef", signals)
        assert isinstance(result, RugPullAssessment)
        assert result.symbol == "FIELD"
        assert result.chain == "bsc"
        assert result.contract_address == "0xdef"
        assert len(result.signals) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])