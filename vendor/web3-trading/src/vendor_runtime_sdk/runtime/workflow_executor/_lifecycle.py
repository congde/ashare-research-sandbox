# -*- coding: utf-8 -*-
"""
Node lifecycle — lifecycle state, blocking, story events, subtask wait, confirmation wait

Auto-extracted from runtime/workflow_executor.py during refactoring.
"""

from __future__ import annotations

import asyncio
import logging
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

class LifecycleMixin:
    """Node lifecycle — lifecycle state, blocking, story events, subtask wait, confirmation wait"""

    def _get_node_lifecycle(self, node_id: str) -> str:
        """Read the current lifecycle of a node from WorkflowContext."""
        try:
            node_states = self._ctx._state.get("node_states", {})
            node_state = node_states.get(node_id, {})
            return node_state.get("lifecycle", "")
        except Exception:
            return ""

    def _is_node_blocked(self, node_id: str) -> bool:
        """Check if a node has been rejected (lifecycle=blocked)."""
        return self._get_node_lifecycle(node_id) == "blocked"

    async def _fire_story_on_node_done(self, node_id: str, node_ok: bool) -> None:
        """Story-bound automation (``on_node_done`` rules) for this DAG node."""
        if not self._primary_issue_id:
            return
        try:
            from vendor_runtime_sdk.runtime.story_workflow_automation import fire_on_node_done

            await fire_on_node_done(
                workspace_id=self._workspace_id,
                run_id=self._run_id,
                primary_issue_id=self._primary_issue_id,
                node_id=node_id,
                node_ok=node_ok,
            )
        except Exception as e:
            logger.warning("fire_on_node_done failed for node %s: %s", node_id, e)

    async def _wait_until_workflow_subtasks_terminal(
        self,
        node_id: str,
        node_type: str,
        node_label: str,
    ) -> bool:
        """Poll until all issues.task rows for this run+node are done/cancelled (or none exist).

        Returns False if cancelled or timed out (caller must not enter human-confirm wait).
        """
        from dao.mysql.issue import get_issue_dao

        issue_dao = get_issue_dao()
        elapsed = 0
        while elapsed < self._CONFIRM_MAX_WAIT:
            if self._cancel_requested:
                if node_id in self._node_results:
                    self._node_results[node_id]["status"] = "cancelled_before_confirm"
                    self._node_results[node_id]["ok"] = False
                    self._node_results[node_id]["error"] = "Workflow run cancelled"
                await self._persist_node_results()
                return False
            ok, incomplete = await issue_dao.workflow_node_subtasks_completion_for_gate(
                self._workspace_id, self._run_id, node_id,
            )
            if ok:
                if node_id in self._node_results:
                    self._node_results[node_id].pop("subtasks_incomplete_count", None)
                return True

            if node_id in self._node_results:
                self._node_results[node_id]["status"] = "waiting_subtasks"
                self._node_results[node_id]["subtasks_incomplete_count"] = len(incomplete)
                self._node_results[node_id]["node_type"] = node_type
                self._node_results[node_id]["label"] = node_label
            await self._persist_node_results()
            # Mirror into workflow_context so run-detail / assignments API expose lifecycle.
            try:
                node_states = self._ctx._state.setdefault("node_states", {})
                ns = node_states.setdefault(node_id, {})
                ns["lifecycle"] = "waiting_subtasks"
                ns["subtasks_incomplete_count"] = len(incomplete)
                await self._save_context()
            except Exception as e:
                logger.warning("Failed to persist waiting_subtasks lifecycle for %s: %s", node_id, e)

            await asyncio.sleep(self._CONFIRM_POLL_INTERVAL)
            elapsed += self._CONFIRM_POLL_INTERVAL

        logger.warning(
            "Subtask completion wait timed out for node %s after %ds",
            node_id,
            elapsed,
        )
        if node_id in self._node_results:
            self._node_results[node_id]["status"] = "subtasks_wait_timeout"
            self._node_results[node_id]["ok"] = False
            self._node_results[node_id]["error"] = (
                "Timed out waiting for all workflow subtasks to finish"
            )
        await self._persist_node_results()
        try:
            node_states = self._ctx._state.setdefault("node_states", {})
            ns = node_states.setdefault(node_id, {})
            ns["lifecycle"] = "subtasks_wait_timeout"
            await self._save_context()
        except Exception as e:
            logger.warning("Failed to persist subtasks_wait_timeout lifecycle for %s: %s", node_id, e)
        return False

    async def _wait_for_node_confirmation(
        self,
        node_id: str,
        node_type: str,
        node_label: str,
        node_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Block execution after a node with require_user_confirm until
        a human confirms or rejects it via the confirmation API.

        When ``require_subtasks_done_before_confirm`` is not false, and this node has
        run-scoped workflow subtasks (issues.task rows), wait until every subtask is
        ``done`` or ``cancelled`` before entering ``waiting_confirm``.

        The node's lifecycle in workflow_context.node_states transitions:
          - running → waiting_confirm  (set here)
          - waiting_confirm → succeeded (set by confirm API)
          - waiting_confirm → blocked   (set by reject API)
        """
        from vendor_runtime_sdk.runtime.workflow_subtask_gate import subtasks_done_gate_enabled

        nd = node_data if isinstance(node_data, dict) else {}
        if subtasks_done_gate_enabled(nd):
            sub_ok = await self._wait_until_workflow_subtasks_terminal(
                node_id, node_type, node_label,
            )
            if not sub_ok:
                await self._fire_story_on_node_done(node_id, False)
                return

        # Mark node as waiting_confirm in WorkflowContext
        try:
            node_states = self._ctx._state.setdefault("node_states", {})
            node_state = node_states.setdefault(node_id, {})
            node_state.pop("subtasks_incomplete_count", None)
            node_state["lifecycle"] = "waiting_confirm"
            node_state["waiting_confirm_at"] = datetime.now().isoformat()
            await self._save_context()
        except Exception as e:
            logger.warning("Failed to set waiting_confirm for node %s: %s", node_id, e)

        # Update node_results so frontend can see the state
        if node_id in self._node_results:
            self._node_results[node_id]["status"] = "waiting_confirm"
            self._node_results[node_id]["require_user_confirm"] = True
        await self._persist_node_results()

        # Poll workflow_context for confirmation
        elapsed = 0
        while elapsed < self._CONFIRM_MAX_WAIT:
            if self._cancel_requested:
                await self._fire_story_on_node_done(node_id, False)
                return

            await asyncio.sleep(self._CONFIRM_POLL_INTERVAL)
            elapsed += self._CONFIRM_POLL_INTERVAL

            # Re-read workflow_context from DB (confirm API writes to it)
            try:
                from dao.mysql.runtime_workflow import get_runtime_workflow_dao
                dao = get_runtime_workflow_dao()
                run = await dao.get_run(self._run_id)
                if run:
                    ctx = run.get("workflow_context")
                    if isinstance(ctx, str):
                        try:
                            ctx = json.loads(ctx)
                        except (json.JSONDecodeError, TypeError):
                            ctx = {}
                    if isinstance(ctx, dict):
                        ns = ctx.get("node_states", {})
                        state = ns.get(node_id, {})
                        lifecycle = state.get("lifecycle", "")

                        if lifecycle == "succeeded":
                            logger.info(
                                "Node %s confirmed by %s, resuming workflow",
                                node_id, state.get("confirmed_by", "unknown"),
                            )
                            # Sync local context
                            self._ctx._state.setdefault("node_states", {})[node_id] = state
                            # Update node_results
                            if node_id in self._node_results:
                                self._node_results[node_id]["status"] = "confirmed"
                                self._node_results[node_id]["confirmed_by"] = state.get("confirmed_by")
                                self._node_results[node_id]["confirmed_at"] = state.get("confirmed_at")
                            await self._persist_node_results()
                            await self._fire_story_on_node_done(node_id, True)
                            return

                        if lifecycle == "blocked":
                            logger.info(
                                "Node %s rejected, blocking downstream execution",
                                node_id,
                            )
                            self._ctx._state.setdefault("node_states", {})[node_id] = state
                            if node_id in self._node_results:
                                self._node_results[node_id]["status"] = "blocked"
                                self._node_results[node_id]["ok"] = False
                                self._node_results[node_id]["error"] = (
                                    state.get("blocked_reason") or "Rejected by human"
                                )
                            await self._persist_node_results()
                            await self._fire_story_on_node_done(node_id, False)
                            return
            except Exception as e:
                logger.warning("Error polling confirmation for node %s: %s", node_id, e)

        # Timeout: mark as timeout
        logger.warning("Confirmation timeout for node %s after %ds", node_id, elapsed)
        if node_id in self._node_results:
            self._node_results[node_id]["status"] = "confirm_timeout"
            self._node_results[node_id]["ok"] = False
            self._node_results[node_id]["error"] = "Confirmation timed out"
        await self._persist_node_results()
        await self._fire_story_on_node_done(node_id, False)

    # ── Auto-review scoring ──


logger = logging.getLogger(__name__)
