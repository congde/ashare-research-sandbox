# -*- coding: utf-8 -*-
"""
LaneManager — Parallel execution track management.

From claw-code V2:
  Lane = work unit / parallel execution track
  - Each Lane binds to an independent workspace_root
  - Sessions between Lanes don't share, preventing data races
  - Lanes communicate via structured events
  - Lane states: Created → Running → Completed → Failed → Stopped

Relationship with existing code:
  - Lane is a HIGH-LEVEL parallel isolation unit
  - Lane wraps ConversationRuntime (src/runtime/conversation.py)
  - Lane executes TaskPacket (src/runtime/task_packet.py) via DAGPlan
  - Lane uses WorkspaceManager (src/runtime/workspace.py) for isolation

  Existing DAG executor (src/agent/dag_executor.py) is the LOW-LEVEL engine.
  Lane is the HIGH-LEVEL orchestration that manages:
    - Session isolation
    - TaskPacket lifecycle
    - Inter-lane event communication
    - Failure + escalation handling

Hierarchy:
  LaneManager (manages multiple lanes)
    └── Lane (one parallel track)
          ├── ConversationRuntime (ReAct loop)
          ├── Session (isolated state)
          ├── TaskPacket (task definition)
          └── WorkspaceManager (filesystem)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
import sys
from enum import Enum
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    class StrEnum(str, Enum): pass

from typing import Any, Callable, Dict, List, Optional

from vendor_runtime_sdk.runtime.task_packet import TaskPacket, EscalationType
from vendor_runtime_sdk.runtime.workspace import WorkspaceManager, WorkspaceInfo

logger = logging.getLogger(__name__)


# ──────────────── Lane State ────────────────


class LaneState(StrEnum):
    """Lane lifecycle states"""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"  # Gracefully stopped
    DEGRADED = "degraded"  # Running with degraded capability


@dataclass
class LaneEvent:
    """Structured event emitted by lanes"""

    lane_id: str
    event_type: str  # "progress" | "tool_call" | "result" | "error" | "degraded"
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""


@dataclass
class LaneResult:
    """Final result of a lane execution"""

    lane_id: str
    state: LaneState
    output: str = ""
    tool_calls: List[Dict] = field(default_factory=list)
    acceptance_passed: bool = False
    acceptance_failures: List[str] = field(default_factory=list)
    duration_ms: float = 0.0


# ──────────────── Lane ────────────────


class Lane:
    """
    A single parallel execution track.

    Each Lane has:
    - Its own Session (isolated from other lanes)
    - Its own workspace (filesystem isolation)
    - A TaskPacket defining what to accomplish
    - Event emission for inter-lane communication

    Usage:
        lane = Lane(lane_id="lane_1", task_packet=packet, ...)
        result = await lane.execute()
    """

    def __init__(
        self,
        lane_id: str,
        task_packet: TaskPacket,
        workspace: WorkspaceInfo,
        llm_client=None,  # LLMClient protocol
        tool_executor=None,  # ToolExecutor protocol
        conversation_runtime=None,  # Optional pre-built runtime
        event_callback: Optional[Callable[[LaneEvent], None]] = None,
    ):
        self.lane_id = lane_id
        self.task_packet = task_packet
        self.workspace = workspace
        self._llm_client = llm_client
        self._tool_executor = tool_executor
        self._conversation_runtime = conversation_runtime
        self._event_callback = event_callback
        self._state = LaneState.CREATED
        self._result: Optional[LaneResult] = None
        self._events: List[LaneEvent] = []

    @property
    def state(self) -> LaneState:
        return self._state

    @property
    def result(self) -> Optional[LaneResult]:
        return self._result

    def emit_event(self, event_type: str, data: Optional[Dict] = None) -> None:
        """Emit a structured event"""
        from vendor_runtime_sdk.agent.utils import utc_now_iso

        event = LaneEvent(
            lane_id=self.lane_id,
            event_type=event_type,
            data=data or {},
            timestamp=utc_now_iso(),
        )
        self._events.append(event)
        if self._event_callback:
            try:
                self._event_callback(event)
            except Exception as e:
                logger.warning("Lane %s event callback error: %s", self.lane_id, e)

    async def execute(self) -> LaneResult:
        """
        Execute the lane's task.

        Delegates to ConversationRuntime if available,
        otherwise falls back to direct LLM + tool execution.
        """
        import time

        self._state = LaneState.RUNNING
        self.emit_event("progress", {"status": "starting"})
        start_time = time.monotonic()

        try:
            # Use ConversationRuntime if provided
            if self._conversation_runtime:
                result = await self._conversation_runtime.run_turn(
                    user_input=self.task_packet.objective,
                    system_prompt=self._build_system_prompt(),
                )
                output = result.text
                tool_calls = result.tool_calls
            elif self._llm_client:
                # Fallback: direct LLM call (simplified, no tool loop)
                result = await self._llm_client.complete(
                    messages=[{"role": "user", "content": self.task_packet.objective}],
                    system_prompt=self._build_system_prompt(),
                    tools=[],
                )
                output = result.text
                tool_calls = result.tool_calls
            else:
                raise RuntimeError("Lane has no LLM client or conversation runtime")

            # Run acceptance tests
            acceptance_passed, failures = self._run_acceptance_tests(output)

            self._state = LaneState.COMPLETED if acceptance_passed else LaneState.DEGRADED
            self.emit_event("result", {
                "status": "completed" if acceptance_passed else "degraded",
                "output_length": len(output),
            })

        except Exception as e:
            self._state = LaneState.FAILED
            output = ""
            tool_calls = []
            acceptance_passed = False
            failures = [str(e)]
            self.emit_event("error", {"error": str(e)})

            # Handle escalation
            if self.task_packet.escalation_policy.on_failure == EscalationType.ABORT:
                self._state = LaneState.STOPPED
            elif self.task_packet.escalation_policy.on_failure == EscalationType.DEGRADE:
                self._state = LaneState.DEGRADED

        duration_ms = (time.monotonic() - start_time) * 1000

        self._result = LaneResult(
            lane_id=self.lane_id,
            state=self._state,
            output=output,
            tool_calls=tool_calls,
            acceptance_passed=acceptance_passed,
            acceptance_failures=failures,
            duration_ms=duration_ms,
        )
        return self._result

    async def stop(self) -> None:
        """Gracefully stop the lane"""
        self._state = LaneState.STOPPED
        self.emit_event("progress", {"status": "stopped"})

    def _build_system_prompt(self) -> str:
        """Build system prompt incorporating TaskPacket context"""
        parts = [
            f"Task: {self.task_packet.objective}",
            f"Scope: {', '.join(self.task_packet.scope)}",
            f"Repository: {self.task_packet.repo}",
        ]
        if self.task_packet.acceptance_tests:
            parts.append("Acceptance criteria:")
            for test in self.task_packet.acceptance_tests:
                parts.append(f"  - {test.name}: {test.description}")
        return "\n".join(parts)

    def _run_acceptance_tests(self, output: str) -> tuple[bool, List[str]]:
        """Run acceptance tests against the output"""
        failures = []
        for test in self.task_packet.acceptance_tests:
            try:
                # Simple assertion evaluation
                assertion = test.assertion.lower()
                if assertion.startswith("output.contains("):
                    # Extract the expected string
                    inner = assertion[len("output.contains("):-1].strip("'\"")
                    if inner not in output:
                        failures.append(f"{test.name}: expected '{inner}' in output")
                elif assertion.startswith("success == true"):
                    pass  # Always passes if we got here
                elif assertion == "output.length > 0":
                    if not output.strip():
                        failures.append(f"{test.name}: output is empty")
            except Exception as e:
                failures.append(f"{test.name}: assertion error - {e}")

        required_failures = [
            f for f, t in zip(failures, self.task_packet.acceptance_tests)
            if t.required
        ]
        return len(required_failures) == 0, failures


# ──────────────── LaneManager ────────────────


class LaneManager:
    """
    Manages multiple parallel lanes — creation, execution, monitoring.

    Usage:
        mgr = LaneManager(workspace_mgr=WorkspaceManager())
        lane = await mgr.create_lane(user_id="u1", task_packet=packet)
        result = await mgr.execute_lane(lane.lane_id)
        # Or execute all lanes in parallel:
        results = await mgr.execute_all()
    """

    def __init__(
        self,
        workspace_mgr: Optional[WorkspaceManager] = None,
        max_concurrent: int = 5,
    ):
        self._workspace_mgr = workspace_mgr or WorkspaceManager()
        self._max_concurrent = max_concurrent
        self._lanes: Dict[str, Lane] = {}
        self._event_history: List[LaneEvent] = []
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def create_lane(
        self,
        user_id: str,
        task_packet: TaskPacket,
        llm_client=None,
        tool_executor=None,
        conversation_runtime=None,
        lane_id: Optional[str] = None,
    ) -> Lane:
        """
        Create a new lane with isolated workspace.

        Args:
            user_id: Owner user ID
            task_packet: Structured task definition
            lane_id: Optional explicit lane ID

        Returns:
            Configured Lane instance (not yet executing)
        """
        lid = lane_id or f"lane_{uuid.uuid4().hex[:8]}"

        # Create isolated workspace
        workspace = self._workspace_mgr.create_workspace(
            user_id=user_id,
            lane_id=lid,
        )

        # Create lane
        lane = Lane(
            lane_id=lid,
            task_packet=task_packet,
            workspace=workspace,
            llm_client=llm_client,
            tool_executor=tool_executor,
            conversation_runtime=conversation_runtime,
            event_callback=self._on_lane_event,
        )

        self._lanes[lid] = lane
        logger.info("Created lane %s for user %s", lid, user_id)
        return lane

    async def execute_lane(self, lane_id: str) -> Optional[LaneResult]:
        """Execute a single lane"""
        lane = self._lanes.get(lane_id)
        if not lane:
            logger.warning("Lane %s not found", lane_id)
            return None

        async with self._semaphore:
            return await lane.execute()

    async def execute_all(self) -> Dict[str, LaneResult]:
        """Execute all created lanes in parallel (up to max_concurrent)"""
        tasks = {}
        for lane_id, lane in self._lanes.items():
            if lane.state in (LaneState.CREATED,):
                tasks[lane_id] = asyncio.create_task(self.execute_lane(lane_id))

        results = {}
        for lane_id, task in tasks.items():
            try:
                results[lane_id] = await task
            except Exception as e:
                logger.error("Lane %s execution failed: %s", lane_id, e)
                results[lane_id] = LaneResult(
                    lane_id=lane_id,
                    state=LaneState.FAILED,
                    output="",
                    acceptance_failures=[str(e)],
                )

        return results

    async def stop_lane(self, lane_id: str) -> bool:
        """Gracefully stop a running lane"""
        lane = self._lanes.get(lane_id)
        if not lane:
            return False
        await lane.stop()
        return True

    def get_lane(self, lane_id: str) -> Optional[Lane]:
        """Get a lane by ID"""
        return self._lanes.get(lane_id)

    def list_lanes(
        self,
        state: Optional[LaneState] = None,
        user_id: Optional[str] = None,
    ) -> List[Lane]:
        """List lanes, optionally filtered"""
        lanes = list(self._lanes.values())
        if state:
            lanes = [l for l in lanes if l.state == state]
        if user_id:
            lanes = [l for l in lanes if l.workspace.owner_id == user_id]
        return lanes

    def get_events(self, lane_id: Optional[str] = None) -> List[LaneEvent]:
        """Get event history, optionally filtered by lane"""
        if lane_id:
            return [e for e in self._event_history if e.lane_id == lane_id]
        return list(self._event_history)

    def cleanup_completed(self) -> int:
        """Remove completed/failed/stopped lanes. Returns count of removed lanes."""
        to_remove = [
            lid for lid, lane in self._lanes.items()
            if lane.state in (LaneState.COMPLETED, LaneState.FAILED, LaneState.STOPPED)
        ]
        for lid in to_remove:
            self._lanes.pop(lid, None)
            self._workspace_mgr.cleanup_workspace(lid)
        return len(to_remove)

    # ──────────────── Internal ────────────────

    def _on_lane_event(self, event: LaneEvent) -> None:
        """Collect lane events"""
        self._event_history.append(event)
        # Keep event history bounded
        if len(self._event_history) > 1000:
            self._event_history = self._event_history[-500:]
