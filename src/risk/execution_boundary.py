"""Execution capability boundary for the research sandbox.

This module does not submit orders. It classifies a requested action into a
research-safe outcome before any simulated risk rule or UI action can use it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ExecutionCapability = Literal["none", "simulation_only", "real_order"]
RequestedAction = Literal["record_signal", "dry_run_order", "real_order"]
BoundaryOutcome = Literal["research_record", "dry_run", "blocked"]


@dataclass(frozen=True, slots=True)
class ExecutionBoundaryRequest:
    symbol: str
    signal: str
    requested_action: RequestedAction
    capability: ExecutionCapability = "none"
    source: str = "research_sandbox"
    human_confirmed: bool = False


@dataclass(frozen=True, slots=True)
class ExecutionBoundaryResult:
    allowed: bool
    outcome: BoundaryOutcome
    reason: str
    downgraded_from: RequestedAction | None = None


def classify_execution_request(request: ExecutionBoundaryRequest) -> ExecutionBoundaryResult:
    """Keep research signals from becoming real execution actions."""
    if request.capability == "real_order" or request.requested_action == "real_order":
        return ExecutionBoundaryResult(
            allowed=False,
            outcome="blocked",
            reason="research sandbox has no real-order execution capability",
            downgraded_from=request.requested_action,
        )

    if request.requested_action == "dry_run_order":
        if request.capability != "simulation_only":
            return ExecutionBoundaryResult(
                allowed=True,
                outcome="research_record",
                reason="dry-run request downgraded because execution capability is not enabled",
                downgraded_from=request.requested_action,
            )
        if not request.human_confirmed:
            return ExecutionBoundaryResult(
                allowed=True,
                outcome="research_record",
                reason="dry-run request requires explicit human confirmation",
                downgraded_from=request.requested_action,
            )
        return ExecutionBoundaryResult(
            allowed=True,
            outcome="dry_run",
            reason="request may enter simulation only; no account or order API is available",
        )

    return ExecutionBoundaryResult(
        allowed=True,
        outcome="research_record",
        reason="signal is recorded as research evidence, not an execution instruction",
    )
