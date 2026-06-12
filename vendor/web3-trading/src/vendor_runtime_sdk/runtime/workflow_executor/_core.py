# -*- coding: utf-8 -*-
"""
Core WorkflowExecutor — init, topo_sort, _execute_node dispatch, _execute, start, cancel

Auto-extracted from runtime/workflow_executor.py during refactoring.
"""

from __future__ import annotations

import time
import asyncio
import logging
import json
import uuid
import os

from datetime import datetime
from typing import Any, Dict, List, Optional
from collections import defaultdict, deque

from vendor_runtime_sdk.runtime.workflow_executor._helpers import (
    _ACTIVE_EXECUTORS, _MAX_SUBWORKFLOW_DEPTH, _WorkflowRuntimeFacade,
)

class WorkflowExecutorCore:
    def __init__(
        self,
        workflow: dict,
        run_id: str,
        workspace_id: str,
        nesting_depth: int = 0,
        primary_issue_id: Optional[str] = None,
    ) -> None:
        self._workflow = workflow
        self._run_id = run_id
        self._workspace_id = workspace_id
        self._nesting_depth = nesting_depth
        self._primary_issue_id = primary_issue_id
        raw_graph = workflow.get("graph_data")
        if isinstance(raw_graph, str):
            try:
                self._graph_data = json.loads(raw_graph)
            except json.JSONDecodeError:
                self._graph_data = {"nodes": [], "edges": []}
        else:
            self._graph_data = raw_graph or {"nodes": [], "edges": []}
        self._nodes: List[Dict] = list(self._graph_data.get("nodes") or [])
        self._edges: List[Dict] = list(self._graph_data.get("edges") or [])
        self._nodes_by_id: Dict[str, Dict] = {n["id"]: n for n in self._nodes if n.get("id")}
        self._runtime: Optional[_WorkflowRuntimeFacade] = None
        self._node_results: Dict[str, Any] = {}
        self._node_results_dirty: bool = True
        self._variables: Dict[str, Any] = dict(workflow.get("variables") or {})
        self._cancel_requested = False
        self._memory_kv: Dict[str, str] = {}
        # ── Runtime module integration ──
        self._activity = None
        self._telemetry_start = None
        try:
            from vendor_runtime_sdk.runtime.activity import ActivityTracker
            self._activity = ActivityTracker(session_id=run_id)
        except Exception:
            pass
        # ── WorkflowContext integration ──
        from vendor_runtime_sdk.agent.orchestration.workflow_context import WorkflowContext
        self._ctx = WorkflowContext(
            task_instance_id=run_id,
            workspace_id=workspace_id,
            workflow_id=workflow.get("id", ""),
            run_id=run_id,
            variables=dict(workflow.get("variables") or {}),
        )

    def _topo_sort(self, nodes: List[Dict], edges: List[Dict]) -> List[List[str]]:
        """Kahn's algorithm — returns list of levels (parallel batches)."""
        adj: Dict[str, List[str]] = defaultdict(list)
        in_degree: Dict[str, int] = {n["id"]: 0 for n in nodes if n.get("id")}
        for e in edges:
            src, tgt = e.get("source"), e.get("target")
            if not src or not tgt:
                continue
            adj[src].append(tgt)
            in_degree.setdefault(tgt, 0)
            in_degree[tgt] += 1
        queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
        levels: List[List[str]] = []
        while queue:
            level = list(queue)
            queue.clear()
            for nid in level:
                for neighbor in adj.get(nid, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)
            levels.append(level)
        processed = sum(len(lv) for lv in levels)
        if processed != len(in_degree):
            raise ValueError("Graph has a cycle or unreachable nodes")
        return levels

    def _build_runtime(self) -> _WorkflowRuntimeFacade:
        return _WorkflowRuntimeFacade(self)

    async def _execute_node(self, node: Dict) -> Dict[str, Any]:
        # Prefer data.type (block type) over ReactFlow node type.
        ntype = (node.get("data") or {}).get("type") or (node.get("type") or "").strip()
        _ALIASES = {
            "agent": "agent_call",
            "tool": "tool_call",
            "llm": "llm_call",
            "if-else": "condition",
            "http-request": "webhook",
            "http_request": "webhook",
            "template-transform": "transform",
            "variable-assigner": "variable_assigner",
            "knowledge-retrieval": "knowledge_retrieval",
            "wait": "wait",
            "notify": "notify",
            "iteration": "iteration",
            "human-input": "human_input",
            "code": "code_exec",
            "doc_generator": "doc_generator",
            "code_generator": "code_generator",
            "assign-task": "assign_task",
            "gate-confirm": "gate_confirm",
        }
        ntype = _ALIASES.get(ntype, ntype)
        handlers = {
            "start": self._exec_passthrough,
            "end": self._exec_passthrough,
            "input": self._exec_passthrough,
            "output": self._exec_passthrough,
            "agent_call": self._exec_agent_call,
            "tool_call": self._exec_tool_call,
            "llm_call": self._exec_llm_call,
            "condition": self._exec_condition,
            "approval": self._exec_approval,
            "gate_confirm": self._exec_gate_confirm,
            "transform": self._exec_transform,
            "policy_gate": self._exec_policy_gate,
            "memory_op": self._exec_memory_op,
            "webhook": self._exec_webhook,
            "parallel": self._exec_parallel,
            "schedule": self._exec_schedule,
            "subworkflow": self._exec_subworkflow,
            "wait": self._exec_wait,
            "notify": self._exec_notify,
            "iteration": self._exec_iteration,
            "human_input": self._exec_human_input,
            "code_exec": self._exec_code,
            "doc_generator": self._exec_doc_generator,
            "code_generator": self._exec_code_generator,
            "assign_task": self._exec_assign_task,
        }
        fn = handlers.get(ntype)
        if not fn:
            return {"ok": False, "error": f"unknown node type: {ntype}"}

        # ── Resolve ${...} expressions in node data ──
        data = node.get("data") or {}
        resolved_data = self._ctx.resolve_all(data)
        node = {**node, "data": resolved_data}

        # ── Activity tracking ──
        node_id_pre = node.get("id", "")
        if self._activity:
            self._activity.touch(f"executing node {node_id_pre} ({ntype})")

        result = await fn(node)

        if self._activity:
            ok = result.get("ok", True) if isinstance(result, dict) else True
            self._activity.touch(f"node {node_id_pre} {'completed' if ok else 'failed'}")

        # ── Track output in WorkflowContext ──
        node_id = node.get("id", "")
        if node_id and result.get("ok", True):
            from vendor_runtime_sdk.agent.orchestration.workflow_context import (
                make_node_output, infer_deliverable_type, Deliverable,
            )
            deliverable_name = resolved_data.get("deliverable_name")
            review_score = None
            review_passed = None

            # Auto-review if acceptance criteria provided
            acceptance_criteria = resolved_data.get("acceptance_criteria")
            if acceptance_criteria and (result.get("content") or result.get("text")):
                try:
                    review_score, review_passed = await self._auto_review(
                        result, resolved_data,
                    )
                except Exception as e:
                    logger.warning("Auto-review failed for node %s: %s", node_id, e)

            node_output = make_node_output(
                node_id=node_id,
                node_type=ntype,
                result=result,
                deliverable_name=deliverable_name,
                review_score=review_score,
                review_passed=review_passed,
            )
            node_output.metadata["label"] = resolved_data.get("label", node_id)
            self._ctx.set_upstream_output(node_id, node_output)

            # Archive deliverable if named
            if deliverable_name:
                content = result.get("content", "") or result.get("text", "") or ""
                deliverable = Deliverable(
                    id=str(uuid.uuid4()),
                    name=deliverable_name,
                    type=infer_deliverable_type(resolved_data),
                    content=str(content),
                    produced_by_node=node_id,
                    produced_by_task=self._run_id,
                    review_score=review_score,
                    review_passed=review_passed,
                    review_status="approved" if review_passed else ("reviewing" if review_score is not None else "draft"),
                )
                self._ctx.add_deliverable(deliverable)
                # Fire-and-forget archive to deliverables table + document library
                try:
                    await self._archive_deliverable(deliverable)
                except Exception as e:
                    logger.warning("Deliverable archive failed for %s: %s", deliverable_name, e)

                # Lark: deliverable archived notification (fire-and-forget)
                try:
                    from services.sdlc_lark_notify import notify_deliverable_archived
                    asyncio.ensure_future(notify_deliverable_archived(
                        deliverable_name=deliverable_name,
                        deliverable_type=deliverable.type,
                        run_id=self._run_id,
                        node_id=node_id,
                    ))
                except Exception:
                    pass

            # Lark: node completed notification (fire-and-forget)
            try:
                from services.sdlc_lark_notify import notify_node_completed
                node_label = resolved_data.get("label", node_id)
                node_status = "completed" if result.get("ok", True) else "failed"
                asyncio.ensure_future(notify_node_completed(
                    run_id=self._run_id,
                    node_id=node_id,
                    node_label=node_label,
                    status=node_status,
                    deliverable_name=deliverable_name,
                ))
            except Exception:
                pass

        return result

    async def _execute(self) -> None:
        self._runtime = self._build_runtime()
        levels = self._topo_sort(self._nodes, self._edges)

        async def _run_node_with_status(nid: str) -> Dict[str, Any]:
            """Execute a single node with real-time status tracking."""
            node = self._nodes_by_id.get(nid, {})
            node_data = node.get("data") or {}
            node_type = node_data.get("type") or node.get("type", "")
            node_label = node_data.get("label") or node.get("label", nid)

            # ── Check if node is blocked (rejected by human) ──
            if self._is_node_blocked(nid):
                self._node_results[nid] = {
                    "ok": False,
                    "error": "node blocked by human rejection",
                    "status": "blocked",
                    "node_type": node_type,
                    "label": node_label,
                }
                await self._persist_node_results()
                return self._node_results[nid]

            # ── Mark node as running ──
            self._node_results[nid] = {
                "status": "running",
                "node_type": node_type,
                "label": node_label,
                "started_at": datetime.now().isoformat(),
            }
            await self._persist_node_results()

            try:
                res = await asyncio.wait_for(
                    self._execute_node(self._nodes_by_id[nid]),
                    timeout=_NODE_TIMEOUT,
                )
                if isinstance(res, dict):
                    res["status"] = "completed" if res.get("ok", True) else "failed"
                    res["node_type"] = res.get("node_type") or node_type
                    res["label"] = res.get("label") or node_label
                    res["completed_at"] = datetime.now().isoformat()
                self._node_results[nid] = res
            except Exception as exc:
                self._node_results[nid] = {
                    "ok": False,
                    "error": str(exc),
                    "status": "failed",
                    "node_type": node_type,
                    "label": node_label,
                    "completed_at": datetime.now().isoformat(),
                }
            # ── Persist after each node completes ──
            await self._persist_node_results()

            # ── Story automation (`on_node_done`) ───────────────────────────
            # When a human-confirm gate applies and execution succeeded, defer
            # automation until confirm/reject/timeout (or subtask wait failure).
            nr = self._node_results.get(nid, {})
            node_ok_exec = bool(nr.get("ok", True))
            require_confirm = node_data.get("require_user_confirm", False)
            _GATE_ALIASES = {"gate-confirm": "gate_confirm"}
            resolved_type = _GATE_ALIASES.get(node_type, node_type)
            if resolved_type == "gate_confirm":
                require_confirm = True
            defer_automation = bool(require_confirm and node_ok_exec)
            if not defer_automation:
                await self._fire_story_on_node_done(nid, node_ok_exec)

            # ── Confirmation gate: wait for human confirmation ──
            if require_confirm and self._node_results[nid].get("ok", True):
                await self._wait_for_node_confirmation(
                    nid, node_type, node_label, node_data,
                )

            return self._node_results[nid]

        for level in levels:
            if self._cancel_requested:
                raise asyncio.CancelledError("workflow cancelled")
            # DB-based cancel check (multi-instance safe)
            try:
                # PR-E4 (SDK extraction §5 PR-E4): RuntimeWorkflowDao is now accessed via the
                # WorkflowRunRepository Protocol.  The legacy dao.mysql.runtime_workflow is
                # still used via the _LegacyWorkflowRunRepository fallback so runtime
                # behaviour is unchanged in Phase 0.  Phase 2 removes the fallback when
                # dao/ leaves the engine import surface.
                from vendor_runtime_sdk.runtime.protocols.workflow_run_repository import (
                    get_workflow_run_repository,
                )
                if await get_workflow_run_repository().is_cancel_requested(self._run_id):
                    self._cancel_requested = True
                    raise asyncio.CancelledError("workflow cancelled via DB")
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            # Per-node timeout: 5 minutes for LLM-heavy nodes
            _NODE_TIMEOUT = 300
            # Mark waiting nodes in this level
            for nid in level:
                if nid in self._nodes_by_id:
                    node = self._nodes_by_id[nid]
                    node_data = node.get("data") or {}
                    node_type = node_data.get("type") or node.get("type", "")
                    node_label = node_data.get("label") or node.get("label", nid)
                    if nid not in self._node_results:
                        self._node_results[nid] = {
                            "status": "waiting",
                            "node_type": node_type,
                            "label": node_label,
                        }
            await self._persist_node_results()

            tasks = [_run_node_with_status(nid) for nid in level if nid in self._nodes_by_id]
            await asyncio.gather(*tasks, return_exceptions=True)

            # ── Save WorkflowContext after each level ──
            await self._save_context()

    async def start(self) -> None:
        import time as _time
        self._telemetry_start = _time.time()
        # PR-E4 (SDK extraction §5 PR-E4): RuntimeWorkflowDao is now accessed via the
        # WorkflowRunRepository Protocol.  The legacy dao.mysql.runtime_workflow is
        # still used via the _LegacyWorkflowRunRepository fallback so runtime
        # behaviour is unchanged in Phase 0.  Phase 2 removes the fallback when
        # dao/ leaves the engine import surface.
        from vendor_runtime_sdk.runtime.protocols.workflow_run_repository import (
            get_workflow_run_repository,
        )

        repo = get_workflow_run_repository()

        # ── Pod claim ──
        pod_id = os.environ.get("POD_ID") or f"local-{os.getpid()}"
        claimed = await repo.claim_run(self._run_id, pod_id, self._workspace_id)
        if not claimed:
            logger.warning("Run %s already claimed by another pod, aborting", self._run_id)
            return

        # ── Heartbeat background task ──
        heartbeat_task: Optional[asyncio.Task] = None

        async def _heartbeat_loop():
            while True:
                await asyncio.sleep(60)
                try:
                    await repo.heartbeat(self._run_id, pod_id)
                except Exception as exc:
                    logger.debug("Heartbeat failed: %s", exc)

        _ACTIVE_EXECUTORS[self._run_id] = self
        try:
            heartbeat_task = asyncio.create_task(_heartbeat_loop())

            await repo.update_run(
                self._run_id,
                {
                    "status": "running",
                    "started_at": datetime.now(),
                },
            )

            # ── Sync node assignments from graph_data ──
            await self._sync_node_assignments()

            await self._execute()
            snap = self._runtime.snapshot() if self._runtime else None
            final_status = "completed" if not self._cancel_requested else "cancelled"
            await repo.update_run(
                self._run_id,
                {
                    "status": final_status,
                    "completed_at": datetime.now(),
                    "node_results": self._node_results,
                    "runtime_snapshot": snap,
                    "error": None,
                },
            )
            # Lark: workflow completed
            try:
                from services.sdlc_lark_notify import notify_workflow_completed
                asyncio.ensure_future(notify_workflow_completed(
                    run_id=self._run_id,
                    workflow_name=self._workflow.get("name", ""),
                    creator_id=self._workflow.get("variables", {}).get("creator_id", ""),
                    status=final_status,
                ))
            except Exception:
                pass
        except asyncio.CancelledError:
            await repo.update_run(
                self._run_id,
                {
                    "status": "cancelled",
                    "completed_at": datetime.now(),
                    "node_results": self._node_results,
                    "error": "cancelled",
                },
            )
            raise
        except Exception as e:
            logger.exception("WorkflowExecutor failed: %s", e)
            await repo.update_run(
                self._run_id,
                {
                    "status": "failed",
                    "completed_at": datetime.now(),
                    "node_results": self._node_results,
                    "error": str(e),
                },
            )
            # Lark: workflow failed
            try:
                from services.sdlc_lark_notify import notify_workflow_completed
                asyncio.ensure_future(notify_workflow_completed(
                    run_id=self._run_id,
                    workflow_name=self._workflow.get("name", ""),
                    creator_id=self._workflow.get("variables", {}).get("creator_id", ""),
                    status="failed",
                    error=str(e)[:500],
                ))
            except Exception:
                pass
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
            _ACTIVE_EXECUTORS.pop(self._run_id, None)
            # ── Record telemetry ──
            try:
                import time as _time
                from vendor_runtime_sdk.runtime.telemetry import TurnMetrics, get_recorder
                elapsed = int((_time.time() - (self._telemetry_start or _time.time())) * 1000)
                n_nodes = len(self._node_results)
                n_ok = sum(1 for r in self._node_results.values() if isinstance(r, dict) and r.get("ok"))
                n_llm = sum(1 for r in self._node_results.values() if isinstance(r, dict) and r.get("model"))
                recorder = get_recorder()
                recorder.record_turn(TurnMetrics(
                    first_token_ms=float(elapsed),
                    tool_calls=n_nodes,
                    tool_successes=n_ok,
                    llm_calls=max(n_llm, 1),
                    llm_successes=n_llm,
                    request_success=not self._cancel_requested and not any(
                        isinstance(r, dict) and not r.get("ok") for r in self._node_results.values()
                    ),
                ))
            except Exception:
                pass

    @classmethod
    async def cancel(cls, run_id: str) -> bool:
        # PR-E4 (SDK extraction §5 PR-E4): RuntimeWorkflowDao is now accessed via the
        # WorkflowRunRepository Protocol.  The legacy dao.mysql.runtime_workflow is
        # still used via the _LegacyWorkflowRunRepository fallback so runtime
        # behaviour is unchanged in Phase 0.  Phase 2 removes the fallback when
        # dao/ leaves the engine import surface.
        from vendor_runtime_sdk.runtime.protocols.workflow_run_repository import (
            get_workflow_run_repository,
        )

        ex = _ACTIVE_EXECUTORS.get(run_id)
        if ex:
            ex._cancel_requested = True
            if ex._runtime:
                ex._runtime.request_interrupt("workflow_cancel")
        repo = get_workflow_run_repository()
        run = await repo.get_run(run_id)
        if run and run.get("status") == "running":
            await repo.update_run(
                run_id,
                {"status": "cancelling", "error": "cancellation requested"},
            )
        return ex is not None

logger = logging.getLogger(__name__)
