# -*- coding: utf-8 -*-
"""
HITL Resume — re-enter a paused agent's tool execution after the
operator decides on the gate.

When the agent loop yields ``REQUIRES_APPROVAL`` it suspends. The
frontend presents the operator with the ApprovalCard; the operator
clicks Allow/Reject/Cancel + chooses a scope. ``/hitl/decide`` posts
the verdict; this module then:

  1. **approve** — execute the gated tool with the (optionally edited)
     arguments, push a ``TOOL_CALL`` + ``TOOL_RESULT`` envelope onto
     the SSE stream so the chat UI shows the tool ran inline, and
     record the decision per scope so subsequent identical calls
     short-circuit.
  2. **reject** — push a ``TOOL_RESULT`` envelope with ``success=False``
     reflecting the operator's rejection so the agent can read the
     denial as a normal tool failure, then clear pending state.
  3. **cancel** — same as reject but additionally writes
     ``cancel_requested_at`` so any still-running runtime sees the
     stop on its next event-yield boundary.

The "true ReAct continuation" — re-running ``AgentLoop.run()`` against
the updated message buffer so the LLM gets to react to the tool result
— is intentionally NOT implemented in v1. The original SSE connection
holds open via the existing keepalive (see ``api/chat/local_query``);
the agent's next user-turn picks up the tool result from MongoDB
transcript history and continues from there. Documented limitation:
right after approve, the agent surfaces the tool result and waits for
the user; this matches Claude Code's ``/allow`` UX where the user can
see what happened before deciding to continue.
"""

from __future__ import annotations

import json as _json_top
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)


# ── Continuation prompt building ────────────────────────────────────────


# Markers we inject into the continuation query. Listed here so the
# stripper picks up everything we ever appended even if the wording
# evolves — the bracketed prefix is the stable contract.
_CONTINUATION_MARKERS = ("[系统继续提示]", "[已完成]")

# Keys whose values are omitted from HITL continuation prompts — embedding
# multi-KiB write_file ``content`` in qa.query triggered risk-control
# false positives (category=恶意攻击) and blew the LLM context budget
# (3× APITimeoutError on resume).  Full args are still passed to the
# inline executor; only the operator-facing prompt is redacted.
_LARGE_ARG_KEYS = frozenset({
    "content",
    "new_content",
    "new_string",
    "old_string",
    "patch",
    "diff",
    "edits",
})


@dataclass(frozen=True)
class ApprovedToolFact:
    """What ``_handle_approve`` did on behalf of the operator.

    Two ``mode`` regimes — the prompt text must tell the LLM very
    different things in each:

    ``executed`` (V1 path, ``delegated=False``)
        ``_handle_approve`` ran the tool inline via the resume registry
        and got a real result. The LLM should NOT re-issue the call —
        the work is done. The [已完成] block reports the outcome
        (success/error) so the LLM can decide the next step.

    ``delegated`` (V2 path, ``delegated=True``)
        ``_handle_approve`` did NOT execute the tool — it only recorded
        a session-scope decision_memory entry and dispatched a fresh
        agent. The LLM MUST re-issue the same call so the PolicyResolver
        short-circuits via the recorded decision and actually executes
        it. The [已完成] block in this mode reports "gate cleared, now
        please retry the call to run it"; claiming success would make
        the LLM skip the retry and the work never gets done.

    Without this distinction the V2 path was broken (observed in
    dogfood): the prompt said "bash_exec succeeded" but the tool never
    ran — pip install never happened, the service never started, and
    the LLM jumped straight to "执行完成" with no real progress.
    """

    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    content: str = ""
    error: Optional[str] = None
    delegated: bool = False


def _strip_continuation_markers(
    qa_query: Optional[str],
    sess_doc: Optional[Mapping[str, Any]] = None,
) -> str:
    """Recover the bare original user phrase from a possibly-enriched
    ``qa.query`` value.

    V2 continuations accumulate over a chained-HITL session:

      original ─┐
                "<user phrase>\\n\\n{frontend_meta_json}"
                "  + \\n\\n[系统继续提示] ..."
                "  + \\n\\n[已完成] tool=write_file ..."
                "  + \\n\\n[系统继续提示] ..."   ← compounds each resume
                "  + \\n\\n[已完成] tool=bash_exec ..."

    The stripper walks LEFT-to-RIGHT, slicing off everything from the
    first occurrence of any marker (system prompt or completed-tool
    note) and the frontend's metadata-JSON suffix. Falls back to
    ``session.title`` (similarly stripped) when ``qa.query`` is empty
    or carries the resume placeholder; final fallback is a non-empty
    sentinel phrase so the LLM never receives a bare prompt.
    """
    q = (qa_query or "").strip()
    for marker in _CONTINUATION_MARKERS:
        idx = q.find(marker)
        if idx >= 0:
            q = q[:idx].strip()
    # Frontend appends "\\n\\n{json metadata}" — strip the JSON suffix
    # so the LLM doesn't see implementation details like model name.
    if "\n\n{" in q:
        q = q.split("\n\n{", 1)[0].strip()
    if not q or q == "(继续完成 milestone)":
        title = ""
        if sess_doc is not None:
            title = (
                sess_doc.get("title") if isinstance(sess_doc, dict)
                else getattr(sess_doc, "title", "")
            ) or ""
        for marker in _CONTINUATION_MARKERS:
            idx = title.find(marker)
            if idx >= 0:
                title = title[:idx].strip()
        if "\n\n{" in title:
            title = title.split("\n\n{", 1)[0].strip()
        q = title.strip() or "(继续完成上一轮请求)"
    return q


def _sanitize_args_for_prompt(
    tool_name: str,
    args: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return a prompt-safe copy of tool args — paths/commands only."""
    out: Dict[str, Any] = {}
    for key, value in dict(args or {}).items():
        if key in _LARGE_ARG_KEYS:
            if isinstance(value, str):
                out[key] = f"<{len(value)} chars omitted>"
            elif isinstance(value, list):
                out[key] = f"<{len(value)} items omitted>"
            else:
                out[key] = "<omitted>"
            continue
        if key == "command" and isinstance(value, str) and len(value) > 120:
            out[key] = value[:120] + "…"
            continue
        if isinstance(value, str) and len(value) > 120:
            out[key] = value[:120] + "…"
            continue
        out[key] = value
    return out


def _format_approved_tool_note(fact: ApprovedToolFact) -> str:
    """Render the [已完成] block. Kept small (≤ ~400 chars) so chained
    resumes don't blow the context budget when stacking notes.

    Branches on ``fact.delegated``:

      * delegated=True (V2 path) — the gate was approved but the tool
        was NOT executed yet; the resumed agent must re-issue the call.
      * delegated=False (V1 path) — the tool already ran; do NOT
        re-issue. The body reports success vs failure for next-step
        decisioning.
    """
    try:
        prompt_args = _sanitize_args_for_prompt(fact.name, fact.arguments)
        args_blob = _json_top.dumps(prompt_args, ensure_ascii=False)[:200]
    except Exception:  # noqa: BLE001
        args_blob = "{}"

    if fact.delegated:
        # V2 delegation: gate cleared, but tool has NOT run yet. Tell
        # the LLM to retry exactly this call so the auto-allow path
        # (decision_memory short-circuit) executes the work. Critical:
        # do NOT say "succeeded" here — the LLM will skip the retry
        # and the work won't get done. Dogfood reproducer: bash_exec
        # `pip install ...` was approved, V2 delegated, prompt claimed
        # success, LLM jumped to final response, pip never ran.
        body = (
            f"工具 `{fact.name}` 已被操作员批准（参数: {args_blob}）。"
            "操作员的批准 ONLY 解除了 HITL 闸门，工具本身还没有运行。"
            "请用相同的参数重新调用 `{name}` —— PolicyResolver 会基于"
            "已记录的 session-scope decision 直接放行执行。看到真实结果"
            "之后再决定下一步。"
        ).replace("{name}", fact.name)
    elif fact.success:
        body = (
            f"工具 `{fact.name}` 已被操作员批准并成功执行（参数: {args_blob}）。"
            "请基于该进展继续 — 绝对不要再次调用此工具完成同一步骤；"
            "如果原始请求已被满足，直接给出最终响应。"
        )
    else:
        err_blob = (fact.error or "tool execution failed")[:120]
        collab_hint = ""
        if "outside the bound workspace" in (fact.error or ""):
            collab_hint = (
                " 当前为 AI 协同绑定的工作区：请使用相对路径（如 "
                "`mkdir -p ka_lead_crawler/config`），勿使用 "
                "`/tmp/agent_workspace/...`。"
            )
        body = (
            f"工具 `{fact.name}` 已被批准但执行失败（参数: {args_blob}；"
            f"错误: {err_blob}）。请决定下一步 — 修正参数重试、换工具、"
            f"或者向用户解释失败原因。{collab_hint}"
        )
    return f"[已完成] {body}"


def build_continuation_query(
    qa_query: Optional[str],
    sess_doc: Optional[Mapping[str, Any]] = None,
    approved_tool: Optional[ApprovedToolFact] = None,
) -> str:
    """Public test-surface helper: builds the full continuation prompt
    from a possibly-enriched qa.query + an optional approved-tool fact.

    Pure / no I/O so unit tests can pin down dedup + tool-note format
    without touching mongo or the gateway.
    """
    original = _strip_continuation_markers(qa_query, sess_doc)
    note = (
        "[系统继续提示] 你的上一轮在 HITL 审批处暂停，被拦下的工具调用"
        "刚被操作员批准。请基于历史中前一轮的 tool 调用记录继续完成"
        "上述请求 — 不要重新开始 exploration，不要重复已做过的步骤。"
        "如果上一轮的进度已经满足请求，直接给出最终响应。"
    )
    parts = [original, note]
    if approved_tool is not None:
        parts.append(_format_approved_tool_note(approved_tool))
    return "\n\n".join(parts)


# ── Tool registry build (re-exported helper) ────────────────────────────


async def build_resume_tool_registry():
    """Construct a fresh ``ToolRegistry`` containing local + MCP tools.

    Used by HITL resume to get back a working ``BaseTool`` for the
    paused call without depending on the original session's runtime
    being alive in memory. ``MCPToolWrapper`` dispatches via the
    module-level ``mcp_client`` so the new registry's tools are
    functionally equivalent to the originals.

    Fail-soft: if MCP fetch fails (no VPN / disabled / Eureka down)
    we still return the registry with local sandbox tools registered —
    callers see a missing tool error if the paused call was MCP-only.
    """
    from vendor_runtime_sdk.agent.tools import ToolRegistry, register_local_file_tools
    from vendor_runtime_sdk.agent.tools.mcp_adapter import MCPToolAdapter

    reg = ToolRegistry()
    register_local_file_tools(reg)

    try:
        from vendor_runtime_sdk.mcp.mcp_http_client import mcp_client
        tools_info = await mcp_client.get_tools_info()
        if tools_info is not None:
            MCPToolAdapter.register_all(reg, tools_info, retries=1)
    except Exception as exc:  # noqa: BLE001 — fail-soft per docstring
        logger.warning("hitl.resume: MCP tools_info fetch failed — %s", exc)

    return reg


# ── Argument normalisation ─────────────────────────────────────────────


# LLM emits ``file_path`` for some tools that declare ``path``.
_ARG_ALIASES = {
    "file_path": "path",
}


def normalise_tool_args(tool: Any, args: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Map LLM aliases + drop injected identity keys the tool didn't declare.

    Mirrors the helper in the legacy ``HitlApi._normalize_tool_args``
    so both endpoints share a canonical shape. Anything the schema
    doesn't list passes through to the tool's own validation.
    """
    if not isinstance(args, Mapping):
        return {}
    try:
        schema = getattr(tool, "parameters", {}) or {}
        props = set((schema.get("properties") or {}).keys())
    except Exception:
        props = set()

    out: Dict[str, Any] = {}
    for k, v in args.items():
        # Drop injected-identity keys unless the tool declared them.
        if k in ("user_id", "userId", "agent_id") and k not in props:
            continue
        if k in props:
            out[k] = v
            continue
        aliased = _ARG_ALIASES.get(k)
        if aliased and aliased in props:
            out[aliased] = v
            continue
        out[k] = v
    return out


async def _build_agent_tool_registry_for_resume(agent: Any) -> Any:
    """Return a ToolRegistry that can execute the paused tool on resume.

    V2 auto-resume dispatches a fresh CoderAgent with the full coder
    registry (bash_exec, write_file, …).  Re-use that builder here so
    we don't fall back to ``build_resume_tool_registry()`` which only
    has sandbox + MCP tools and can't run ``write_file``.
    """
    from vendor_runtime_sdk.agent.tools.registry import ToolRegistry

    try:
        from vendor_runtime_sdk.agent.schema import AgentType

        agent_type = getattr(agent, "NAME", None)
        is_coder = agent_type == AgentType.CODER or (
            hasattr(agent_type, "value") and agent_type.value == AgentType.CODER.value
        )
    except Exception:  # noqa: BLE001
        is_coder = type(agent).__name__ == "CoderAgent"

    if is_coder and hasattr(agent, "_build_tool_registry"):
        slash = None
        if hasattr(agent, "_expand_slash"):
            slash, _ = agent._expand_slash(getattr(agent, "query", "") or "")
        session_id = (
            getattr(getattr(agent, "session", None), "id", None)
            or getattr(agent, "session_id", None)
            or ""
        )
        return agent._build_tool_registry(
            slash,
            task_id=session_id or None,
            invoking_milestone_id=session_id or None,
            execution_mode="milestone",
        )

    existing = getattr(agent, "tool_registry", None)
    if existing is not None and getattr(existing, "tool_names", None):
        return existing

    return await build_resume_tool_registry()


async def _execute_v2_delegated_tool(
    agent: Any,
    fact: ApprovedToolFact,
) -> ApprovedToolFact:
    """Run a V2-delegated approved tool inline — do not wait for the LLM.

    Dogfood reproducer (2026-05-22): operator approved ``write_file``,
    V2 told the LLM to retry, but the model glob/read_file'd instead
    and then hit 3× LLM timeout on an oversized context.  Executing the
    approved call deterministically closes the HITL loop.
    """
    try:
        registry = await _build_agent_tool_registry_for_resume(agent)
        tool = registry.get_tool(fact.name)
        if tool is None:
            return ApprovedToolFact(
                name=fact.name,
                arguments=dict(fact.arguments or {}),
                success=False,
                content="",
                error=f"tool '{fact.name}' not found in resume registry",
                delegated=False,
            )
        norm_args = normalise_tool_args(tool, fact.arguments)
        if fact.name == "bash_exec" and isinstance(norm_args.get("command"), str):
            try:
                from vendor_runtime_sdk.agent.tools.workspace_roots import rewrite_staff_collab_bash_command

                norm_args = dict(norm_args)
                norm_args["command"] = rewrite_staff_collab_bash_command(
                    norm_args["command"]
                )
            except Exception as exc:  # noqa: BLE001 — fail-soft
                logger.debug("v2_delegated_tool bash rewrite skipped: %s", exc)
        result = await registry.execute(fact.name, norm_args)
        return ApprovedToolFact(
            name=fact.name,
            arguments=dict(fact.arguments or {}),
            success=bool(result.success),
            content=(result.content or "")[:4096],
            error=result.error,
            delegated=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "v2_delegated_tool: execute failed tool=%s", fact.name,
        )
        return ApprovedToolFact(
            name=fact.name,
            arguments=dict(fact.arguments or {}),
            success=False,
            content="",
            error=f"{type(exc).__name__}: {exc}"[:200],
            delegated=False,
        )


# ── Push tool result onto SSE stream ────────────────────────────────────


async def push_tool_envelope(
    *,
    session_id: str,
    qa_id: str,
    tool_name: str,
    tool_call_id: Optional[str],
    arguments: Optional[Mapping[str, Any]],
    success: bool,
    content: str,
    error: Optional[str] = None,
    final: bool = True,
) -> None:
    """Append ``TOOL_CALL`` + ``TOOL_RESULT`` + ``COMPLETED`` SSE events
    to the session's Redis token queue.

    Frontend ``useChatSession`` already renders the structured envelopes
    via ``ToolEventList`` (Claude-Code-style inline tool cards), so the
    user sees the resumed tool execute in the same bubble as the prior
    HITL gate.

    Args:
        final: When ``True`` (default, V1 behaviour) the envelope ends the
            turn — a ``SYSTEM/COMPLETED`` token is appended, the session
            channel publishes ``complete``, and the session meta status
            flips to ``COMPLETED``. The SSE consumer in
            ``/chat/local_query`` sees this and closes the stream.

            When ``False`` (V2 ``hitl_auto_resume`` path) only the
            ``TOOL_CALL`` + ``TOOL_RESULT`` events are pushed; the SSE
            channel stays open so a follow-up background task can write
            additional events (next milestone steps, final response, …)
            into the same token queue.
    """
    # PR-E*c (SDK extraction §5 PR-E*c): session cache is now sourced from
    # runtime.protocols.session_cache.get_session_cache(). The legacy
    # web.api.chat.cache.RedisCache adapter keeps the runtime path
    # byte-identical in Phase 0. Phase 2 removes the re-export when
    # web/ leaves the engine import surface.
    from vendor_runtime_sdk.agent.schema import StepType, StreamResponse, StreamStatusType
    from vendor_runtime_sdk.runtime.protocols.session_cache import get_session_cache

    cache = get_session_cache()

    call_payload = {
        "name": tool_name,
        "tool_call_id": tool_call_id,
        "arguments": dict(arguments or {}),
    }
    result_payload = {
        "name": tool_name,
        "tool_call_id": tool_call_id,
        "success": bool(success),
        "content": (content or "")[:4096],
        "error": error,
    }

    call_event = StreamResponse(
        sessionId=session_id,
        qaId=qa_id,
        type=StepType.TOOL_CALL,
        status=StreamStatusType.PENDING,
        content=call_payload,
        checkSensitive=False,
    ).model_dump_json(exclude={"save", "deliver"})

    # Tool-level failure must not use top-level FAILED when ``final=False`` —
    # the chat UI treats any SSE chunk with status=FAILED as a terminal
    # session error ("执行失败"), even though V2 auto-resume keeps the
    # agent running.  ``content.success`` still carries the tool outcome.
    result_status = (
        StreamStatusType.PENDING
        if success or not final
        else StreamStatusType.FAILED
    )
    result_event = StreamResponse(
        sessionId=session_id,
        qaId=qa_id,
        type=StepType.TOOL_RESULT,
        status=result_status,
        content=result_payload,
        checkSensitive=False,
    ).model_dump_json(exclude={"save", "deliver"})

    complete_event = StreamResponse(
        sessionId=session_id,
        qaId=qa_id,
        type=StepType.SYSTEM,
        status=StreamStatusType.COMPLETED,
        content="",
        log="HITL resumed — tool finished",
        checkSensitive=False,
    ).model_dump_json(exclude={"save", "deliver"})

    await cache.append_token(session_id=session_id, qa_id=qa_id, token=call_event)
    await cache.append_token(session_id=session_id, qa_id=qa_id, token=result_event)
    if final:
        await cache.append_token(session_id=session_id, qa_id=qa_id, token=complete_event)
        await cache.publish_complete(session_id=session_id, qa_id=qa_id)
        await cache.update_session_status(
            session_id=session_id, qa_id=qa_id, status="COMPLETED"
        )
    # PRD L4 metrics — track V1 (final=True) vs V2 (final=False) traffic.
    try:
        from vendor_runtime_sdk.runtime.hitl_metrics import record_push_envelope
        record_push_envelope(final)
    except Exception:  # noqa: BLE001 — metrics never break hot path
        pass


# ── Reject / cancel envelope ────────────────────────────────────────────


async def push_rejection_envelope(
    *,
    session_id: str,
    qa_id: str,
    tool_name: str,
    tool_call_id: Optional[str],
    reason: str,
    cancel: bool = False,
) -> None:
    """Push a ``TOOL_RESULT`` envelope reflecting operator rejection.

    The agent reads this on the next read of its message context as a
    standard tool failure with ``success=False`` and ``error="..."``,
    so existing failure-handling logic kicks in (recovery prompts,
    etc.) without HITL-specific branches in the agent code.
    """
    # PR-E*c (SDK extraction §5 PR-E*c): session cache is now sourced from
    # runtime.protocols.session_cache.get_session_cache(). The legacy
    # web.api.chat.cache.RedisCache adapter keeps the runtime path
    # byte-identical in Phase 0. Phase 2 removes the re-export when
    # web/ leaves the engine import surface.
    from vendor_runtime_sdk.agent.schema import StepType, StreamResponse, StreamStatusType
    from vendor_runtime_sdk.runtime.protocols.session_cache import get_session_cache

    cache = get_session_cache()
    label = "cancelled" if cancel else "rejected"
    formatted = f"Operator {label} the call: {reason}" if reason else f"Operator {label} the call"

    result_payload = {
        "name": tool_name,
        "tool_call_id": tool_call_id,
        "success": False,
        "content": "",
        "error": formatted,
    }
    result_event = StreamResponse(
        sessionId=session_id,
        qaId=qa_id,
        type=StepType.TOOL_RESULT,
        status=StreamStatusType.FAILED,
        content=result_payload,
        checkSensitive=False,
    ).model_dump_json(exclude={"save", "deliver"})
    complete_event = StreamResponse(
        sessionId=session_id,
        qaId=qa_id,
        type=StepType.SYSTEM,
        status=StreamStatusType.COMPLETED,
        content="",
        log=f"HITL {label}",
        checkSensitive=False,
    ).model_dump_json(exclude={"save", "deliver"})

    await cache.append_token(session_id=session_id, qa_id=qa_id, token=result_event)
    await cache.append_token(session_id=session_id, qa_id=qa_id, token=complete_event)
    await cache.publish_complete(session_id=session_id, qa_id=qa_id)
    await cache.update_session_status(
        session_id=session_id, qa_id=qa_id, status="COMPLETED"
    )


# ── V2 HITL auto-continuation ───────────────────────────────────────────


async def continue_after_hitl_approval(
    *,
    session_id: str,
    qa_id: str,
    approved_tool: Optional[ApprovedToolFact] = None,
    tool_call_id: Optional[str] = None,
) -> None:
    """V2 HITL auto-resume — re-enter the agent loop after the operator
    approves the gated tool, so the milestone continues without the user
    having to send a manual "继续" message.

    Mechanism:
      1. Reload the paused QA + session from MongoDB.
      2. Build a fresh agent via ``Gateway.dispatch`` using the original
         ``agent_type`` as hint (no re-routing — we trust the prior
         routing decision that landed us in HITL).
      2b. When ``approved_tool.delegated`` (V2 path), execute the
         approved tool inline via the resumed agent's full registry
         *before* ``agent.run()`` — do not rely on the LLM to retry
         ``write_file`` / ``bash_exec`` (observed failure mode: re-
         exploration + context blow-up + LLM timeout).
      3. Run ``agent.run()`` to completion, **rewriting** every emitted
         event's ``qaId`` field to the **original** ``qa_id`` before
         appending it to Redis. This keeps the open SSE consumer in
         ``/chat/local_query`` (which is polling tokens keyed by the
         original ``qa_id``) seeing the resumption inline.
      4. Mark the session ``COMPLETED`` + ``publish_complete()`` so the
         SSE loop drains residual tokens and shuts cleanly.

    Failure modes:
      * Toggle off (``hitl_auto_resume``) — caller never invokes this;
        legacy V1 ``push_tool_envelope(final=True)`` already closed SSE.
      * Reload failure — log + status FAILED so the SSE loop terminates
        cleanly with a visible error rather than hanging on PENDING.
      * Mid-run exception — same — log + status FAILED.

    This helper is fire-and-forget; the caller does
    ``asyncio.create_task(continue_after_hitl_approval(...))`` and
    returns the HTTP response immediately so the operator's click
    feels instant.
    """
    import asyncio as _asyncio
    import json as _json

    # PR-E*c (SDK extraction §5 PR-E*c): ExtraBodyModel is now sourced from
    # runtime.types.chat; the session cache is accessed via
    # runtime.protocols.session_cache.get_session_cache(). The legacy
    # web.api.chat.* re-exports keep business code unchanged in Phase 0.
    # Phase 2 removes the re-exports when web/ leaves the engine import surface.
    from vendor_runtime_sdk.agent.schema import QAModel, SessionModel
    from vendor_runtime_sdk.runtime.protocols.session_cache import get_session_cache
    from vendor_runtime_sdk.runtime.types.chat import ExtraBodyModel
    from web.config import config as _app_config

    # PRD L4 metrics — record exactly one outcome before returning, no
    # matter which path we take. Helper is no-op when prometheus_client
    # isn't installed; never raises.
    from vendor_runtime_sdk.runtime.hitl_metrics import record_auto_resume_outcome

    cache = get_session_cache()

    async def _finalize_failed(reason: str) -> None:
        from vendor_runtime_sdk.agent.schema import StepType, StreamResponse, StreamStatusType
        try:
            err_event = StreamResponse(
                sessionId=session_id,
                qaId=qa_id,
                type=StepType.SYSTEM,
                status=StreamStatusType.FAILED,
                content="",
                log=f"hitl_auto_resume failed: {reason}",
                checkSensitive=False,
            ).model_dump_json(exclude={"save", "deliver"})
            await cache.append_token(session_id=session_id, qa_id=qa_id, token=err_event)
            await cache.publish_complete(session_id=session_id, qa_id=qa_id)
            await cache.update_session_status(
                session_id=session_id, qa_id=qa_id, status="FAILED", log=reason
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "continue_after_hitl_approval: finalize_failed path also crashed "
                "for session %s qa %s", session_id, qa_id,
            )

    try:
        qa_doc = await QAModel.get(qa_id)
        if not qa_doc:
            await _finalize_failed(f"qa {qa_id} not found")
            record_auto_resume_outcome("qa_not_found")
            return
        # QAModel.get returns a raw dict in this codebase — wrap into the
        # Pydantic model for attribute access.
        qa = QAModel(**qa_doc) if isinstance(qa_doc, dict) else qa_doc
        sess_doc = await SessionModel.get(session_id, user_id=qa.userId)
        if not sess_doc:
            await _finalize_failed(f"session {session_id} not found")
            record_auto_resume_outcome("session_not_found")
            return

        # Reconstruct the extra_body the original turn used so the
        # continuation runs with the same workspace / model / persona.
        # Primary source: Redis session meta (written at turn start).
        # Mongo SessionModel does not persist extraBody today.
        raw_extra = None
        try:
            _meta = await cache.get_session_meta(session_id=session_id, qa_id=qa_id)
            if _meta:
                _eb = _meta.get("extraBody") or _meta.get(b"extraBody")
                if isinstance(_eb, bytes):
                    _eb = _eb.decode("utf-8", errors="replace")
                if _eb:
                    raw_extra = _eb
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "continue_after_hitl_approval: redis session meta extraBody read failed: %s",
                exc,
            )
        if not raw_extra:
            raw_extra = (
                sess_doc.get("extraBody")
                if isinstance(sess_doc, dict)
                else getattr(sess_doc, "extraBody", None)
            )
        extra_body: Optional[ExtraBodyModel] = None
        if raw_extra:
            try:
                payload = (
                    _json.loads(raw_extra)
                    if isinstance(raw_extra, str)
                    else raw_extra
                )
                extra_body = ExtraBodyModel(**payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "continue_after_hitl_approval: failed to parse extra_body "
                    "(%s); proceeding with empty extra_body", exc,
                )
                extra_body = ExtraBodyModel()

        # Use the same Gateway path the live request goes through so all
        # the standard wiring (registry, skills, runtime hooks, …) is in
        # place.  PR-E*c (SDK extraction §5 PR-E*c): the Gateway is now
        # sourced from ``runtime.gateway_registry`` which the web layer
        # primes during lifespan startup. Engine code never imports
        # from ``web.api.chat.chat`` — the legacy fallback is removed
        # to keep the SDK import boundary clean. Tests inject a fake
        # via ``runtime.gateway_registry.set_gateway``.
        from vendor_runtime_sdk.runtime.conversation import ConversationRuntime
        from vendor_runtime_sdk.runtime.gateway_registry import get_gateway as _registry_get_gateway

        gateway = _registry_get_gateway()
        if gateway is None:
            logger.warning(
                "continue_after_hitl_approval: no Gateway installed in "
                "runtime.gateway_registry; aborting auto-resume "
                "(session=%s qa=%s)", session_id, qa_id,
            )
            await _finalize_failed("no Gateway available")
            record_auto_resume_outcome("gateway_unavailable")
            return

        # Build the continuation query via the dedicated helper so
        # marker dedup + approved-tool surfacing are testable in
        # isolation. Without dedup, chained HITL resumes compound the
        # system note + frontend metadata JSON each cycle; without the
        # approved-tool note, the LLM doesn't see that the prior tool
        # succeeded and re-issues the same call (observed as an
        # infinite write_file → HITL loop in dogfood).
        continuation_query = build_continuation_query(
            qa_query=qa.query,
            sess_doc=sess_doc,
            approved_tool=approved_tool,
        )

        agent = await gateway.dispatch(
            query=continuation_query,
            user_id=qa.userId,
            session_id=session_id,
            extra_body=extra_body,
            agent_type_hint=qa.agentType,
        )

        # HITL continuation queries embed system markers and (redacted)
        # tool-arg snippets — running them through query risk-control
        # false-positives as 恶意攻击 (observed 2026-05-22 on
        # write_file resume).  The original user turn was already
        # moderated; skip re-check on auto-resume.
        await agent.on_init()

        _runtime = ConversationRuntime(session_id=session_id)
        # PR-E*c (SDK extraction §5 PR-E*c): output_schema is defined in
        # ``agent.schema`` (the canonical location); ``web.api.chat.chat``
        # re-exports it. Import directly from the canonical module so
        # the engine never reaches into ``web.api.*`` for this helper.
        from vendor_runtime_sdk.agent.schema import output_schema

        _ws_id = (
            sess_doc.get("workspace_id")
            if isinstance(sess_doc, dict)
            else getattr(sess_doc, "workspace_id", "")
        ) or ""
        _collab_ws_tok = None
        if extra_body and bool(getattr(extra_body, "staff_ai_collab", False)):
            from vendor_runtime_sdk.agent.tools.workspace_roots import (
                collab_workspace_bind,
                collab_workspace_reset,
            )

            _collab_ws_tok = collab_workspace_bind(
                getattr(extra_body, "collab_workspace_relative", None),
                workspace_absolute=getattr(extra_body, "collab_workspace_path", None),
                workspace_id=_ws_id or None,
                staff_collab_turn=True,
            )
            if getattr(extra_body, "imported_documents", None):
                try:
                    from vendor_runtime_sdk.agent.coder.context.imported_docs_workspace import (
                        imported_documents_workspace_hint,
                        materialize_imported_documents_to_workspace,
                    )
                    from vendor_runtime_sdk.agent.tools.workspace_roots import get_collab_effective_root

                    _ws_root = get_collab_effective_root()
                    if _ws_root is not None:
                        _mat_paths = materialize_imported_documents_to_workspace(
                            _ws_root, extra_body
                        )
                        if _mat_paths:
                            agent.cache["collab.materialized_attachment_paths"] = (
                                _mat_paths
                            )
                            _hint = imported_documents_workspace_hint(_mat_paths)
                            if _hint:
                                _prev = (
                                    getattr(extra_body, "append_system_prompt", None)
                                    or ""
                                )
                                extra_body.append_system_prompt = (
                                    f"{_prev}\n\n{_hint}".strip() if _prev else _hint
                                )
                                agent.extra_body = extra_body
                except Exception as _mat_exc:  # noqa: BLE001
                    logger.warning(
                        "continue_after_hitl_approval: materialize imported_documents "
                        "failed: %s",
                        _mat_exc,
                    )

        # V2 delegation: execute the approved tool inline before the LLM
        # loop starts.  Relying on the model to re-issue write_file was
        # flaky (re-exploration + context blow-up) and left code tasks
        # with zero files written after operator approval.
        _post_exec_fact = approved_tool
        if approved_tool is not None and approved_tool.delegated:
            _post_exec_fact = await _execute_v2_delegated_tool(agent, approved_tool)
            try:
                await push_tool_envelope(
                    session_id=session_id,
                    qa_id=qa_id,
                    tool_name=_post_exec_fact.name,
                    tool_call_id=tool_call_id,
                    arguments=_post_exec_fact.arguments,
                    success=_post_exec_fact.success,
                    content=_post_exec_fact.content,
                    error=_post_exec_fact.error,
                    final=False,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "continue_after_hitl_approval: push_tool_envelope failed "
                    "(%s); continuing agent run", exc,
                )
            continuation_query = build_continuation_query(
                qa_query=qa.query,
                sess_doc=sess_doc,
                approved_tool=_post_exec_fact,
            )
            agent.query = continuation_query
            if getattr(agent, "qa", None) is not None:
                agent.qa.query = continuation_query
            logger.info(
                "continue_after_hitl_approval: v2 inline execute tool=%s "
                "success=%s session=%s",
                _post_exec_fact.name,
                _post_exec_fact.success,
                session_id,
            )

        # Observe REQUIRES_APPROVAL events inline so we don't have to
        # race the async mongo write of ``hitl_pending``. If the resumed
        # agent itself pauses at another HITL gate (write_file → bash_exec
        # chain) we keep the SSE open so the next /hitl/decide → continuation
        # cycle can drive the milestone the rest of the way.
        # Pin the SSE-consumer's qa_id into a ContextVar so the
        # in-stream HITL passthrough handler can persist
        # ``hitl_pending.qa_id`` as the ORIGINAL qa_id rather than
        # whatever inner V2-spawned qa the agent currently has. Without
        # this, chained V2 HITL pauses route subsequent
        # ``/hitl/decide`` cycles to the wrong cache key and the chat
        # bubble hangs at "处理中" even after the backend completes.
        from vendor_runtime_sdk.runtime.conversation._stream import _ORIGINAL_SSE_QA_ID
        _qa_id_token = _ORIGINAL_SSE_QA_ID.set(qa_id)

        _saw_requires_approval = False
        try:
            async for event in _runtime.wrap_agent_stream(agent.run(), agent_ref=agent):
                event_schema = output_schema(event)
                if not _saw_requires_approval and "REQUIRES_APPROVAL" in (event or ""):
                    _saw_requires_approval = True
                # Mirror of the chat.py first-turn filter — when the
                # resumed V2 agent itself pauses at another HITL gate
                # (write_file → bash_exec chain), its ``BaseAgent.run``
                # finally block STILL yields a terminal SYSTEM/COMPLETED
                # event because the generator exited without an
                # exception. Letting that event reach the SSE consumer
                # makes the FE render "执行完成" right next to the
                # second ApprovalCard — user sees both the "I'm done"
                # text AND a pending approval, completely contradictory.
                # Drop the agent's terminal event when we've already
                # seen REQUIRES_APPROVAL this resume cycle; the next
                # /hitl/decide approval will either drive past the gate
                # (and emit the real terminal token in our finally
                # below) or chain to yet another approval.
                _is_terminal_completed = False
                if _saw_requires_approval:
                    try:
                        _evt_obj = event_schema.event_object
                        from vendor_runtime_sdk.agent.schema import StepType, StreamStatusType
                        if (
                            getattr(_evt_obj, "status", None)
                                == StreamStatusType.COMPLETED
                            and getattr(_evt_obj, "type", None)
                                == StepType.SYSTEM
                        ):
                            _is_terminal_completed = True
                    except Exception:  # noqa: BLE001 — never raise on filter
                        _is_terminal_completed = False
                if _is_terminal_completed:
                    logger.debug(
                        "continue_after_hitl_approval: session %s — dropping "
                        "resumed agent's terminal SYSTEM/COMPLETED because "
                        "another HITL gate is pending",
                        session_id,
                    )
                    continue
                # Rewrite the qaId so the still-open SSE consumer (keyed
                # by the *original* qa_id) sees the new events inline,
                # not on a separate qa it isn't subscribed to.
                try:
                    payload = _json.loads(event_schema.event_str)
                    payload["qaId"] = qa_id
                    rewritten = _json.dumps(payload, ensure_ascii=False)
                except Exception:  # noqa: BLE001
                    rewritten = event_schema.event_str
                await cache.append_token(
                    session_id=session_id,
                    qa_id=qa_id,
                    token=rewritten,
                    ttl=_app_config.resume_config.ttl,
                )
        finally:
            if _saw_requires_approval:
                logger.info(
                    "continue_after_hitl_approval: session %s qa %s — "
                    "agent paused at another HITL gate; keeping SSE open",
                    session_id, qa_id,
                )
            else:
                # Append a terminal SYSTEM/COMPLETED token to the queue
                # BEFORE flipping Redis status. The frontend clears its
                # "正在工具调用" spinner on this token event; without it
                # the chat bubble stays in the loading state even after
                # the backend session is fully COMPLETED. ``push_tool_envelope``
                # does this for the V1 path; V2 must mirror it.
                try:
                    from vendor_runtime_sdk.agent.schema import (
                        StepType,
                        StreamResponse,
                        StreamStatusType,
                    )
                    _complete_event = StreamResponse(
                        sessionId=session_id,
                        qaId=qa_id,
                        type=StepType.SYSTEM,
                        status=StreamStatusType.COMPLETED,
                        content="",
                        log="hitl_auto_resume continuation finished",
                        checkSensitive=False,
                    ).model_dump_json(exclude={"save", "deliver"})
                    await cache.append_token(
                        session_id=session_id,
                        qa_id=qa_id,
                        token=_complete_event,
                        ttl=_app_config.resume_config.ttl,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "continue_after_hitl_approval: failed to append "
                        "terminal SYSTEM/COMPLETED token (session=%s qa=%s)",
                        session_id, qa_id,
                    )
                await cache.update_session_status(
                    session_id=session_id, qa_id=qa_id, status="COMPLETED"
                )
                await cache.publish_complete(session_id=session_id, qa_id=qa_id)
            if _collab_ws_tok is not None:
                from vendor_runtime_sdk.agent.tools.workspace_roots import collab_workspace_reset

                collab_workspace_reset(_collab_ws_tok)
        # No exception → record the natural terminal outcome. Putting this
        # after the inner try/finally (not inside) avoids double-counting
        # when an exception in the stream falls through to the outer
        # except path below.
        record_auto_resume_outcome(
            "chained" if _saw_requires_approval else "completed"
        )
        logger.info(
            "continue_after_hitl_approval: session %s qa %s — resumed "
            "(saw_requires_approval=%s)",
            session_id, qa_id, _saw_requires_approval,
        )
    except _asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "continue_after_hitl_approval: session %s qa %s — unexpected failure",
            session_id, qa_id,
        )
        await _finalize_failed(f"{type(exc).__name__}: {exc}")
        # Heuristic: distinguish mongo/storage faults from generic unexpected
        # failures so ops can read the dashboard at a glance. ServerSelection
        # / NetworkTimeout / OperationFailure all live under pymongo /
        # motor and embed "Mongo" in the class name.
        _exc_name = type(exc).__name__
        if "Mongo" in _exc_name or "PyMongo" in _exc_name:
            record_auto_resume_outcome("mongo_error")
        else:
            record_auto_resume_outcome("unexpected_error")


__all__ = [
    "ApprovedToolFact",
    "build_continuation_query",
    "build_resume_tool_registry",
    "continue_after_hitl_approval",
    "normalise_tool_args",
    "push_rejection_envelope",
    "push_tool_envelope",
]
