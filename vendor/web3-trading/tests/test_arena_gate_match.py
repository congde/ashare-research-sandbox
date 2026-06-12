# -*- coding: utf-8 -*-
"""Regression tests for hybrid Arena ↔ LLM gate matching."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arena.engine import arena_signal_matches_llm_gate  # noqa: E402


def test_weak_short_direction_matches_sell_gate():
    signal = {
        "agent_name": "technical_signal",
        "symbol": "BTC",
        "action": "WEAK_SHORT",
        "execution_action": "hold",
        "direction": "short",
    }
    assert arena_signal_matches_llm_gate(signal, "sell", match_mode="direction")


def test_wait_neutral_does_not_match_buy_gate():
    signal = {
        "agent_name": "technical_signal",
        "symbol": "HYPE",
        "action": "WAIT",
        "execution_action": "hold",
        "direction": "neutral",
    }
    assert not arena_signal_matches_llm_gate(signal, "buy", match_mode="direction")


def test_claude_hold_does_not_block_technical_direction_match():
    """At least one execution agent must match; claude hold alone is insufficient."""
    assert arena_signal_matches_llm_gate(
        {
            "agent_name": "claude_agent",
            "symbol": "BTC",
            "action": "hold",
            "execution_action": "hold",
            "direction": "neutral",
        },
        "sell",
        match_mode="direction",
    ) is False
