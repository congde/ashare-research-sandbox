# -*- coding: utf-8 -*-
"""
Exceptions raised by the runtime policy / HITL subsystem.

Kept in a standalone module so that both ``agent/`` and ``runtime/``
layers can import without circular-dependency risk.
"""

from __future__ import annotations


class HITLRequiredError(Exception):
    """
    Raised when PolicyEngine returns an ``ask`` action for a tool call,
    signalling that the operation requires human approval before proceeding.

    Attributes
    ----------
    tool_name : str
        The tool that was blocked.
    reason : str
        Human-readable explanation from PermissionResolver.
    rule_id : str | None
        ID of the PolicyRule that triggered the ask action.
    tool_args : dict | None
        The resolved tool arguments at the time of the block.  Surfaced to the
        frontend so the reviewer can see exactly what was about to run.
    approval_id : str | None
        Stable identifier the frontend echoes back on ``/hitl/decide`` so
        the backend can correlate the decision with the right pending
        gate (HITL Redesign).
    risk_level : str
        ``low | medium | high`` — drives ApprovalCard visual badge.
    editable_args : tuple[str, ...]
        Subset of arg keys the operator may inline-edit before approving.
    tool_call_id : str | None
        OpenAI tool_call_id for the paused call — pairs with the
        TOOL_CALL/TOOL_RESULT envelopes the chat UI renders so the
        approval card sits next to the right tool row.
    """

    def __init__(
        self,
        tool_name: str,
        reason: str,
        rule_id: str | None = None,
        tool_args: dict | None = None,
        approval_id: str | None = None,
        risk_level: str = "low",
        editable_args: tuple = (),
        tool_call_id: str | None = None,
    ) -> None:
        super().__init__(f"Tool '{tool_name}' requires human approval: {reason}")
        self.tool_name = tool_name
        self.reason = reason
        self.rule_id = rule_id
        self.tool_args = tool_args or {}
        self.approval_id = approval_id
        self.risk_level = risk_level or "low"
        self.editable_args = tuple(editable_args or ())
        self.tool_call_id = tool_call_id
