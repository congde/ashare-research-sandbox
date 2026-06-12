# -*- coding: utf-8 -*-
"""
Persistence — node results, context save, node assignments sync

Auto-extracted from runtime/workflow_executor.py during refactoring.
"""

from __future__ import annotations

import logging
import json
from typing import Any, Dict, List, Optional

class PersistenceMixin:
    """Persistence — node results, context save, node assignments sync"""

    async def _persist_node_results(self) -> None:
        """Persist current node_results to database for real-time frontend polling.

        Uses a dirty flag to avoid redundant writes — only flushes when
        node_results have actually changed since the last persist.
        """
        if not getattr(self, "_node_results_dirty", True):
            return
        try:
            # PR-E4 (SDK extraction §5 PR-E4): RuntimeWorkflowDao is now accessed via the
            # WorkflowRunRepository Protocol.  The legacy dao.mysql.runtime_workflow is
            # still used via the _LegacyWorkflowRunRepository fallback so runtime
            # behaviour is unchanged in Phase 0.  Phase 2 removes the fallback when
            # dao/ leaves the engine import surface.
            from vendor_runtime_sdk.runtime.protocols.workflow_run_repository import (
                get_workflow_run_repository,
            )
            _repo = get_workflow_run_repository()
            await _repo.update_run(
                self._run_id,
                {"node_results": self._node_results},
            )
            self._node_results_dirty = False
        except Exception as _e:
            logger.warning("Failed to persist node_results: %s", _e)

    def _mark_results_dirty(self) -> None:
        """Mark node_results as needing persistence."""
        self._node_results_dirty = True

    async def _save_context(self) -> None:
        """Persist current WorkflowContext + node_results in a single UPDATE."""
        try:
            # PR-E4 (SDK extraction §5 PR-E4): RuntimeWorkflowDao is now accessed via the
            # WorkflowRunRepository Protocol.  The legacy dao.mysql.runtime_workflow is
            # still used via the _LegacyWorkflowRunRepository fallback so runtime
            # behaviour is unchanged in Phase 0.  Phase 2 removes the fallback when
            # dao/ leaves the engine import surface.
            from vendor_runtime_sdk.runtime.protocols.workflow_run_repository import (
                get_workflow_run_repository,
            )
            repo = get_workflow_run_repository()
            ctx_dict = self._ctx.to_dict()
            ctx_json = json.dumps(ctx_dict, ensure_ascii=False, default=str)
            payload: Dict[str, Any] = {"workflow_context": ctx_json}
            if getattr(self, "_node_results_dirty", True):
                payload["node_results"] = self._node_results
                self._node_results_dirty = False
            await repo.update_run(self._run_id, payload)
        except Exception as e:
            logger.warning("Failed to persist WorkflowContext: %s", e)

    async def _sync_node_assignments(self) -> None:
        """Extract assignee_member_ids from graph_data nodes and sync to
        workflow_node_assignments table.

        Called once at run start so that the "my pending nodes" query
        can find assignments even before the engine reaches those nodes.
        """
        try:
            from dao.mysql.workflow_node_assignment import get_workflow_node_assignment_dao

            node_assignments: List[Dict[str, Any]] = []
            for node in self._nodes:
                node_data = node.get("data") or {}
                assignee_ids = node_data.get("assignee_member_ids")
                if not assignee_ids:
                    continue
                if isinstance(assignee_ids, str):
                    try:
                        import json as _json
                        assignee_ids = _json.loads(assignee_ids)
                    except (json.JSONDecodeError, TypeError):
                        assignee_ids = [assignee_ids]
                if not isinstance(assignee_ids, list):
                    assignee_ids = [assignee_ids]

                assignee_roles = node_data.get("assignee_roles") or []
                due_at = node_data.get("due_at")

                # Build role map from assignee_roles
                role_map: Dict[str, str] = {}
                for ar in assignee_roles:
                    if isinstance(ar, dict):
                        role_map[ar.get("member_id", "")] = ar.get("role", "mentioned")

                for mid in assignee_ids:
                    role = role_map.get(
                        mid,
                        "primary" if mid == assignee_ids[0] else "mentioned",
                    )
                    node_assignments.append({
                        "node_id": node.get("id", ""),
                        "member_id": mid,
                        "role": role,
                        "due_at": due_at,
                    })

            if not node_assignments:
                return

            dao = get_workflow_node_assignment_dao()
            count = await dao.sync_assignments(
                workspace_id=self._workspace_id,
                workflow_id=self._workflow.get("id", ""),
                run_id=self._run_id,
                node_assignments=node_assignments,
            )
            logger.info(
                "Synced %d node assignments for run %s",
                count, self._run_id,
            )
        except Exception as e:
            logger.warning("Failed to sync node assignments for run %s: %s", self._run_id, e)

    # ── Confirmation gate ──

    _CONFIRM_POLL_INTERVAL = 5   # seconds between polls
    _CONFIRM_MAX_WAIT = 86400    # 24 hours max wait


logger = logging.getLogger(__name__)
