# -*- coding: utf-8 -*-
"""
Basic node handlers — tool_call, llm_call, condition, approval, gate, transform, policy_gate, memory_op

Auto-extracted from runtime/workflow_executor.py during refactoring.
"""

from __future__ import annotations

import json
from string import Template
from typing import Any, Dict, List, Optional

class HandlersBasicMixin:
    """Basic node handlers — tool_call, llm_call, condition, approval, gate, transform, policy_gate, memory_op"""

    async def _exec_tool_call(self, node: Dict) -> Dict[str, Any]:
        from vendor_runtime_sdk.agent.tools.registry import default_registry

        data = node.get("data") or {}
        name = data.get("tool_name") or ""
        args = data.get("tool_input")
        if args is None:
            args = data.get("arguments") or {}
        if not name:
            return {"ok": False, "error": "missing tool_name"}
        result = await default_registry.execute(name, args if isinstance(args, dict) else {})
        return {
            "ok": result.success,
            "content": result.content,
            "error": result.error,
            "metadata": result.metadata,
        }

    async def _exec_llm_call(self, node: Dict) -> Dict[str, Any]:
        from vendor_runtime_sdk.llm.base import create_llm

        data = node.get("data") or {}
        prompt = data.get("prompt") or ""
        system_prompt = data.get("system_prompt") or ""
        model_override = data.get("model")
        temperature = float(data.get("temperature", 0.2))

        # ── Inject upstream context into prompt ──
        node_id = node.get("id", "")
        upstream_ctx = self._ctx.format_upstream_context(current_node_id=node_id)
        if upstream_ctx:
            prompt = (
                f"## Context from Previous Steps\n\n{upstream_ctx}\n\n"
                f"---\n\n{prompt}"
            )

        messages: list = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        llm, model = create_llm(model_name=model_override)
        resp = await llm.chat.completions.create(
            model=model_override or model,
            messages=messages,
            temperature=temperature,
        )
        text = ""
        if resp.choices:
            text = (resp.choices[0].message.content or "").strip()
        return {"ok": True, "text": text, "content": text, "model": model_override or model}

    async def _exec_condition(self, node: Dict) -> Dict[str, Any]:
        data = node.get("data") or {}
        expr = str(data.get("expression", "true")).strip()

        # ── Try WorkflowContext variable resolution first ──
        resolved = self._ctx.resolve(expr)
        if resolved is not None and resolved != expr:
            # Expression was a variable reference that resolved
            truthy = bool(resolved)
        else:
            # Fallback to simple evaluation
            expr_lower = expr.lower()
            truthy = expr_lower in ("1", "true", "yes", "on")
            if not truthy and expr_lower not in ("0", "false", "no", "off"):
                # Try resolve against variables / upstream outputs
                truthy = bool(self._variables.get(expr))
                if not truthy:
                    # Check upstream output status
                    up = self._ctx.upstream_outputs.get(expr)
                    if up:
                        truthy = up.status == "success"

        chosen = data.get("true_target") if truthy else data.get("false_target")
        return {
            "ok": True,
            "branch": "true" if truthy else "false",
            "next_target": chosen,
        }

    async def _exec_approval(self, node: Dict) -> Dict[str, Any]:
        data = node.get("data") or {}
        return {
            "ok": True,
            "status": "pending",
            "approver_role": data.get("approver_role"),
            "timeout_hours": data.get("timeout_hours"),
            "message": "approval workflow not fully wired; treated as pending",
        }

    async def _exec_gate_confirm(self, node: Dict) -> Dict[str, Any]:
        """Gate-confirm node — always succeeds; the confirmation gate logic
        is handled in _execute() via _wait_for_node_confirmation() after
        this node type completes.

        The node data should include:
          - assignee_member_ids: list of member IDs who can confirm
          - confirm_policy: { allowed_actor: "assignees_only" | "assignees_or_workspace_admin" }
          - due_at: optional deadline for confirmation

        Because the gate node itself is a no-op (always ok), the actual
        blocking/waiting is done by the _execute() method checking
        require_user_confirm=true on this node.
        """
        data = node.get("data") or {}
        return {
            "ok": True,
            "status": "waiting_confirm",
            "node_type": "gate_confirm",
            "assignee_member_ids": data.get("assignee_member_ids", []),
            "confirm_policy": data.get("confirm_policy", {"allowed_actor": "assignees_only"}),
            "message": "Gate confirm node executed; waiting for human confirmation",
        }

    async def _exec_transform(self, node: Dict) -> Dict[str, Any]:
        data = node.get("data") or {}
        template_str = data.get("template") or ""
        out_var = data.get("output_var") or "last_output"
        try:
            tpl = Template(template_str)
            mapping = {**self._variables, **{"results": json.dumps(self._node_results, ensure_ascii=False)}}
            rendered = tpl.safe_substitute(mapping)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        self._variables[out_var] = rendered
        return {"ok": True, "output_var": out_var, "value": rendered}

    async def _exec_policy_gate(self, node: Dict) -> Dict[str, Any]:
        from vendor_runtime_sdk.runtime.policy_engine import PolicyEngine, PolicyRule, PolicyAction, ActionType

        data = node.get("data") or {}
        raw_rules = data.get("policy_rules") or []
        rules: List[PolicyRule] = []
        for i, r in enumerate(raw_rules):
            if not isinstance(r, dict):
                continue
            chain: List[PolicyAction] = []
            for a in r.get("action_chain") or []:
                if not isinstance(a, dict):
                    continue
                try:
                    at = ActionType(str(a.get("type", "allow")).lower())
                except ValueError:
                    at = ActionType.ALLOW
                chain.append(
                    PolicyAction(
                        type=at,
                        params=dict(a.get("params") or {}),
                        reason=str(a.get("reason", "")),
                    )
                )
            rules.append(
                PolicyRule(
                    rule_id=str(r.get("rule_id", f"r{i}")),
                    priority=int(r.get("priority", 0)),
                    description=str(r.get("description", "")),
                    condition=str(r.get("condition", "true")),
                    action_chain=chain,
                    enabled=bool(r.get("enabled", True)),
                )
            )
        engine = PolicyEngine(rules=rules)
        ctx = {"vars": self._variables, "results": self._node_results, "workflow_id": self._workflow.get("id")}
        actions = engine.evaluate(ctx)
        denied = any(getattr(a, "type", None) == ActionType.DENY for a in actions)
        return {"ok": not denied, "actions": [str(a.type) for a in actions], "denied": denied}

    async def _exec_memory_op(self, node: Dict) -> Dict[str, Any]:
        data = node.get("data") or {}
        op = (data.get("operation") or "retrieve").lower()
        key = data.get("key") or ""
        if op == "store":
            self._memory_kv[key] = str(data.get("value", ""))
            return {"ok": True, "operation": "store", "key": key}
        if op == "retrieve":
            return {"ok": True, "operation": "retrieve", "key": key, "value": self._memory_kv.get(key, "")}
        if op == "search":
            q = str(data.get("query") or "").lower()
            hits = [k for k, v in self._memory_kv.items() if q in k.lower() or q in v.lower()]
            return {"ok": True, "operation": "search", "hits": hits}
        return {"ok": False, "error": f"unknown memory operation: {op}"}

