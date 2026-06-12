# -*- coding: utf-8 -*-
"""
Task node handlers — assign_task, human_input

Auto-extracted from runtime/workflow_executor.py during refactoring.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional


class HandlersTaskMixin:
    """Task node handlers — assign_task, human_input"""

    async def _exec_assign_task(self, node: Dict) -> Dict[str, Any]:
        """Assign task node — creates an issues row (type=task, workflow run + node anchors).

        Node data fields:
        - title: Task title (required)
        - description: Optional (included in inbox body only)
        - assignee_type: member | agent (default: member)
        - assignee_id: User/Agent UUID (required)
        - due_date: Optional due date (YYYY-MM-DD) → schedule_end
        """
        data = node.get("data") or {}
        title = data.get("title") or data.get("task_title") or ""
        if not title:
            return {"ok": False, "error": "assign_task requires title"}

        assignee_id = data.get("assignee_id") or ""
        assignee_type = data.get("assignee_type") or "member"
        if not assignee_id:
            return {"ok": False, "error": "assign_task requires assignee_id"}

        description = (data.get("description") or "").strip()
        due_date = data.get("due_date")
        node_id = str(node.get("id") or "")
        if not node_id:
            return {"ok": False, "error": "assign_task requires node id"}

        schedule_end = None
        if due_date:
            schedule_end = str(due_date).strip()[:10] or None

        upstream_ctx = self._ctx.format_upstream_context(current_node_id=node_id)
        body_extra = description
        if upstream_ctx:
            block = "\n\n---\n## Workflow Context\n" + upstream_ctx
            body_extra = (description + block) if description else ("## Workflow Context\n" + upstream_ctx)

        try:
            # PR-E4b (SDK extraction §5 PR-E4b): IssueDao.create is now
            # sourced via the IssueRepository Protocol.  Legacy fallback
            # preserves Phase 0 runtime behaviour; Phase 2 removes the
            # fallback when ``dao/`` leaves the engine import surface.
            # ``IssueRow`` is re-exported from the Protocol module so
            # engine code does not need ``dao.mysql.*`` imports.
            from vendor_runtime_sdk.runtime.protocols.issue_repository import (
                IssueRow,
                get_issue_repository,
            )

            tid = str(uuid.uuid4())
            wf_id = str(self._workflow.get("id") or "") or None

            context_refs = []
            if wf_id:
                context_refs.append({"kind": "runtime_workflow", "id": wf_id, "name": ""})
            context_refs.append({"kind": "workflow_node", "id": node_id, "name": title[:128]})

            issue = IssueRow(
                id=tid,
                workspace_id=self._workspace_id,
                issue_type="task",
                title=title[:512],
                description=body_extra or None,
                status="pending",
                priority="medium",
                assignee_type=assignee_type,
                assignee_id=assignee_id,
                creator_type="member",
                creator_id=assignee_id,
                owner_type=assignee_type,
                owner_id=assignee_id,
                parent_issue_id=self._primary_issue_id,
                source_type="workflow_assign",
                labels=[],
                custom_fields={},
                type_config={"workflow_node_source": "workflow_assign"},
                position=float(time.time()),
                due_date=schedule_end,
                estimated_hours=None,
                context_refs=context_refs,
                workflow_run_id=str(self._run_id),
                workflow_graph_node_id=str(node_id),
            )
            issue_repo = get_issue_repository()
            await issue_repo.create(issue)

            inbox_issue = self._primary_issue_id
            try:
                # PR-E4c: Use runtime.protocols.InboxRepository so the
                # engine does not depend on business-side
                # ``dao.mysql.inbox`` directly. The protocol's legacy
                # fallback wraps the production DAO transparently
                # (byte-identical behaviour today).
                from vendor_runtime_sdk.runtime.protocols.inbox_repository import (
                    InboxItemRow,
                    get_inbox_repository,
                )

                inbox_repo = get_inbox_repository()
                await inbox_repo.create(
                    InboxItemRow(
                        id=str(uuid.uuid4()),
                        workspace_id=self._workspace_id,
                        recipient_type=assignee_type,
                        recipient_id=assignee_id,
                        type="workflow_node_task_assigned",
                        severity="info",
                        issue_id=tid,
                        title=f"节点任务: {title}",
                        body=(body_extra or f"Workflow run {self._run_id} · node {node_id} · task {tid}")[:16000],
                    )
                )
            except Exception as e:
                logger.warning("assign_task: inbox notification failed: %s", e)

            logger.info(
                "assign_task: created node task issue %s on node %s for %s:%s",
                tid,
                node_id,
                assignee_type,
                assignee_id,
            )
            return {
                "ok": True,
                "node_task_id": tid,
                "task_id": tid,
                "node_id": node_id,
                "title": title,
                "owner_type": assignee_type,
                "owner_id": assignee_id,
                "status": "todo",
                "schedule_end": schedule_end,
                "primary_issue_id": self._primary_issue_id,
            }
        except Exception as e:
            logger.exception("assign_task failed: %s", e)
            return {"ok": False, "error": str(e)}

    async def _exec_human_input(self, node: Dict) -> Dict[str, Any]:
        """Human input node — blocks workflow, requires human confirmation."""
        data = node.get("data") or {}
        prompt = data.get("prompt") or data.get("message") or "请确认继续执行"
        timeout_hours = int(data.get("timeout_hours") or 24)
        timeout_seconds = min(timeout_hours * 3600, 86400)

        # Submit an approval request for human confirmation
        return await self._exec_approval({
            "id": node.get("id"),
            "data": {
                **data,
                "approval_type": "workflow_human_input",
                "title": f"人工确认: {node.get('id', 'unknown')}",
                "reason": prompt,
            },
        })


logger = logging.getLogger(__name__)
