# -*- coding: utf-8 -*-
"""
IO node handlers — webhook, parallel, schedule, subworkflow

Auto-extracted from runtime/workflow_executor.py during refactoring.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from vendor_runtime_sdk.runtime.workflow_executor._helpers import _MAX_SUBWORKFLOW_DEPTH
from string import Template
from typing import Any, Dict, List, Optional


class HandlersIoMixin:
    """IO node handlers — webhook, parallel, schedule, subworkflow"""

    @staticmethod
    def _is_safe_url(url: str) -> bool:
        """Check that a URL is safe to request (no SSRF to internal networks)."""
        import ipaddress
        import socket
        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        try:
            resolved = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in resolved:
                ip = ipaddress.ip_address(sockaddr[0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return False
        except (socket.gaierror, ValueError):
            return False
        return True

    async def _exec_webhook(self, node: Dict) -> Dict[str, Any]:
        data = node.get("data") or {}
        url = data.get("url") or ""
        method = (data.get("method") or "POST").upper()
        headers = data.get("headers") if isinstance(data.get("headers"), dict) else {}
        body_template = data.get("body_template") or ""
        if not url:
            return {"ok": False, "error": "missing url"}
        if not self._is_safe_url(url):
            return {"ok": False, "error": "blocked: private/internal address"}
        try:
            tpl = Template(body_template)
            body = tpl.safe_substitute({**self._variables, **{"results": json.dumps(self._node_results)}})
        except Exception:
            body = body_template
        timeout = httpx.Timeout(30.0)
        async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
            req_kw: Dict[str, Any] = {"method": method, "url": url, "headers": headers or None}
            if method in ("POST", "PUT", "PATCH") and body:
                req_kw["content"] = body.encode("utf-8")
            resp = await client.request(**req_kw)
        return {
            "ok": 200 <= resp.status_code < 400,
            "status_code": resp.status_code,
            "text": resp.text[:8000],
        }

    async def _exec_parallel(self, node: Dict) -> Dict[str, Any]:
        data = node.get("data") or {}
        branch_ids = data.get("branch_node_ids") or []
        if not isinstance(branch_ids, list):
            return {"ok": False, "error": "branch_node_ids must be a list"}
        tasks = []
        for bid in branch_ids:
            child = self._nodes_by_id.get(str(bid))
            if child:
                tasks.append(self._execute_node(child))
        if not tasks:
            return {"ok": True, "branches": []}
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = []
        for r in results:
            if isinstance(r, Exception):
                out.append({"ok": False, "error": str(r)})
            else:
                out.append(r)
        return {"ok": True, "branches": out}

    async def _exec_schedule(self, node: Dict) -> Dict[str, Any]:
        data = node.get("data") or {}
        delay = float(data.get("delay_seconds") or 0)
        await asyncio.sleep(min(delay, 3600.0))
        return {"ok": True, "delayed_seconds": delay}

    async def _exec_subworkflow(self, node: Dict) -> Dict[str, Any]:
        data = node.get("data") or {}
        wid = data.get("workflow_id") or ""
        if not wid:
            return {"ok": False, "error": "missing workflow_id"}
        if self._nesting_depth >= _MAX_SUBWORKFLOW_DEPTH:
            return {"ok": False, "error": "max subworkflow nesting depth exceeded"}
        # PR-E4 (SDK extraction §5 PR-E4): RuntimeWorkflowDao is now accessed via the
        # WorkflowRunRepository Protocol.  The legacy dao.mysql.runtime_workflow is
        # still used via the _LegacyWorkflowRunRepository fallback so runtime
        # behaviour is unchanged in Phase 0.  Phase 2 removes the fallback when
        # dao/ leaves the engine import surface.
        from vendor_runtime_sdk.runtime.protocols.workflow_run_repository import (
            get_workflow_run_repository,
        )

        repo = get_workflow_run_repository()
        nested = await repo.get_workflow_by_id(wid)
        if not nested:
            return {"ok": False, "error": f"workflow {wid} not found"}
        child_run_id = str(uuid.uuid4())
        child = WorkflowExecutor(nested, child_run_id, self._workspace_id, nesting_depth=self._nesting_depth + 1)
        await child.start()
        snap = None
        if child._runtime:
            try:
                snap = child._runtime.snapshot()
            except Exception:
                snap = None
        return {"ok": True, "child_run_id": child_run_id, "child_snapshot": snap}

