# -*- coding: utf-8 -*-
"""Shared rules: workflow node subtasks vs confirmation gate."""

from __future__ import annotations

from typing import Any, Dict, Optional


def subtasks_done_gate_enabled(node_data: Optional[Dict[str, Any]]) -> bool:
    """When True (default), node owner confirm requires all run-scoped subtasks terminal.

    Set ``require_subtasks_done_before_confirm: false`` on node data to skip.
    """
    if not node_data:
        return True
    if node_data.get("require_subtasks_done_before_confirm") is False:
        return False
    return True
