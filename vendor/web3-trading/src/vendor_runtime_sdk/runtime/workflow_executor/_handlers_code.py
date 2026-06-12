# -*- coding: utf-8 -*-
"""
Code node handlers — code execution, wait, notify, iteration

Auto-extracted from runtime/workflow_executor.py during refactoring.
"""

from __future__ import annotations

import asyncio
import logging
import json
from typing import Any, Dict, List, Optional

class HandlersCodeMixin:
    """Code node handlers — code execution, wait, notify, iteration"""

    @staticmethod
    def _validate_code_ast(code: str) -> Optional[str]:
        """AST pre-validation for code expressions. Returns error message or None."""
        import ast

        _MAX_AST_NODES = 50
        _MAX_AST_DEPTH = 10

        try:
            tree = ast.parse(code, mode="eval")
        except SyntaxError as e:
            return f"syntax error: {e}"

        node_count = 0
        for node in ast.walk(tree):
            node_count += 1
            if node_count > _MAX_AST_NODES:
                return "expression too complex (>50 AST nodes)"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                return "import statements are not allowed"
            if isinstance(node, ast.Attribute) and isinstance(node.attr, str) and node.attr.startswith("__"):
                return f"dunder attribute access not allowed: {node.attr}"

        def _depth(n: ast.AST, d: int = 0) -> int:
            if d > _MAX_AST_DEPTH:
                return d
            return max((d, *((_depth(c, d + 1)) for c in ast.iter_child_nodes(n))), default=d)

        if _depth(tree) > _MAX_AST_DEPTH:
            return "expression too deeply nested (>10 levels)"
        return None

    async def _exec_code(self, node: Dict) -> Dict[str, Any]:
        """Code execution node — evaluates a Python expression with access to workflow variables."""
        data = node.get("data") or {}
        code = data.get("code") or data.get("expression") or ""
        out_var = data.get("output_var") or "code_result"

        if not code:
            return {"ok": False, "error": "code node requires 'code' field"}

        # AST pre-validation
        ast_err = self._validate_code_ast(code)
        if ast_err:
            return {"ok": False, "error": f"code validation failed: {ast_err}"}

        try:
            import math as _math
            import json as _json
            _ctx = {
                **{"true": True, "false": False, "null": None},
                **{k: v for k, v in self._variables.items() if not k.startswith("_")},
                "math": _math,
                "json": _json,
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "list": list,
                "dict": dict,
                "len": len,
                "range": range,
                "sum": sum,
                "min": min,
                "max": max,
                "abs": abs,
                "round": round,
            }
            result = eval(code, {"__builtins__": {}}, _ctx)  # nosec B102
            self._variables[out_var] = result
            return {"ok": True, "output_var": out_var, "value": result}
        except Exception as e:
            logger.exception("WorkflowExecutor._exec_code failed: %s", e)
            return {"ok": False, "error": f"code execution error: {e}"}

    async def _exec_wait(self, node: Dict) -> Dict[str, Any]:
        """Wait/delay node — pauses execution for specified seconds."""
        data = node.get("data") or {}
        delay_seconds = float(data.get("delay_seconds") or data.get("seconds") or 0)
        delay_seconds = min(max(delay_seconds, 0), 86400)  # cap at 1 day
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        return {"ok": True, "delayed_seconds": delay_seconds}

    async def _exec_notify(self, node: Dict) -> Dict[str, Any]:
        """Notify node — sends a notification via lark_send_message or logs."""
        data = node.get("data") or {}
        channel = data.get("channel", "lark")  # lark | log
        title = data.get("title", "工作流通知")
        message_text = data.get("message") or data.get("text", "")

        if channel == "lark":
            # Delegate to lark_send_message tool
            result = await self._exec_tool_call({
                "id": node.get("id"),
                "data": {
                    "tool_name": "lark_send_message",
                    "tool_input": {
                        "receive_id": data.get("receive_id") or "${lark_chat_id}",
                        "receive_id_type": data.get("receive_id_type") or "chat_id",
                        "text": f"**{title}**\n{message_text}",
                    },
                },
            })
            return result

        # Fallback: log only
        logger.info("Workflow notification [%s]: %s", title, message_text)
        return {"ok": True, "channel": channel, "title": title, "message": message_text}

    async def _exec_iteration(self, node: Dict) -> Dict[str, Any]:
        """Iteration node — executes a sub-graph repeatedly over an iterable."""
        data = node.get("data") or {}
        items_key = data.get("items_var") or data.get("items")  # variable name containing iterable
        body_node_id = data.get("body_node_id")  # node ID of the loop body
        max_iterations = int(data.get("max_iterations") or data.get("max_loops") or 100)
        out_var = data.get("output_var") or "iteration_results"

        if not items_key:
            return {"ok": False, "error": "iteration node requires 'items_var' (variable name)"}

        items = self._variables.get(items_key)
        if not isinstance(items, (list, tuple, str)):
            # Try to treat as JSON
            try:
                items = json.loads(str(items))
            except Exception:
                return {"ok": False, "error": f"items_var '{items_key}' is not iterable: {items}"}

        results = []
        for i, item in enumerate(items):
            if i >= max_iterations:
                break
            if self._cancel_requested:
                raise asyncio.CancelledError("workflow cancelled")
            self._variables["loop_item"] = item
            self._variables["loop_index"] = i
            if body_node_id:
                body_node = self._nodes_by_id.get(str(body_node_id))
                if body_node:
                    r = await self._execute_node(body_node)
                    results.append(r)
        self._variables[out_var] = results
        return {"ok": True, "iterations": len(results), "output_var": out_var}


logger = logging.getLogger(__name__)
