# -*- coding: utf-8 -*-
"""PR-F2 — :class:`RepeatedValidationFailureHook`.

Per :doc:`docs/CoderAgent-多文件任务完成率根因修复方案` §3.F2.

R5 root cause: when the LLM emits the same broken tool_call shape (most
commonly ``write_file`` missing the ``content`` field) repeatedly, the
legacy :func:`agent.tools.loop._should_abort_on_repeated_validation`
gate fast-aborts after 3 strikes.  V1/V2/V3 baselines showed this
fast-fail produces no recovery surface — the milestone is lost wholesale.

F2 replaces fast-fail with a **3-stage remediation ladder**:

* streak == 2 → ``inject_hint``: structured hint message offered to
  the next LLM turn ("your write_file is dropping content; try
  patch_apply with a small focused diff or edit_file with anchored
  string-replace").
* streak == 3 → ``restrict_tools``: ``write_file`` is filtered out of
  the LLM-visible tool surface for the remainder of the milestone;
  only ``patch_apply`` / ``edit_file`` remain for write-class
  operations.
* streak ≥ 5 → ``abort``: the LLM has had two structured chances to
  recover; the streak is genuinely stuck and the milestone is doomed.

Streak 4 is a deliberate gap — give the LLM one extra turn under the
restricted tool surface before escalating.

Borrowed from claw-code's ``HookEvent::PostToolUseFailure`` design
(rust/crates/runtime/src/hooks.rs): the streak state lives inside the
hook, not the agent loop, so the hook can be unit-tested as a pure
function.

Toggle: :data:`coder_validation_strategy_switch` (default ON; rollback
via env ``RUNTIME__MODULES__CODER_VALIDATION_STRATEGY_SWITCH__ENABLED=false``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import FrozenSet, Literal, Optional

from vendor_runtime_sdk.runtime.hooks_core import PostHookResult, PostToolUseFailureHook

logger = logging.getLogger(__name__)


# Tools that remain available after ``restrict_tools`` fires. The LLM is
# expected to fall back to these for write-class operations.
_RESTRICT_TOOLS_WHITELIST_BASE: FrozenSet[str] = frozenset(
    {
        # Read-class — always safe to keep
        "read_file",
        "list_directory",
        "glob",
        "code_search_grep",
        # Git read-class
        "git_status",
        "git_diff",
        "git_log",
        # Coordination
        "todo_write",
        "spawn_sibling_milestone",
        "enter_decomposed_mode",
        "enter_plan_mode",
        "exit_plan_mode",
        # Bash (required for tests / linting; LLM can still mutate via shell
        # but doing so re-enters the same R1 trap and the hook will fire
        # again on the next streak)
        "bash_exec",
        # Write-class remediation tools — these are the recommended
        # alternatives the hint nudges the LLM to use.
        "patch_apply",
        "edit_file",
    }
)


_HINT_TEMPLATE = (
    "Notice: your {tool_name} calls are repeatedly failing validation "
    "with the same error. This is a known LLM-serialisation issue when "
    "the tool_use payload carries a large 'content' field — the "
    "transformer attention/cache budget drops the trailing portion. "
    "For your next attempt, try one of:\n"
    "  (a) patch_apply with a small focused unified diff, or\n"
    "  (b) edit_file (anchored old_string → new_string), or\n"
    "  (c) write_file with content < 100 lines (split the file into "
    "a short skeleton plus subsequent patch_apply calls).\n"
    "Re-issuing the same {tool_name} payload will keep failing."
)


@dataclass(frozen=True)
class ValidationDecision:
    """Pure decision emitted by :meth:`RepeatedValidationFailureHook.decide`.

    Consumers (AgentLoop integration) read ``action`` and pick up
    whichever payload field corresponds to it. Unused fields stay
    ``None`` so attribute access is always safe.
    """

    streak: int
    action: Literal["log_only", "inject_hint", "restrict_tools", "abort"]
    hint: Optional[str] = None
    tool_whitelist: Optional[FrozenSet[str]] = None
    abort_reason: Optional[str] = None


class RepeatedValidationFailureHook(PostToolUseFailureHook):
    """Subscribes to ``PostToolUseFailure`` events and emits the F2
    remediation decision.

    The hook is intentionally stateless across calls — the AgentLoop
    already tracks streak state on its own instance, and we surface
    the decision through ``decide(streak=...)``. This keeps the hook
    a pure function for unit tests and avoids a global
    ``module-level`` counter that would leak across milestones.
    """

    INJECT_HINT_AT: int = 2
    RESTRICT_TOOLS_AT: int = 3
    ABORT_AT: int = 5

    @classmethod
    def restrict_tools_whitelist(cls) -> FrozenSet[str]:
        """Public accessor — useful for tests + dashboard surfaces."""
        return _RESTRICT_TOOLS_WHITELIST_BASE

    def decide(
        self,
        *,
        streak: int,
        tool_name: str,
        signature: str,
    ) -> ValidationDecision:
        """Pure function: streak count + tool name → decision."""
        if streak <= 1:
            return ValidationDecision(streak=streak, action="log_only")
        if streak == self.INJECT_HINT_AT:
            return ValidationDecision(
                streak=streak,
                action="inject_hint",
                hint=_HINT_TEMPLATE.format(tool_name=tool_name or "the failing tool"),
            )
        if streak == self.RESTRICT_TOOLS_AT:
            return ValidationDecision(
                streak=streak,
                action="restrict_tools",
                tool_whitelist=_RESTRICT_TOOLS_WHITELIST_BASE,
            )
        if streak < self.ABORT_AT:
            # Gap turn — the restrict_tools effect from the previous
            # iteration is still in force; give the LLM one more chance
            # under the new tool surface before escalating.
            return ValidationDecision(streak=streak, action="log_only")
        return ValidationDecision(
            streak=streak,
            action="abort",
            abort_reason=(
                f"repeated_validation_error: {streak} consecutive identical "
                f"validation failures for {tool_name!r} "
                f"(signature={signature[:120]!r}). Aborting after F2 "
                f"remediation ladder exhausted."
            ),
        )

    # ── PostToolUseFailureHook protocol ────────────────────────────────

    async def post_failure(
        self, tool_name: str, error: Exception
    ) -> PostHookResult:
        """Default integration with the existing :class:`HookRunner`.

        The protocol does not surface the streak count — callers that
        want F2's remediation ladder must use
        :meth:`post_failure_with_streak` instead. This default returns
        an empty result so the hook is harmless when wired through the
        generic runner without the AgentLoop streak feed.
        """
        return PostHookResult()

    async def post_failure_with_streak(
        self,
        *,
        tool_name: str,
        error: Exception,
        streak: int,
        signature: str,
    ) -> PostHookResult:
        """Streak-aware variant called from
        :class:`agent.tools.loop.AgentLoop` directly.

        Returns a :class:`PostHookResult` whose ``additional_messages``
        carries the F2 hint (when ``inject_hint`` fires) so the existing
        hook merge path forwards it. The other actions
        (``restrict_tools`` / ``abort``) are surfaced through the
        ``decide`` API so the loop can act on structured fields rather
        than parsing string messages.
        """
        decision = self.decide(streak=streak, tool_name=tool_name, signature=signature)
        result = PostHookResult()
        if decision.action == "inject_hint" and decision.hint:
            result.additional_messages.append(decision.hint)
        return result


def emit_decision_span(decision: ValidationDecision) -> None:
    """Fire-and-forget telemetry for an actionable F2 decision.

    Emits one of ``F2_HINT_INJECTED`` / ``F2_TOOLS_RESTRICTED`` /
    ``F2_ABORTED`` and is a no-op for ``log_only``. Fail-soft — any
    error is swallowed so a buggy telemetry sink can't break the
    AgentLoop's remediation flow.

    Designed for the AgentLoop integration site: call this whenever
    a non-``log_only`` decision is acted upon.
    """
    if decision.action == "log_only":
        return
    span_map = {
        "inject_hint": "F2_HINT_INJECTED",
        "restrict_tools": "F2_TOOLS_RESTRICTED",
        "abort": "F2_ABORTED",
    }
    span_attr = span_map.get(decision.action)
    if span_attr is None:
        return
    try:
        from vendor_runtime_sdk.runtime.telemetry import SpanEvent, SpanType, get_recorder

        span_type = getattr(SpanType, span_attr)
        metadata: dict = {
            "streak": decision.streak,
            "tool": _tool_from_signature(decision),
        }
        if decision.tool_whitelist is not None:
            metadata["whitelist_size"] = len(decision.tool_whitelist)
        if decision.abort_reason:
            metadata["reason"] = decision.abort_reason
        recorder = get_recorder()
        recorder.record_span_event(
            SpanEvent(span_type=span_type, metadata=metadata)
        )
        # SLI counter bump alongside the span.
        if decision.action == "inject_hint":
            recorder.inc_f2_hint_injected()
        elif decision.action == "restrict_tools":
            recorder.inc_f2_tools_restricted()
        elif decision.action == "abort":
            recorder.inc_f2_aborted()
    except Exception:  # pragma: no cover — defensive
        pass


def _tool_from_signature(decision: ValidationDecision) -> str:
    """Extract the tool name from a decision.

    The hint string starts with ``Notice: your <tool_name> calls`` so
    we can pull the tool name from there when present. Otherwise fall
    back to ``<unknown>``.
    """
    if decision.hint:
        # "Notice: your write_file calls are repeatedly failing..."
        import re

        m = re.match(r"Notice: your (\S+) calls", decision.hint)
        if m:
            return m.group(1)
    return "<unknown>"


__all__ = [
    "RepeatedValidationFailureHook",
    "ValidationDecision",
    "emit_decision_span",
]
