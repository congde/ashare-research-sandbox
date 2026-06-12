# -*- coding: utf-8 -*-
"""
SkillReviewMixin — generator-verifier loop, skill nudge, background review

Auto-extracted from runtime/conversation.py during refactoring.
Part of the ConversationRuntime mixin chain.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, List, Optional

class SkillReviewMixin:
    """SkillReviewMixin — generator-verifier loop, skill nudge, background review"""

    async def _run_generator_verifier_loop(
        self,
        *,
        grader: "Grader",
        rubric: "Rubric",
        initial_output: str,
    ) -> "OutcomeReport":
        """
        Drive the Generator-Verifier retry loop around the current agent turn.

        The first attempt reuses ``initial_output`` (the already-streamed
        response — we never re-invoke the agent for attempt 0).  If the Grader
        returns FAIL, subsequent attempts call ``self._agent_ref.run(
        injected_feedback=...)`` and SILENTLY consume the SSE event stream
        (events are NOT re-yielded to the caller) while aggregating CONTENT /
        ANSWER_RESPONSE chunks into a new output string.

        Design rationale (P0, docs/多Agent优化实施方案-SDLC.md Sprint 1):
          - The user-facing stream must not be replayed mid-turn.  Retries
            stay telemetry-only so dashboards can observe FAIL→PASS
            turnaround without mutating the live SSE response.
          - We preserve the FSM invariant — the loop runs inside one RUNNING
            cycle and never re-enters RUNNING.
        """
        from vendor_runtime_sdk.agent.evaluation.retry_loop import (
            GeneratorVerifierLoop,
            RetryLoopConfig,
        )

        agent_ref = self._agent_ref

        async def _silent_consume(feedback: str) -> str:
            """Consume agent.run(injected_feedback=...) events silently."""
            buf: List[str] = []
            stream = agent_ref.run(injected_feedback=feedback)
            try:
                async for evt in stream:
                    parsed = self._parse_sse_event(evt)
                    if not parsed:
                        continue
                    etype = str(
                        parsed.get("type", "") or parsed.get("event_type", "") or ""
                    ).upper()
                    estatus = str(parsed.get("status", "") or "").upper()
                    if etype in ("CONTENT", "ANSWER_RESPONSE") and estatus == "PENDING":
                        content = parsed.get("content")
                        if isinstance(content, str) and content:
                            buf.append(content)
            finally:
                aclose = getattr(stream, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception:
                        pass
            return "".join(buf) if buf else (
                getattr(self, "_last_response_text", "") or ""
            )

        async def generator_fn(feedback: Optional[str]) -> str:
            # Attempt 0 — reuse the already-streamed response.  The user has
            # already received it; re-invoking the agent would duplicate side
            # effects (tool calls, cost, memory writes).
            if feedback is None:
                return initial_output
            # Attempt 1+ — re-run the agent silently with verifier feedback
            # folded into the query via Agent.run(injected_feedback=...).
            return await _silent_consume(feedback)

        loop = GeneratorVerifierLoop(grader=grader, config=RetryLoopConfig())
        result = await loop.run(
            session_id=self._session_id,
            agent_id=getattr(agent_ref, "agent_type", None) or "runtime",
            rubric=rubric,
            generator_fn=generator_fn,
        )
        # ``final_report`` is always populated by ``GeneratorVerifierLoop.run``
        # (synthesized PENDING when budget is exhausted before attempt 0);
        # assert for the type-checker.
        assert result.final_report is not None
        return result.final_report

    def _compute_nudge_interval(self) -> int:
        """Adaptive nudge interval based on quality signals."""
        base = 10
        score = getattr(self, "_last_grader_score", None)
        if score is not None:
            if score < 50:
                base = 5    # low quality → review sooner
            elif score > 80:
                base = 20   # high quality → review less often
        if self._fallback_count > 0:
            base = max(3, base - 3)  # fallback triggered → review sooner
        return base

    async def _background_skill_review(self):
        """Spawn a background agent to review conversations and suggest skill improvements.

        Optimizations over initial skeleton:
          1. Injects actual conversation context (response text, metrics, grader score)
          2. Parses JSON suggestions and calls SkillRegistry.evolve() for draft creation
          3. Records evolution events to TelemetryRecorder for cross-session tracking
        """
        try:
            from vendor_runtime_sdk.agent.typed_subagent import SubAgentRole, SubAgentSpawner
            from vendor_runtime_sdk.llm.base import create_llm

            # ── Build context summary from actual conversation data ───────
            _activity = self._activity.get_summary()
            _response = getattr(self, "_last_response_text", "") or ""
            _score = getattr(self, "_last_grader_score", None)

            context_lines = [
                f"Session: {self._session_id}",
                f"Iterations: {self._current_iteration}",
                f"Tool calls: {_activity.tool_call_count}",
                f"API calls: {_activity.api_call_count}",
                f"Fallback count: {self._fallback_count}",
                f"Tokens used: {self._tokens_total}",
            ]
            if _score is not None:
                context_lines.append(f"Quality score: {_score:.0f}/100")
            if _response:
                context_lines.append(f"Last response (truncated):\n{_response[:2000]}")

            context_summary = "\n".join(context_lines)

            # Collect existing skill names so the LLM can match them
            _skill_names = []
            try:
                _reg = self._get_skill_registry()
                if _reg and hasattr(_reg, "_entries"):
                    _skill_names = [e.name for e in _reg._entries.values() if hasattr(e, "name")]
            except Exception:
                pass

            from vendor_runtime_sdk.agent.tools.registry import ToolRegistry

            _llm, _model = create_llm()
            spawner = SubAgentSpawner(llm=_llm, model_name=_model)
            result = await spawner.spawn_and_wait(
                task=(
                    f"## Conversation Context\n{context_summary}\n\n"
                    f"## Existing Skills\n{_skill_names}\n\n"
                    "## Task\n"
                    "Review the conversation context above. Identify patterns where the agent's "
                    "responses could be improved. Suggest specific skill improvements as a JSON list:\n"
                    '[{"skill_name": "existing_skill_name", "improvement": "improved content", "rationale": "why"}]\n'
                    "Rules:\n"
                    "- skill_name MUST be one of the existing skills listed above\n"
                    "- improvement should be the new skill content text\n"
                    "- Be concise. If no improvements needed, return an empty list []\n"
                    "- Maximum 3 suggestions per review\n"
                ),
                role=SubAgentRole.PLAN,
                tool_registry=ToolRegistry(),
                depth=1,
                label="skill-review-bg",
                timeout=90.0,
            )
            self._review_count += 1
            logger.info(
                "Background skill review completed: success=%s, elapsed=%dms",
                result.success, result.elapsed_ms,
            )

            # ── Parse suggestions and auto-evolve as draft ────────────────
            _drafts_created = 0
            if result.success and result.content:
                try:
                    import json as _json
                    # Strip markdown code fences if present
                    _raw = result.content.strip()
                    if _raw.startswith("```"):
                        _raw = "\n".join(_raw.split("\n")[1:-1])
                    suggestions = _json.loads(_raw)
                    if isinstance(suggestions, list) and suggestions:
                        _registry = self._get_skill_registry()
                        if _registry:
                            for s in suggestions[:3]:
                                _name = s.get("skill_name", "")
                                _improvement = s.get("improvement", "")
                                _rationale = s.get("rationale", "")
                                if not _name or not _improvement:
                                    continue
                                _entry = _registry.get_by_name(_name, scope="global")
                                if _entry:
                                    try:
                                        await _registry.evolve(
                                            skill_id=_entry.skill_id,
                                            new_content=_improvement,
                                            actor="self-evolution",
                                            change_summary=_rationale,
                                        )
                                        _drafts_created += 1
                                        logger.info(
                                            "Self-evolution: created draft for skill '%s' — %s",
                                            _name, _rationale[:80],
                                        )
                                    except Exception as _ev_exc:
                                        logger.debug("Self-evolution: evolve '%s' failed: %s", _name, _ev_exc)
                except Exception as _parse_exc:
                    logger.debug("Self-evolution: suggestion parsing failed: %s", _parse_exc)

            # ── Telemetry ─────────────────────────────────────────────────
            try:
                from vendor_runtime_sdk.runtime.telemetry import SpanEvent, get_recorder
                recorder = get_recorder()
                recorder.record_span_event(SpanEvent(
                    span_type="skill_review_completed",
                    session_id=self._session_id,
                    metadata={
                        "nudge_count": self._nudge_count,
                        "review_count": self._review_count,
                        "drafts_created": _drafts_created,
                    },
                ))
                recorder.record_evolution_event("review_completed")
                for _ in range(_drafts_created):
                    recorder.record_evolution_event("draft_created")
            except Exception:
                pass

        except Exception as exc:
            logger.error("Background skill review failed: %s", exc, exc_info=True)

    def _get_skill_registry(self):
        """Get SkillRegistry from app.state (best-effort)."""
        try:
            from web.context import context as _ctx
            _req = _ctx.get("request")
            if _req and hasattr(_req, "app"):
                return getattr(getattr(_req.app, "state", None), "skill_registry", None)
        except Exception:
            pass
        return None


logger = logging.getLogger(__name__)
