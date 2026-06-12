# -*- coding: utf-8 -*-
"""
Hooks — Tool execution middleware pipeline.

Hook lifecycle:
  Phase 1: PreToolUse Hook
    - Can modify tool input (parameter sanitization)
    - Can override permission decision
    - Can silently cancel tool call
    - Can explicitly deny tool call (LLM-visible reason)

  Phase 2: Permission Check — handled by PermissionResolver
           (Sprint 6 V2 single-lattice; see runtime.policy.permission).

  Phase 3: Tool Execution

  Phase 4: PostToolUse Hook
    - Can audit tool usage
    - Can redact/truncate tool output
    - Can mark successful results as errors
    - Can add additional messages

Built-in hooks:
  - AuditLogHook: Record all tool calls to JSONL
  - RiskControlHook: Integrate LLM Shield (URL risk check, sensitive word filter)
  - TokenBudgetHook: Truncate oversized tool output
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from vendor_runtime_sdk.runtime.protocols import ToolResult

logger = logging.getLogger(__name__)


# ──────────────── Hook Result Types ────────────────


@dataclass
class PreHookResult:
    """PreToolUse hook 返回结果"""

    updated_input: Optional[Dict] = None          # 替换工具输入
    permission_override: Optional[str] = None      # "allow" | "deny" | "ask"
    cancelled: bool = False                        # 静默取消
    denied: bool = False                           # 显式拒绝
    deny_reason: Optional[str] = None              # 拒绝原因（LLM 可见）
    messages: List[str] = field(default_factory=list)


@dataclass
class PostHookResult:
    """PostToolUse hook 返回结果"""

    mark_as_error: bool = False
    error_message: Optional[str] = None
    additional_messages: List[str] = field(default_factory=list)
    redacted_output: Optional[str] = None           # 脱敏后的输出


# ──────────────── Hook Protocol ────────────────


class PreToolUseHook(ABC):
    """PreToolUse hook 基类"""

    @abstractmethod
    async def pre(self, tool_name: str, tool_input: Dict) -> PreHookResult:
        ...


class PostToolUseHook(ABC):
    """PostToolUse hook 基类"""

    @abstractmethod
    async def post(self, tool_name: str, result: ToolResult) -> PostHookResult:
        ...


class PostToolUseFailureHook(ABC):
    """PostToolUse failure hook 基类"""

    @abstractmethod
    async def post_failure(self, tool_name: str, error: Exception) -> PostHookResult:
        ...


# ──────────────── Hook Runner ────────────────


class HookRunner:
    """
    工具执行 Hook 中间件管线.

    Usage:
        hook_runner = HookRunner()
        hook_runner.register_pre_hook(RiskControlHook())
        hook_runner.register_post_hook(AuditLogHook())

        pre_result = await hook_runner.run_pre_tool_use("bash", {"command": "ls"})
        if pre_result.denied:
            return ToolResult(success=False, error=pre_result.deny_reason)

        result = await tool_executor.execute("bash", pre_result.updated_input or {"command": "ls"})
        post_result = await hook_runner.run_post_tool_use("bash", result)
    """

    def __init__(self):
        self._pre_hooks: List[PreToolUseHook] = []
        self._post_hooks: List[PostToolUseHook] = []
        self._post_failure_hooks: List[PostToolUseFailureHook] = []

    def register_pre_hook(self, hook: PreToolUseHook) -> None:
        self._pre_hooks.append(hook)

    def register_post_hook(self, hook: PostToolUseHook) -> None:
        self._post_hooks.append(hook)

    def register_post_failure_hook(self, hook: PostToolUseFailureHook) -> None:
        self._post_failure_hooks.append(hook)

    async def run_pre_tool_use(
        self, tool_name: str, tool_input: Dict
    ) -> PreHookResult:
        """执行所有 PreToolUse hooks，合并结果"""
        merged = PreHookResult()
        current_input = tool_input

        for hook in self._pre_hooks:
            try:
                result = await hook.pre(tool_name, current_input)
                # Merge results
                if result.updated_input is not None:
                    current_input = result.updated_input
                    merged.updated_input = current_input
                if result.cancelled:
                    merged.cancelled = True
                    break
                if result.denied:
                    merged.denied = True
                    merged.deny_reason = result.deny_reason
                    break
                if result.permission_override is not None:
                    merged.permission_override = result.permission_override
                merged.messages.extend(result.messages)
            except Exception as e:
                logger.warning("PreHook %s failed: %s", hook.__class__.__name__, e)

        return merged

    async def run_post_tool_use(
        self, tool_name: str, result: ToolResult
    ) -> PostHookResult:
        """执行所有 PostToolUse hooks，合并结果"""
        merged = PostHookResult()

        for hook in self._post_hooks:
            try:
                post_result = await hook.post(tool_name, result)
                if post_result.mark_as_error:
                    merged.mark_as_error = True
                    merged.error_message = post_result.error_message
                if post_result.redacted_output is not None:
                    merged.redacted_output = post_result.redacted_output
                    # Update result for next hook
                    result = ToolResult(
                        success=result.success,
                        content=post_result.redacted_output,
                        error=result.error,
                        metadata=result.metadata,
                    )
                merged.additional_messages.extend(post_result.additional_messages)
            except Exception as e:
                logger.warning("PostHook %s failed: %s", hook.__class__.__name__, e)

        return merged

    async def run_post_tool_use_failure(
        self, tool_name: str, error: Exception
    ) -> PostHookResult:
        """执行所有 PostToolUse failure hooks"""
        merged = PostHookResult()

        for hook in self._post_failure_hooks:
            try:
                post_result = await hook.post_failure(tool_name, error)
                merged.additional_messages.extend(post_result.additional_messages)
                if post_result.redacted_output is not None:
                    merged.redacted_output = post_result.redacted_output
            except Exception as e:
                logger.warning("PostFailureHook %s failed: %s", hook.__class__.__name__, e)

        return merged


# ──────────────── Built-in Hooks ────────────────


class AuditLogHook(PostToolUseHook):
    """审计日志 Hook — 三层持久化:

    Plan §3.4: (1) Mongo ``audit_logs`` 主 sink, toggle ``audit_log_central``
    (2) Mongo 挂时写 per-POD_ID fallback ``{audit_fallback_base}/{pod_id}/{YYYYMMDD}.jsonl``
    (3) 两路都挂时 ``logger.critical`` — 最后一道防线.

    Fallback 按 POD_ID 分文件避免多副本互相覆盖；后续离线合并。
    """

    def __init__(self, log_dir: Optional[Path] = None):
        self._explicit_log_dir = log_dir
        # Legacy compatibility — ``~/.ai-buddy/audit`` is the default when
        # toggle off + shared-storage helper not importable. We do NOT mkdir
        # here: under ``audit_log_central=on`` the fallback path is never
        # touched and creating an empty directory on every pod boot is noise.
        # ``_write_fallback`` creates the dir lazily on first fallback write.
        self._log_dir = log_dir or Path.home() / ".ai-buddy" / "audit"

    async def post(self, tool_name: str, result: ToolResult) -> PostHookResult:
        entry = self._build_entry(tool_name, result)
        if await self._try_mongo_write(entry):
            return PostHookResult()
        self._write_fallback(entry)
        return PostHookResult()

    # ── Entry construction ────────────────────────────────────────────────

    def _build_entry(self, tool_name: str, result: ToolResult) -> Dict[str, Any]:
        """Build an AuditLogDAO-compatible entry.

        Falls back silently when workspace/owner context is unavailable
        (e.g., non-HTTP invocation paths). The shared-PVC fallback file also
        accepts the thinner payload.
        """
        entry: Dict[str, Any] = {
            "timestamp": time.time(),
            "tool_name": tool_name,
            "success": result.error is None,
            "content_length": len(result.output) if result.output else 0,
            "error": result.error,
            "performed_at": datetime.now(tz=timezone.utc),
        }
        try:
            from vendor_runtime_sdk.runtime.config.shared_storage import get_pod_id
            entry["pod_id"] = get_pod_id()
        except Exception:
            entry["pod_id"] = "unknown"
        try:
            # PR-E2b (SDK extraction §5 PR-E2b): owner_id / avatar_id /
            # set_ownership are now sourced from runtime.context.  The legacy
            # web.middleware.* call continues via the runtime.context
            # fallback path so runtime behaviour is unchanged in Phase 0.
            # Phase 2 removes the fallback when web/ leaves the engine
            # import surface.
            from vendor_runtime_sdk.runtime.context import get_owner_id, get_workspace_id
            ws = get_workspace_id() or ""
            owner = get_owner_id() or ""
            if ws:
                entry["workspace_id"] = ws
            if owner:
                entry["user_id"] = owner
        except Exception:
            pass
        # Agent-vs-employee distinction. ``AvatarIsolationMiddleware`` only
        # sets the ContextVar when the JWT carries an ``avatar_id`` claim —
        # that's the S1 convention for "agent acting on behalf of
        # employee". Presence ⇒ agent; absence ⇒ direct employee call.
        # The whole ephemeral-git-token / compliance story depends on this
        # line being reliable (see docs/数字员工协同V1实施计划.md §Gap 2).
        # Fail-safe to "user" if the lookup blows up — audit chain must
        # never break on an actor-type import error.
        try:
            # PR-E2b (SDK extraction §5 PR-E2b): owner_id / avatar_id /
            # set_ownership are now sourced from runtime.context.  The legacy
            # web.middleware.* call continues via the runtime.context
            # fallback path so runtime behaviour is unchanged in Phase 0.
            # Phase 2 removes the fallback when web/ leaves the engine
            # import surface.
            from vendor_runtime_sdk.runtime.context import get_avatar_id
            avatar_id = get_avatar_id() or ""
            if avatar_id:
                entry["avatar_id"] = avatar_id
            entry["actor_type"] = "agent" if avatar_id else "user"
        except Exception:
            entry["actor_type"] = "user"
        return entry

    # ── Mongo primary sink ────────────────────────────────────────────────

    async def _try_mongo_write(self, entry: Dict[str, Any]) -> bool:
        """Insert into Mongo ``audit_logs``. Returns True on success."""
        try:
            from vendor_runtime_sdk.runtime.config.toggles import get_toggles
            if not get_toggles().is_enabled("audit_log_central"):
                return False
        except Exception:
            return False
        if not entry.get("workspace_id"):
            # Compound index (workspace_id, performed_at) requires it —
            # without it, skip Mongo and use the pod-local file.
            return False
        try:
            from dao.mongo.audit_log import get_audit_log_dao
            dao = get_audit_log_dao()
            return bool(await dao.write(entry))
        except Exception as exc:
            logger.debug("AuditLogHook: mongo sink failed: %s", exc)
            return False

    # ── PVC / legacy fallback ─────────────────────────────────────────────

    def _resolve_fallback_dir(self) -> Path:
        """Pod-scoped fallback dir: ``{audit_fallback_base}/{pod_id}``.

        Falls back to the legacy ``~/.ai-buddy/audit`` layout when the
        shared-storage helper is not importable (keeps tests/scripts alive).
        """
        if self._explicit_log_dir is not None:
            return self._explicit_log_dir
        try:
            from vendor_runtime_sdk.runtime.config.shared_storage import audit_fallback_base, get_pod_id
            return audit_fallback_base() / get_pod_id()
        except Exception:
            return self._log_dir

    def _write_fallback(self, entry: Dict[str, Any]) -> None:
        """Append a JSONL record to the pod-scoped fallback file.

        Critical-log on any IO failure — never crash the tool call.
        """
        try:
            fallback_dir = self._resolve_fallback_dir()
            fallback_dir.mkdir(parents=True, exist_ok=True)
            log_file = fallback_dir / f"{time.strftime('%Y%m%d')}.jsonl"
            serialised = json.dumps(entry, ensure_ascii=False, default=_json_safe)
            with log_file.open("a", encoding="utf-8") as f:
                f.write(serialised + "\n")
        except Exception as exc:
            # Last-ditch: log the audit entry itself so ops can reconstruct
            # offline. Critical level because losing audit records is a
            # compliance incident.
            logger.critical(
                "AuditLogHook: both Mongo and PVC fallback failed for tool=%s: %s. Entry=%s",
                entry.get("tool_name"),
                exc,
                entry,
            )


def _json_safe(obj: Any) -> str:
    """Default JSON encoder for datetime / other non-serialisable objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


class RiskControlHook(PreToolUseHook):
    """风控 Hook — URL 风险检查 + 敏感词过滤"""

    def __init__(
        self,
        blocked_commands: Optional[List[str]] = None,
        sensitive_patterns: Optional[List[str]] = None,
    ):
        self._blocked_commands = blocked_commands or [
            "rm -rf /",
            "mkfs",
            "dd if=",
            "> /dev/sd",
        ]
        self._sensitive_patterns = sensitive_patterns or []

    async def pre(self, tool_name: str, tool_input: Dict) -> PreHookResult:
        # Check bash commands for destructive patterns
        if tool_name == "bash":
            command = tool_input.get("command", "")
            for blocked in self._blocked_commands:
                if blocked in command:
                    return PreHookResult(
                        denied=True,
                        deny_reason=f"Command contains blocked pattern: {blocked}",
                    )

        # Check URL risk for web_search / read_url
        if tool_name in ("web_search", "read_url"):
            url = tool_input.get("url", "") or tool_input.get("query", "")
            # Simple check — can be enhanced with LLM Shield
            for pattern in self._sensitive_patterns:
                if pattern in url:
                    return PreHookResult(
                        denied=True,
                        deny_reason=f"URL contains sensitive pattern: {pattern}",
                    )

        return PreHookResult()


# Sprint 10 PR-3 (T1.3) — TokenBudgetHook output cap operator-tunable
# via env.  Default 16_000 (~4K tokens) preserves prior behaviour.
# Ceiling 256_000 (~64K tokens) prevents runaway memory under a fat-
# fingered config.
_TOKEN_BUDGET_CEILING = 256_000


def _resolve_token_budget_max_chars() -> int:
    raw = os.environ.get("RUNTIME_TOKEN_BUDGET_HOOK_MAX_CHARS", "").strip()
    if not raw:
        return 16_000
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "RUNTIME_TOKEN_BUDGET_HOOK_MAX_CHARS=%r not int; using default 16000",
            raw,
        )
        return 16_000
    if value <= 0:
        logger.warning(
            "RUNTIME_TOKEN_BUDGET_HOOK_MAX_CHARS=%d must be > 0; using default",
            value,
        )
        return 16_000
    if value > _TOKEN_BUDGET_CEILING:
        logger.warning(
            "RUNTIME_TOKEN_BUDGET_HOOK_MAX_CHARS=%d exceeds ceiling %d; clamping",
            value, _TOKEN_BUDGET_CEILING,
        )
        return _TOKEN_BUDGET_CEILING
    return value


class TokenBudgetHook(PostToolUseHook):
    """Token 预算 Hook — 截断超大工具输出"""

    # Class-level default kept for backward compatibility with code
    # that reads ``TokenBudgetHook.MAX_OUTPUT_CHARS`` directly.
    MAX_OUTPUT_CHARS = _resolve_token_budget_max_chars()

    def __init__(self, max_output_chars: Optional[int] = None):
        # Resolve at instance-creation time so an operator flipping the
        # env post-import gets the new value on the next hook bind.
        self._max_output_chars = (
            max_output_chars
            if max_output_chars is not None
            else _resolve_token_budget_max_chars()
        )

    async def post(self, tool_name: str, result: ToolResult) -> PostHookResult:
        if result.content and len(result.content) > self._max_output_chars:
            truncated = result.content[:self._max_output_chars] + "\n[... truncated by TokenBudgetHook]"
            return PostHookResult(redacted_output=truncated)
        return PostHookResult()


class DLPHook(PostToolUseHook):
    """数据脱敏 Hook — 输出内容脱敏处理"""

    def __init__(self, patterns: Optional[List[Dict[str, str]]] = None):
        _api_key_regex = (
            r"(api[_-]?key|token|secret)"
            r"[\"']?\s*[:=]\s*[\"']?[a-zA-Z0-9_-]{16,}"
        )
        self._patterns = patterns or [
            {"name": "email", "regex": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "replace": "[EMAIL]"},
            {"name": "phone", "regex": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "replace": "[PHONE]"},
            {"name": "api_key", "regex": _api_key_regex, "replace": "[API_KEY]"},
        ]

    async def post(self, tool_name: str, result: ToolResult) -> PostHookResult:
        import re
        content = result.content
        if not content:
            return PostHookResult()

        for pattern in self._patterns:
            content = re.sub(pattern["regex"], pattern["replace"], content, flags=re.IGNORECASE)

        if content != result.content:
            return PostHookResult(redacted_output=content)
        return PostHookResult()
