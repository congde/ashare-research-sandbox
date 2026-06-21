from __future__ import annotations

from risk import ExecutionBoundaryRequest, classify_execution_request


def test_research_signal_stays_research_record() -> None:
    result = classify_execution_request(
        ExecutionBoundaryRequest(
            symbol="BTC/USDT",
            signal="BUY",
            requested_action="record_signal",
        )
    )

    assert result.allowed is True
    assert result.outcome == "research_record"
    assert result.downgraded_from is None
    assert "not an execution instruction" in result.reason


def test_dry_run_without_confirmation_is_downgraded_to_research_record() -> None:
    result = classify_execution_request(
        ExecutionBoundaryRequest(
            symbol="BTC/USDT",
            signal="BUY",
            requested_action="dry_run_order",
            capability="simulation_only",
            human_confirmed=False,
        )
    )

    assert result.allowed is True
    assert result.outcome == "research_record"
    assert result.downgraded_from == "dry_run_order"


def test_confirmed_dry_run_never_becomes_real_order() -> None:
    result = classify_execution_request(
        ExecutionBoundaryRequest(
            symbol="BTC/USDT",
            signal="BUY",
            requested_action="dry_run_order",
            capability="simulation_only",
            human_confirmed=True,
        )
    )

    assert result.allowed is True
    assert result.outcome == "dry_run"
    assert "no account or order API" in result.reason


def test_real_order_request_is_blocked_even_when_confirmed() -> None:
    result = classify_execution_request(
        ExecutionBoundaryRequest(
            symbol="BTC/USDT",
            signal="BUY",
            requested_action="real_order",
            capability="real_order",
            human_confirmed=True,
        )
    )

    assert result.allowed is False
    assert result.outcome == "blocked"
    assert result.downgraded_from == "real_order"
    assert "no real-order execution capability" in result.reason
