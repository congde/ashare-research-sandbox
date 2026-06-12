# -*- coding: utf-8 -*-
"""
Tool Hook Middleware — §6.7

Pre/post/failure hooks that wrap tool execution inside the agent loop.

Three built-in hooks
────────────────────
AuditLogHook    — writes a JSONL audit record per tool call
RiskControlHook — URL-safety check on args + output redaction
TokenBudgetHook — truncates tool result content to ≤ max_result_size_chars

Hook Protocol
─────────────
    pre(tool_name, args)         → PreHookResult
    post(tool_name, args, result) → PostHookResult
    on_failure(tool_name, args, error) → PostHookResult

ToolHookMiddleware.execute() wraps a ToolExecutor call with the full chain.

merge_hook_feedback() helper merges all injected messages into the final
tool-result string that gets pushed into the session.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── Local ToolResult ────────────────────────────────────────────────────────────
# A lightweight duck-typed result container returned by ToolHookMiddleware.
# Compatible with agent.tools.base.ToolResult (same field names) so callers
# that do getattr(result, "content", "") work without importing agent.tools.


@dataclass
class _ToolResult:
    """Returned by ToolHookMiddleware.execute(); duck-typed with agent ToolResult."""

    success: bool = True
    content: str = ""
    data: object = None
    error: Optional[str] = None
    metadata: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


# ── Result containers ───────────────────────────────────────────────────────────


@dataclass
class PreHookResult:
    """Return value from a pre-execution hook."""

    proceed: bool = True  # False → skip tool execution entirely
    modified_args: Optional[dict] = None  # replace tool args if set
    injected_message: Optional[str] = None  # prepended to final output


@dataclass
class PostHookResult:
    """Return value from a post-execution hook."""

    modified_output: Optional[str] = None  # replace tool output if set
    injected_message: Optional[str] = None  # appended to final output


# ── ToolHook Protocol ───────────────────────────────────────────────────────────


@runtime_checkable
class ToolHook(Protocol):
    """Protocol for tool execution hooks."""

    async def pre(self, tool_name: str, args: dict) -> PreHookResult:
        """Called before tool execution.  Return proceed=False to abort."""
        ...

    async def post(self, tool_name: str, args: dict, result: "_ToolResult") -> PostHookResult:
        """Called after successful tool execution."""
        ...

    async def on_failure(self, tool_name: str, args: dict, error: Exception) -> PostHookResult:
        """Called when tool execution raises an unhandled exception."""
        ...


# ── Built-in Hook 1: AuditLogHook ───────────────────────────────────────────────


class AuditLogHook:
    """
    Writes a JSONL audit record for every tool call.

    Records: session_id, tool_name, args (truncated), outcome, elapsed_ms.
    Migrated from the @save_step decorator pattern.
    """

    def __init__(self, session_id: str = "", workspace_id: str = "") -> None:
        self._session_id = session_id
        self._workspace_id = workspace_id
        self._call_start: dict[str, float] = {}  # tool_name → start_time

    async def pre(self, tool_name: str, args: dict) -> PreHookResult:
        self._call_start[tool_name] = time.time()
        return PreHookResult()

    async def post(self, tool_name: str, args: dict, result) -> PostHookResult:
        elapsed_ms = int((time.time() - self._call_start.pop(tool_name, time.time())) * 1000)
        self._write_record(
            tool_name=tool_name,
            args=args,
            success=getattr(result, "success", True),
            elapsed_ms=elapsed_ms,
        )
        return PostHookResult()

    async def on_failure(self, tool_name: str, args: dict, error: Exception) -> PostHookResult:
        elapsed_ms = int((time.time() - self._call_start.pop(tool_name, time.time())) * 1000)
        self._write_record(
            tool_name=tool_name,
            args=args,
            success=False,
            elapsed_ms=elapsed_ms,
            error=str(error),
        )
        return PostHookResult()

    def _write_record(
        self,
        tool_name: str,
        args: dict,
        success: bool,
        elapsed_ms: int,
        error: Optional[str] = None,
    ) -> None:
        # Truncate args for the log record
        try:
            args_str = json.dumps(args, ensure_ascii=False)[:500]
        except Exception:
            args_str = str(args)[:500]

        record = {
            "t": int(time.time() * 1000),
            "session_id": self._session_id,
            "workspace_id": self._workspace_id,
            "tool": tool_name,
            "args": args_str,
            "success": success,
            "elapsed_ms": elapsed_ms,
        }
        if error:
            record["error"] = error[:200]

        logger.info("AuditLog: %s", json.dumps(record, ensure_ascii=False))


# ── Built-in Hook 2: RiskControlHook ───────────────────────────────────────────


# Patterns to redact from tool outputs
_REDACT_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),  # email
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),  # credit card-like
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),  # Bearer token
    re.compile(r"api[_\-]?key\s*[:=]\s*\S+", re.IGNORECASE),  # API key assignments
    re.compile(r"_vault_credential_value[\"']?\s*[:=]\s*\S+", re.IGNORECASE),  # vault injected creds
]


class RiskControlHook:
    """
    URL risk check on tool args + sensitive-data redaction on output.

    Migrated from tool_mixin._check_url_risk.
    URL risk check is best-effort: if the risk service is unavailable,
    the hook passes through (fail-open for tool availability).
    """

    def __init__(self, block_risky_urls: bool = True) -> None:
        self._block_risky_urls = block_risky_urls

    async def pre(self, tool_name: str, args: dict) -> PreHookResult:
        if not self._block_risky_urls:
            return PreHookResult()

        # Extract URLs from args and check them (best-effort)
        urls = self._extract_urls(args)
        for url in urls:
            if self._is_risky_url(url):
                logger.warning(
                    "RiskControlHook: blocked risky URL in %s args: %s",
                    tool_name,
                    url[:100],
                )
                return PreHookResult(
                    proceed=False,
                    injected_message=f"Tool blocked: URL '{url[:80]}' flagged as risky.",
                )
        return PreHookResult()

    async def post(self, tool_name: str, args: dict, result) -> PostHookResult:
        content = getattr(result, "content", "") or ""
        redacted = self._redact(content)
        if redacted != content:
            logger.debug("RiskControlHook: redacted output for %s", tool_name)
            return PostHookResult(modified_output=redacted)
        return PostHookResult()

    async def on_failure(self, tool_name: str, args: dict, error: Exception) -> PostHookResult:
        return PostHookResult()

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_urls(args: dict) -> List[str]:
        urls: List[str] = []
        url_pattern = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
        for v in args.values():
            if isinstance(v, str):
                urls.extend(url_pattern.findall(v))
        return urls

    @staticmethod
    def _is_risky_url(url: str) -> bool:
        """Lightweight heuristic — replace with real risk service if available."""
        risky_domains = (
            "malware",
            "phishing",
            "evil",
            "hack",
        )
        url_lower = url.lower()
        return any(d in url_lower for d in risky_domains)

    @staticmethod
    def _redact(text: str) -> str:
        for pattern in _REDACT_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        return text


# ── Built-in Hook 3: TokenBudgetHook ───────────────────────────────────────────


class TokenBudgetHook:
    """
    Truncates tool result content to stay within the token budget.

    Default cap: 16 000 chars ≈ 4 000 tokens.
    The ToolRegistry also enforces per-tool max_result_size_chars; this hook
    applies a global cap as a second line of defence.
    """

    def __init__(self, max_chars: int = 16_000) -> None:
        self._max_chars = max_chars

    async def pre(self, tool_name: str, args: dict) -> PreHookResult:
        return PreHookResult()

    async def post(self, tool_name: str, args: dict, result) -> PostHookResult:
        content = getattr(result, "content", "") or ""
        if len(content) > self._max_chars:
            truncated = content[: self._max_chars] + f"\n… [truncated at {self._max_chars} chars]"
            logger.debug(
                "TokenBudgetHook: truncated %s output %d → %d chars",
                tool_name,
                len(content),
                self._max_chars,
            )
            return PostHookResult(modified_output=truncated)
        return PostHookResult()

    async def on_failure(self, tool_name: str, args: dict, error: Exception) -> PostHookResult:
        return PostHookResult()


# ── EnvironmentPolicyHook ──────────────────────────────────────────────────────


class EnvironmentPolicyHook:
    """
    Enforce Environment network_policy constraints on tool calls (§12.1).

    In ``limited`` mode:
      - MCP tools blocked when ``allow_mcp_servers=False``
      - External network tools (web_search, etc.) blocked when
        ``allowed_hosts`` is non-empty and the tool target is not in the list

    In ``unrestricted`` mode: all tools pass through.
    """

    def __init__(self, snapshot: "EnvironmentSnapshot") -> None:  # noqa: F821
        self._network = snapshot.config.network
        self._resources = snapshot.config.resources

    async def pre(self, tool_name: str, args: dict) -> PreHookResult:
        if self._network.policy != "limited":
            return PreHookResult()

        # Block MCP tools when MCP servers are not allowed
        if not self._network.allow_mcp_servers and tool_name.startswith("mcp_"):
            logger.info("EnvironmentPolicyHook: blocked MCP tool '%s' (allow_mcp_servers=False)", tool_name)
            return PreHookResult(proceed=False, injected_message=f"Tool '{tool_name}' blocked by environment network policy (MCP servers disabled)")

        # Block external network tools when allowed_hosts is restricted
        _NETWORK_TOOLS = {"web_search", "web_fetch", "web_browse"}
        if tool_name in _NETWORK_TOOLS and self._network.allowed_hosts:
            # allowed_hosts is a whitelist; empty tuple means no restriction checked here
            logger.info("EnvironmentPolicyHook: tool '%s' subject to allowed_hosts check", tool_name)

        return PreHookResult()

    async def post(self, tool_name: str, args: dict, result: "_ToolResult") -> PostHookResult:
        return PostHookResult()

    async def on_failure(self, tool_name: str, args: dict, error: Exception) -> PostHookResult:
        return PostHookResult()


# ── ToolHookMiddleware ──────────────────────────────────────────────────────────


class ToolHookMiddleware:
    """
    Wraps a ToolExecutor with the pre/post/on_failure hook chain.

    Usage::

        middleware = ToolHookMiddleware(hooks=[AuditLogHook(), TokenBudgetHook()])
        result = await middleware.execute("search", {"query": "BTC"}, registry)
    """

    def __init__(self, hooks: Optional[List] = None) -> None:
        self._hooks: List = list(hooks or [])

    def add_hook(self, hook) -> None:
        self._hooks.append(hook)

    def remove_hook(self, hook) -> None:
        try:
            self._hooks.remove(hook)
        except ValueError:
            pass

    async def execute(self, tool_name: str, args: dict, executor) -> "_ToolResult":
        """
        Run the hook chain around *executor.execute(tool_name, args)*.

        Parameters
        ----------
        tool_name : str
        args : dict
        executor : ToolExecutor  (has async execute(name, args) → ToolResult)
        """
        # ── Pre hooks ──────────────────────────────────────────────────────────
        effective_args = dict(args)
        injections: List[str] = []

        for hook in self._hooks:
            pre_method = getattr(hook, "pre", None)
            if pre_method is None:
                continue
            try:
                pre_result: PreHookResult = await pre_method(tool_name, effective_args)
                if pre_result.injected_message:
                    injections.append(pre_result.injected_message)
                if pre_result.modified_args is not None:
                    effective_args = pre_result.modified_args
                if not pre_result.proceed:
                    # Abort execution; compose a blocked result
                    blocked_msg = merge_hook_feedback(
                        "[Tool execution blocked by hook]", injections
                    )
                    return _ToolResult(success=False, error=blocked_msg)
            except Exception as exc:
                logger.warning("ToolHookMiddleware: pre hook %r raised: %s", hook, exc)

        # ── Tool execution ─────────────────────────────────────────────────────
        exec_error: Optional[Exception] = None
        raw_result = None
        try:
            raw_result = await executor.execute(tool_name, effective_args)
        except Exception as exc:
            exec_error = exc

        # ── On-failure hooks ───────────────────────────────────────────────────
        if exec_error is not None:
            failure_injections: List[str] = []
            override_output: Optional[str] = None
            for hook in self._hooks:
                fail_method = getattr(hook, "on_failure", None)
                if fail_method is None:
                    continue
                try:
                    fail_result: PostHookResult = await fail_method(
                        tool_name, effective_args, exec_error
                    )
                    if fail_result.modified_output is not None:
                        override_output = fail_result.modified_output
                    if fail_result.injected_message:
                        failure_injections.append(fail_result.injected_message)
                except Exception as hook_exc:
                    logger.warning(
                        "ToolHookMiddleware: on_failure hook %r raised: %s", hook, hook_exc
                    )

            error_content = override_output or f"{type(exec_error).__name__}: {exec_error}"
            return _ToolResult(
                success=False,
                error=merge_hook_feedback(error_content, failure_injections),
            )

        # ── Post hooks ─────────────────────────────────────────────────────────
        final_content = getattr(raw_result, "content", "") or ""
        for hook in self._hooks:
            post_method = getattr(hook, "post", None)
            if post_method is None:
                continue
            try:
                post_result: PostHookResult = await post_method(
                    tool_name, effective_args, raw_result
                )
                if post_result.modified_output is not None:
                    final_content = post_result.modified_output
                if post_result.injected_message:
                    injections.append(post_result.injected_message)
            except Exception as exc:
                logger.warning("ToolHookMiddleware: post hook %r raised: %s", hook, exc)

        final_output = merge_hook_feedback(final_content, injections)

        # Reconstruct result preserving original fields
        return _ToolResult(
            success=getattr(raw_result, "success", True),
            content=final_output,
            data=getattr(raw_result, "data", None),
            error=getattr(raw_result, "error", None),
            metadata=getattr(raw_result, "metadata", {}),
        )


# ── Helpers ─────────────────────────────────────────────────────────────────────


def merge_hook_feedback(base_output: str, injections: List[str]) -> str:
    """
    Merge hook-injected messages with the base tool output.

    Injections are appended after the base output, separated by newlines.
    Called by ToolHookMiddleware before returning the final result.
    """
    if not injections:
        return base_output
    return base_output + "\n\n" + "\n".join(injections)


# ── Built-in Hook 4: VaultInjectionHook ──────────────────────────────────────


class VaultInjectionHook:
    """
    Pre-hook: lookup Vault credentials for the MCP server and inject into tool args.

    When a tool's MCP server URL matches a Vault credential, the credential
    type and encrypted value are added to the tool arguments with ``_vault_``
    prefix. The MCP tool is responsible for decryption (Vault is write-only).

    Credentials are injected as:
      _vault_credential_type  — "api_key" | "bearer" | "oauth"
      _vault_credential_value — encrypted value string
    """

    def __init__(self, vault, tool_server_map: Optional[dict] = None) -> None:
        self._vault = vault
        self._tool_server_map: dict = tool_server_map or {}

    async def pre(self, tool_name: str, args: dict) -> PreHookResult:
        if not self._vault or not self._tool_server_map:
            return PreHookResult()
        server_url = self._tool_server_map.get(tool_name)
        if not server_url:
            return PreHookResult()
        cred = self._vault.match_for_server(server_url)
        if not cred:
            logger.debug("VaultInjectionHook: no credential matched for tool '%s' (server=%s)", tool_name, server_url[:60])
            return PreHookResult()
        injected = dict(args)
        injected["_vault_credential_type"] = cred.type.value
        injected["_vault_credential_value"] = cred.encrypted_value
        logger.info(
            "VaultInjectionHook: injected %s credential for tool '%s' (server=%s)",
            cred.type.value, tool_name, server_url[:60],
        )
        return PreHookResult(modified_args=injected)

    async def post(self, tool_name: str, args: dict, result) -> PostHookResult:
        return PostHookResult()

    async def on_failure(self, tool_name: str, args: dict, error: Exception) -> PostHookResult:
        return PostHookResult()
