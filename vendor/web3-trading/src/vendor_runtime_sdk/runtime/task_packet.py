# -*- coding: utf-8 -*-
"""
TaskPacket — Structured task definition for Lane execution.

From claw-code V2:
  Each TaskPacket contains 8 mandatory fields that fully describe
  a business-level task (not a single tool call — that's DAGTask).

  TaskPacket → DAGPlan → DAGTask[]

Hierarchy:
  TaskPacket (business task) ←→ existing DAGTask (tool call unit)
  TaskPacket.objective maps to a DAGPlan
  TaskPacket.acceptance_tests define success criteria
  TaskPacket.escalation_policy defines failure handling

Integration with existing code:
  - TaskPacket wraps around existing DAGPlan (src/agent/dag_executor.py)
  - TaskPacket is consumed by LaneManager to spawn isolated lanes
  - TaskPacket.acceptance_tests complement existing test infrastructure
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
import sys
from enum import Enum
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    class StrEnum(str, Enum): pass

from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──────────────── Enums ────────────────


class BranchPolicy(StrEnum):
    """Branch strategy for the task"""
    MAIN = "main"
    FEATURE = "feature"
    HOTFIX = "hotfix"
    RELEASE = "release"


class CommitPolicy(StrEnum):
    """Commit strategy"""
    DIRECT = "direct"          # Commit directly
    PR = "pr"                  # Create pull request
    DRAFT_PR = "draft_pr"      # Create draft PR
    NONE = "none"              # No commit (read-only)


class EscalationType(StrEnum):
    """What to do on failure"""
    RETRY = "retry"            # Retry once (via RecoveryEngine)
    DEGRADE = "degrade"        # Continue with degraded capability
    NOTIFY = "notify"          # Alert human, continue
    ABORT = "abort"            # Stop the lane immediately
    REDIRECT = "redirect"      # Redirect to a different lane


# ──────────────── Data Classes ────────────────


@dataclass
class EscalationPolicy:
    """Failure handling policy"""

    on_failure: EscalationType = EscalationType.NOTIFY
    max_retries: int = 1         # 0 = no retry, 1 = one retry (RecoveryEngine)
    notify_channel: str = "lark_urgent"  # Alert channel
    redirect_target: Optional[str] = None  # Lane ID to redirect to


@dataclass
class ReportingContract:
    """Output format and frequency contract"""

    output_format: str = "text"  # "text" | "json" | "markdown"
    frequency: str = "on_completion"  # "on_completion" | "streaming" | "periodic"
    include_tool_outputs: bool = False
    max_report_length: int = 10_000


@dataclass
class AcceptanceTest:
    """Single acceptance criterion"""

    name: str
    description: str
    assertion: str  # Expression to evaluate (e.g., "output.contains('BTC')")
    required: bool = True  # If True, failing this test = task failure


# ──────────────── TaskPacket ────────────────


@dataclass
class TaskPacket:
    """
    Structured task definition — 8 mandatory fields.

    This is the business-level task unit, consumed by LaneManager.
    It maps to a DAGPlan (existing dag_executor.py) for actual execution.

    Usage:
        packet = TaskPacket(
            objective="Analyze BTC price trend and generate report",
            scope=["market_data", "price_history"],
            repo="kucoin-market",
            branch_policy=BranchPolicy.MAIN,
            acceptance_tests=[
                AcceptanceTest("has_price", "Output contains BTC price", "output.contains('BTC')"),
            ],
            commit_policy=CommitPolicy.NONE,
            reporting_contract=ReportingContract(output_format="markdown"),
            escalation_policy=EscalationPolicy(on_failure=EscalationType.DEGRADE),
        )
    """

    objective: str                           # What to accomplish
    scope: List[str]                         # What domains/files/modules are involved
    repo: str                                # Associated repo or data source
    branch_policy: BranchPolicy              # Branch strategy
    acceptance_tests: List[AcceptanceTest]   # Success criteria
    commit_policy: CommitPolicy              # Commit strategy
    reporting_contract: ReportingContract    # Output format / frequency
    escalation_policy: EscalationPolicy      # Failure handling

    # Optional metadata
    priority: int = 0                        # Higher = more important
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_packet_id: Optional[str] = None   # For sub-packets spawned by a lane

    # Runtime fields (set by LaneManager)
    packet_id: str = ""
    created_at: str = ""
    status: str = "pending"  # "pending" | "running" | "completed" | "failed" | "degraded"

    def __post_init__(self):
        if not self.packet_id:
            import uuid
            from vendor_runtime_sdk.libs.wrapper import usage_time
            self.packet_id = f"pkt_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            from vendor_runtime_sdk.agent.utils import utc_now_iso
            self.created_at = utc_now_iso()

    def validate(self) -> List[str]:
        """
        Validate all 8 mandatory fields are present and non-empty.
        Returns list of validation errors (empty = valid).
        """
        errors = []
        if not self.objective.strip():
            errors.append("objective is required")
        if not self.scope:
            errors.append("scope must have at least one item")
        if not self.repo.strip():
            errors.append("repo is required")
        if not isinstance(self.branch_policy, BranchPolicy):
            errors.append(f"invalid branch_policy: {self.branch_policy}")
        if not self.acceptance_tests:
            errors.append("at least one acceptance_test is required")
        if not isinstance(self.commit_policy, CommitPolicy):
            errors.append(f"invalid commit_policy: {self.commit_policy}")
        if not isinstance(self.reporting_contract, ReportingContract):
            errors.append("reporting_contract is required")
        if not isinstance(self.escalation_policy, EscalationPolicy):
            errors.append("escalation_policy is required")
        return errors

    def is_valid(self) -> bool:
        """Quick check if all mandatory fields are present"""
        return len(self.validate()) == 0


class ValidatedPacket:
    """
    Wrapper that type-level guarantees all fields are non-empty.

    Usage:
        packet = TaskPacket(...)
        errors = packet.validate()
        if errors:
            raise ValueError(errors)
        validated = ValidatedPacket(packet)  # Only constructable if valid
    """

    def __init__(self, packet: TaskPacket):
        errors = packet.validate()
        if errors:
            raise ValueError(f"Invalid TaskPacket: {errors}")
        self._packet = packet

    @property
    def packet(self) -> TaskPacket:
        return self._packet

    def __getattr__(self, name: str):
        """Delegate all attribute access to the inner TaskPacket"""
        return getattr(self._packet, name)


# ──────────────── Packet Factory ────────────────


def create_simple_packet(
    objective: str,
    scope: Optional[List[str]] = None,
    repo: str = "default",
    **kwargs,
) -> TaskPacket:
    """Convenience factory for simple task packets"""
    return TaskPacket(
        objective=objective,
        scope=scope or ["general"],
        repo=repo,
        branch_policy=kwargs.get("branch_policy", BranchPolicy.MAIN),
        acceptance_tests=kwargs.get("acceptance_tests", [
            AcceptanceTest("default", "Task completes without error", "success == True"),
        ]),
        commit_policy=kwargs.get("commit_policy", CommitPolicy.NONE),
        reporting_contract=kwargs.get("reporting_contract", ReportingContract()),
        escalation_policy=kwargs.get("escalation_policy", EscalationPolicy()),
        priority=kwargs.get("priority", 0),
        tags=kwargs.get("tags", []),
        metadata=kwargs.get("metadata", {}),
    )
