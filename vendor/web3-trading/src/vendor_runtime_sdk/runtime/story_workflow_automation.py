# -*- coding: utf-8 -*-
"""Evaluate Story automation rules when workflow events occur."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _condition_passes(condition: Optional[Dict[str, Any]], ctx: Dict[str, Any]) -> bool:
    if not condition:
        return True
    expected_ok = condition.get("require_node_ok")
    if expected_ok is not None and bool(expected_ok) != bool(ctx.get("node_ok")):
        return False
    return True


async def fire_on_node_done(
    *,
    workspace_id: str,
    run_id: str,
    primary_issue_id: Optional[str],
    node_id: str,
    node_ok: bool,
) -> None:
    """Fire enabled `on_node_done` rules for the Story bound to this run."""
    if not primary_issue_id:
        return
    try:
        from dao.mysql.story_workflow_automation import get_story_workflow_automation_dao

        dao = get_story_workflow_automation_dao()
        rules = await dao.list_by_issue(workspace_id, primary_issue_id, enabled_only=True)
    except Exception as e:
        logger.warning("fire_on_node_done: list rules failed: %s", e)
        return

    ctx = {"run_id": run_id, "node_id": node_id, "node_ok": node_ok}
    for rule in rules:
        if rule.get("trigger_type") != "on_node_done":
            continue
        tn = rule.get("trigger_node_id")
        if tn and str(tn) != str(node_id):
            continue
        cond = rule.get("condition_json")
        if isinstance(cond, str):
            try:
                import json

                cond = json.loads(cond)
            except Exception:
                cond = {}
        if not _condition_passes(cond if isinstance(cond, dict) else {}, ctx):
            continue
        await _execute_action(workspace_id, primary_issue_id, rule, ctx)


async def _execute_action(
    workspace_id: str,
    issue_id: str,
    rule: Dict[str, Any],
    ctx: Dict[str, Any],
) -> None:
    at = (rule.get("action_type") or "inbox").strip().lower()
    aj = rule.get("action_json") or {}
    if isinstance(aj, str):
        try:
            import json

            aj = json.loads(aj) if aj else {}
        except Exception:
            aj = {}

    if at != "inbox":
        logger.debug("story automation: unsupported action_type=%s rule=%s", at, rule.get("id"))
        return

    title = str(aj.get("title") or rule.get("name") or "Workflow automation")
    body_tpl = str(aj.get("body") or "Node {node_id} finished (run {run_id}).")
    body = body_tpl.format(**ctx)

    recipient_type = str(aj.get("recipient_type") or "member")
    recipient_id = str(aj.get("recipient_id") or "").strip()
    if not recipient_id:
        logger.warning("story automation inbox: missing recipient_id rule=%s", rule.get("id"))
        return

    try:
        # PR-E4c: Use runtime.protocols.InboxRepository so the engine
        # does not depend on business-side ``dao.mysql.inbox`` directly.
        # The protocol's legacy fallback wraps the production DAO
        # transparently (byte-identical behaviour today).
        from vendor_runtime_sdk.runtime.protocols.inbox_repository import (
            InboxItemRow,
            get_inbox_repository,
        )

        inbox_repo = get_inbox_repository()
        await inbox_repo.create(
            InboxItemRow(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                recipient_type=recipient_type,
                recipient_id=recipient_id,
                type="workflow_automation",
                severity=str(aj.get("severity") or "info"),
                issue_id=issue_id,
                title=title[:512],
                body=body[:16000] if body else None,
            )
        )
    except Exception as e:
        logger.warning("story automation inbox failed: %s", e)
