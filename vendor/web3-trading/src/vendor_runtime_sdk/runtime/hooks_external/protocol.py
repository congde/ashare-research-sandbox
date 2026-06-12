"""S2.1 · External-hook wire protocol.

JSON schema flowing over stdin / stdout between the agent process
and each hook subprocess.  Strict validation on decode — unknown
top-level keys are rejected so the schema can evolve safely
without silently ignoring caller intent.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Final, Optional

# ── Event names (stable wire constants — never rename) ──────────────────────

EVENT_PRE_TOOL_USE: Final[str] = "PreToolUse"
EVENT_POST_TOOL_USE: Final[str] = "PostToolUse"
EVENT_POST_TOOL_USE_FAILURE: Final[str] = "PostToolUseFailure"

_VALID_EVENTS: Final[frozenset[str]] = frozenset({
    EVENT_PRE_TOOL_USE,
    EVENT_POST_TOOL_USE,
    EVENT_POST_TOOL_USE_FAILURE,
})

_VALID_PERMISSION_OVERRIDES: Final[frozenset[str]] = frozenset({
    "allow", "deny", "ask",
})

# ── Output size caps (operator safety) ──────────────────────────────────────

_MAX_FEEDBACK_CHARS: Final[int] = 16 * 1024
"""``additional_feedback`` is injected into the LLM context — a
runaway hook spewing megabytes would blow the context window."""

_MAX_REASON_CHARS: Final[int] = 4 * 1024
"""``reason`` lands in audit logs.  Keep it readable."""

_MAX_FINAL_MESSAGE_CHARS: Final[int] = 16 * 1024


# ── Data classes ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HookInput:
    """Payload sent to the hook subprocess on stdin."""

    event: str
    tool_name: str
    input: Dict[str, Any] = field(default_factory=dict)
    # PostToolUse only:
    result: Optional[Dict[str, Any]] = None
    # PostToolUseFailure only:
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if self.event not in _VALID_EVENTS:
            raise ValueError(
                f"unknown hook event: {self.event!r} "
                f"(valid: {sorted(_VALID_EVENTS)})"
            )


@dataclass(frozen=True)
class HookOutput:
    """Hook subprocess response decoded from stdout JSON.

    All fields optional — an empty ``{}`` decodes as a clean no-op.
    """

    # PreToolUse only:
    updated_input: Optional[Dict[str, Any]] = None
    permission_override: Optional[str] = None  # allow / deny / ask
    reason: Optional[str] = None

    # PostToolUse only:
    additional_feedback: Optional[str] = None

    # PostToolUseFailure only:
    retry: bool = False
    final_message: Optional[str] = None


# ── Encode (agent → stdin) ──────────────────────────────────────────────────


def encode_input(payload: HookInput) -> str:
    """Serialize ``payload`` as a single JSON line.  Drops fields
    that are ``None`` so the wire format stays compact and the hook
    sees only the keys relevant to its event type."""
    body: Dict[str, Any] = {
        "event": payload.event,
        "tool_name": payload.tool_name,
        "input": dict(payload.input or {}),
    }
    if payload.result is not None:
        body["result"] = payload.result
    if payload.error is not None:
        body["error"] = payload.error
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


# ── Decode (stdout → HookOutput) ────────────────────────────────────────────

_VALID_OUTPUT_KEYS: Final[frozenset[str]] = frozenset({
    "updated_input",
    "permission_override",
    "reason",
    "additional_feedback",
    "retry",
    "final_message",
})


def decode_output(stdout: str) -> HookOutput:
    """Parse a hook subprocess's stdout into a :class:`HookOutput`.

    Strict: unknown top-level keys raise ``ValueError`` so the
    schema can evolve safely without silently ignoring caller intent.
    Type validation per field — a hook accidentally sending an int
    where a string is expected would otherwise crash later in the
    agent loop with an opaque ``TypeError``.
    """
    raw = (stdout or "").strip()
    if not raw:
        return HookOutput()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"hook output is not valid json: {exc}") from exc
    if not isinstance(body, dict):
        raise ValueError(
            f"hook output must be a JSON object, got {type(body).__name__}"
        )

    unknown = set(body.keys()) - _VALID_OUTPUT_KEYS
    if unknown:
        raise ValueError(
            f"unknown hook output keys: {sorted(unknown)} "
            f"(valid: {sorted(_VALID_OUTPUT_KEYS)})"
        )

    updated_input = body.get("updated_input")
    if updated_input is not None and not isinstance(updated_input, dict):
        raise ValueError(
            f"updated_input must be a JSON object, got "
            f"{type(updated_input).__name__}"
        )

    permission_override = body.get("permission_override")
    if permission_override is not None:
        if not isinstance(permission_override, str):
            raise ValueError(
                "permission_override must be a string"
            )
        if permission_override not in _VALID_PERMISSION_OVERRIDES:
            raise ValueError(
                f"permission_override must be one of "
                f"{sorted(_VALID_PERMISSION_OVERRIDES)}, "
                f"got {permission_override!r}"
            )

    reason = body.get("reason")
    if reason is not None:
        if not isinstance(reason, str):
            raise ValueError("reason must be a string")
        if len(reason) > _MAX_REASON_CHARS:
            raise ValueError(
                f"reason too long ({len(reason)} > {_MAX_REASON_CHARS})"
            )

    additional_feedback = body.get("additional_feedback")
    if additional_feedback is not None:
        if not isinstance(additional_feedback, str):
            raise ValueError("additional_feedback must be a string")
        if len(additional_feedback) > _MAX_FEEDBACK_CHARS:
            raise ValueError(
                f"additional_feedback too long "
                f"({len(additional_feedback)} > {_MAX_FEEDBACK_CHARS})"
            )

    retry = body.get("retry", False)
    if not isinstance(retry, bool):
        raise ValueError("retry must be a boolean")

    final_message = body.get("final_message")
    if final_message is not None:
        if not isinstance(final_message, str):
            raise ValueError("final_message must be a string")
        if len(final_message) > _MAX_FINAL_MESSAGE_CHARS:
            raise ValueError(
                f"final_message too long "
                f"({len(final_message)} > {_MAX_FINAL_MESSAGE_CHARS})"
            )

    return HookOutput(
        updated_input=updated_input,
        permission_override=permission_override,
        reason=reason,
        additional_feedback=additional_feedback,
        retry=retry,
        final_message=final_message,
    )
