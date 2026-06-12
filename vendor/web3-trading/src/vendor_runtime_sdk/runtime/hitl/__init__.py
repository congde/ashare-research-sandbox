# -*- coding: utf-8 -*-
"""
runtime.hitl — HITL prompter implementations.

Implements the ``PermissionPrompter`` Protocol from
``runtime.protocols.permission_prompter`` for the two runtime
contexts:

* ``WebSseHitlPrompter`` (Sprint 0 PR-D) — defers the decision off-
  process via SSE + ``POST /hitl/decide``. Used by HTTP request path.
* ``TerminalPrompter`` (Sprint 2 PR-I) — wraps the in-process
  ``approval_callback`` shape already used by CLI / TUI. Synchronous
  reply, no off-process detour.

Both implementations satisfy a single Protocol contract so
``ConversationRuntime`` can inject either without conditionals at
call sites.
"""

from __future__ import annotations

from vendor_runtime_sdk.runtime.hitl.dispatch import (
    ApprovalCallback,
    build_envelope_from_hitl_exception,
    build_request_from_envelope,
    resolve_hitl_decision,
)
from vendor_runtime_sdk.runtime.hitl.terminal_prompter import (
    RichApprovalCallback,
    TerminalPrompter,
)
from vendor_runtime_sdk.runtime.hitl.web_sse_prompter import WebSseHitlPrompter

__all__ = [
    "ApprovalCallback",
    "RichApprovalCallback",
    "TerminalPrompter",
    "WebSseHitlPrompter",
    "build_envelope_from_hitl_exception",
    "build_request_from_envelope",
    "resolve_hitl_decision",
]
