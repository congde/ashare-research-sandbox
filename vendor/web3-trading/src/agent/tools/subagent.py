# -*- coding: utf-8 -*-
"""
Subagent Manager

Manages background sub-tasks that run as independent agent loops.
Inspired by nanobot's subagent.py pattern.

Subagents are lightweight, in-process background tasks that:
- Have their own ReAct loop with limited tool access
- Run concurrently via asyncio.create_task()
- Report results back via a callback function
- Cannot spawn further subagents (prevents recursive spawning)

Use cases:
- Parallel data gathering from multiple tools
- Background research tasks while the main agent responds
- Async processing that doesn't need to block the SSE stream
"""

import asyncio
import uuid
import logging
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

from agent.tools.registry import ToolRegistry
from agent.tools.loop import AgentLoop, LoopEvent, LoopEventType

logger = logging.getLogger(__name__)


# ============================================================
# Subagent Types and Events
# ============================================================

class SubagentStatus(str, Enum):
    """Status of a subagent task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SubagentTask:
    """Tracks the state of a spawned subagent."""
    task_id: str
    label: str
    task_description: str
    status: SubagentStatus = SubagentStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    elapsed_ms: Optional[int] = None
    asyncio_task: Optional[asyncio.Task] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubagentResult:
    """Result reported by a completed subagent."""
    task_id: str
    label: str
    success: bool
    content: str
    elapsed_ms: int
    iterations: int = 0
    tool_calls_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# Type for the callback that receives subagent results
SubagentCallback = Callable[[SubagentResult], Coroutine[Any, Any, None]]


# ============================================================
# Subagent Manager
# ============================================================

class SubagentManager:
    """
    Manages spawning and tracking of background subagent tasks.
    
    Each subagent gets:
    - Its own AgentLoop with limited max_iterations
    - A scoped ToolRegistry (no spawn tool to prevent recursion)
    - A dedicated system prompt for the subtask
    - A callback for reporting results
    
    Usage:
        manager = SubagentManager(llm=client, model_name="gpt-4")
        
        task_id = await manager.spawn(
            task="Analyze BTC market data",
            label="btc_analysis",
            tool_registry=main_registry.create_subset(exclude={"spawn_subagent"}),
            callback=handle_result,
        )
        
        # Check status
        status = manager.get_task_status(task_id)
        
        # Wait for all tasks
        results = await manager.wait_all()
    """

    # Default system prompt for subagents
    DEFAULT_SUBAGENT_PROMPT = (
        "You are a focused task execution agent. Your job is to complete the given task "
        "efficiently using the available tools. Be concise and direct in your approach. "
        "When you have gathered enough information, provide a clear summary of your findings."
    )

    def __init__(
        self,
        llm,
        model_name: str,
        max_subagent_iterations: int = 15,
        max_concurrent_subagents: int = 5,
        default_temperature: float = 0.3,
        default_max_tokens: int = 1000,
        default_timeout: float = 30.0,
        extra_body: Optional[Dict] = None,
    ):
        """
        Initialize the SubagentManager.
        
        Args:
            llm: OpenAI AsyncOpenAI client
            model_name: Model name for subagent LLM calls
            max_subagent_iterations: Max ReAct iterations per subagent
            max_concurrent_subagents: Max number of concurrent subagents
            default_temperature: Default LLM temperature for subagents
            default_max_tokens: Default max tokens for subagents
            default_timeout: Default API timeout for subagents
            extra_body: Extra body parameters for LLM calls
        """
        self.llm = llm
        self.model_name = model_name
        self.max_subagent_iterations = max_subagent_iterations
        self.max_concurrent_subagents = max_concurrent_subagents
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self.default_timeout = default_timeout
        self.extra_body = extra_body

        self._tasks: Dict[str, SubagentTask] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent_subagents)

    async def spawn(
        self,
        task: str,
        tool_registry: ToolRegistry,
        label: Optional[str] = None,
        callback: Optional[SubagentCallback] = None,
        system_prompt: Optional[str] = None,
        max_iterations: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Spawn a background subagent to execute a task.
        
        Args:
            task: Task description for the subagent
            tool_registry: Scoped ToolRegistry for the subagent
            label: Human-readable label for the task
            callback: Async callback to receive the result
            system_prompt: Custom system prompt (uses default if None)
            max_iterations: Override max iterations for this subagent
            metadata: Additional metadata to attach to the task
            
        Returns:
            task_id: Unique identifier for the spawned task
        """
        task_id = uuid.uuid4().hex[:8]
        label = label or f"subagent_{task_id}"

        subagent_task = SubagentTask(
            task_id=task_id,
            label=label,
            task_description=task,
            metadata=metadata or {},
        )
        self._tasks[task_id] = subagent_task

        # Create the asyncio task
        bg_task = asyncio.create_task(
            self._run_subagent(
                subagent_task=subagent_task,
                tool_registry=tool_registry,
                callback=callback,
                system_prompt=system_prompt or self.DEFAULT_SUBAGENT_PROMPT,
                max_iterations=max_iterations or self.max_subagent_iterations,
            )
        )
        subagent_task.asyncio_task = bg_task
        bg_task.add_done_callback(lambda _: self._on_task_done(task_id))

        logger.info(
            f"Spawned subagent '{label}' (id={task_id}): {task[:100]}..."
            if len(task) > 100 else f"Spawned subagent '{label}' (id={task_id}): {task}"
        )
        return task_id

    async def _run_subagent(
        self,
        subagent_task: SubagentTask,
        tool_registry: ToolRegistry,
        callback: Optional[SubagentCallback],
        system_prompt: str,
        max_iterations: int,
    ) -> None:
        """
        Internal method that runs a subagent's ReAct loop.
        
        Uses a semaphore to limit concurrent subagents.
        """
        async with self._semaphore:
            subagent_task.status = SubagentStatus.RUNNING
            start_time = time.time()

            try:
                # Create the AgentLoop for this subagent
                loop = AgentLoop(
                    llm=self.llm,
                    model_name=self.model_name,
                    tool_registry=tool_registry,
                    max_iterations=max_iterations,
                    temperature=self.default_temperature,
                    max_tokens=self.default_max_tokens,
                    timeout=self.default_timeout,
                    extra_body=self.extra_body,
                )

                # Build messages for the subagent
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": subagent_task.task_description},
                ]

                # Run the loop to completion
                final_content = await loop.run_to_completion(messages)

                elapsed_ms = int((time.time() - start_time) * 1000)
                subagent_task.status = SubagentStatus.COMPLETED
                subagent_task.result = final_content
                subagent_task.completed_at = time.time()
                subagent_task.elapsed_ms = elapsed_ms

                logger.info(
                    f"Subagent '{subagent_task.label}' completed in {elapsed_ms}ms, "
                    f"iterations={loop.iteration_count}, tool_calls={loop.total_tool_calls}"
                )

                # Report result via callback
                if callback:
                    result = SubagentResult(
                        task_id=subagent_task.task_id,
                        label=subagent_task.label,
                        success=True,
                        content=final_content,
                        elapsed_ms=elapsed_ms,
                        iterations=loop.iteration_count,
                        tool_calls_count=loop.total_tool_calls,
                        metadata=subagent_task.metadata,
                    )
                    try:
                        await callback(result)
                    except Exception as cb_err:
                        logger.error(f"Subagent callback failed: {cb_err}")

            except asyncio.CancelledError:
                subagent_task.status = SubagentStatus.CANCELLED
                subagent_task.completed_at = time.time()
                subagent_task.elapsed_ms = int((time.time() - start_time) * 1000)
                logger.warning(f"Subagent '{subagent_task.label}' was cancelled")

            except Exception as e:
                elapsed_ms = int((time.time() - start_time) * 1000)
                error_msg = f"{type(e).__name__}: {str(e)}"
                subagent_task.status = SubagentStatus.FAILED
                subagent_task.error = error_msg
                subagent_task.completed_at = time.time()
                subagent_task.elapsed_ms = elapsed_ms

                logger.exception(
                    f"Subagent '{subagent_task.label}' failed after {elapsed_ms}ms: {error_msg}"
                )

                # Report failure via callback
                if callback:
                    result = SubagentResult(
                        task_id=subagent_task.task_id,
                        label=subagent_task.label,
                        success=False,
                        content=f"Task failed: {error_msg}",
                        elapsed_ms=elapsed_ms,
                        metadata=subagent_task.metadata,
                    )
                    try:
                        await callback(result)
                    except Exception as cb_err:
                        logger.error(f"Subagent failure callback failed: {cb_err}")

    def _on_task_done(self, task_id: str) -> None:
        """Callback when an asyncio task completes."""
        task = self._tasks.get(task_id)
        if task and task.status == SubagentStatus.RUNNING:
            # Task ended unexpectedly
            task.status = SubagentStatus.FAILED
            task.error = "Task ended unexpectedly"
            task.completed_at = time.time()

    # ============================================================
    # Task Management
    # ============================================================

    def get_task(self, task_id: str) -> Optional[SubagentTask]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def get_task_status(self, task_id: str) -> Optional[SubagentStatus]:
        """Get the status of a task."""
        task = self._tasks.get(task_id)
        return task.status if task else None

    def get_running_tasks(self) -> List[SubagentTask]:
        """Get all currently running tasks."""
        return [t for t in self._tasks.values() if t.status == SubagentStatus.RUNNING]

    def get_all_tasks(self) -> List[SubagentTask]:
        """Get all tracked tasks."""
        return list(self._tasks.values())

    @property
    def running_count(self) -> int:
        """Number of currently running subagents."""
        return len(self.get_running_tasks())

    @property
    def total_count(self) -> int:
        """Total number of tracked tasks (all states)."""
        return len(self._tasks)

    def cancel(self, task_id: str) -> bool:
        """
        Cancel a running subagent task.
        
        Args:
            task_id: ID of the task to cancel
            
        Returns:
            True if the task was found and cancelled
        """
        task = self._tasks.get(task_id)
        if not task or not task.asyncio_task:
            return False

        if task.status == SubagentStatus.RUNNING:
            task.asyncio_task.cancel()
            task.status = SubagentStatus.CANCELLED
            task.completed_at = time.time()
            logger.info(f"Cancelled subagent '{task.label}' (id={task_id})")
            return True
        return False

    def cancel_all(self) -> int:
        """
        Cancel all running subagent tasks.
        
        Returns:
            Number of tasks cancelled
        """
        cancelled = 0
        for task_id, task in self._tasks.items():
            if task.status == SubagentStatus.RUNNING and task.asyncio_task:
                task.asyncio_task.cancel()
                task.status = SubagentStatus.CANCELLED
                task.completed_at = time.time()
                cancelled += 1
        if cancelled:
            logger.info(f"Cancelled {cancelled} running subagent(s)")
        return cancelled

    async def wait_all(self, timeout: Optional[float] = None) -> List[SubagentResult]:
        """
        Wait for all spawned subagent tasks to complete.
        
        Args:
            timeout: Maximum time to wait in seconds (None = wait forever)
            
        Returns:
            List of SubagentResult for completed tasks
        """
        tasks = [
            t.asyncio_task for t in self._tasks.values()
            if t.asyncio_task and not t.asyncio_task.done()
        ]

        if tasks:
            logger.info(f"Waiting for {len(tasks)} subagent(s) to complete...")
            done, pending = await asyncio.wait(tasks, timeout=timeout)

            if pending:
                logger.warning(f"{len(pending)} subagent(s) still running after timeout")
                for t in pending:
                    t.cancel()

        # Collect results
        results = []
        for task in self._tasks.values():
            results.append(SubagentResult(
                task_id=task.task_id,
                label=task.label,
                success=task.status == SubagentStatus.COMPLETED,
                content=task.result or task.error or "",
                elapsed_ms=task.elapsed_ms or 0,
                metadata=task.metadata,
            ))
        return results

    async def cleanup(self) -> None:
        """Cancel all running tasks and clear the task registry."""
        self.cancel_all()
        self._tasks.clear()
        logger.debug("SubagentManager cleaned up")
