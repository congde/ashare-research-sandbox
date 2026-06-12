# -*- coding: utf-8 -*-
"""Sprint 7 PR-1 · MCP server config schema.

Pydantic model that doubles as the security perimeter — every loaded
external MCP server config goes through these validators before any
subprocess spawn or HTTP connection.

Hard rules (per docs/Sprint7-MCP-工具扩展技术方案.md §5.2 + §9):
  1. stdio command[0] cannot be a shell wrapper (sh / bash / zsh / fish)
     because the runner will spawn via exec; a shell wrapper means the
     operator wants shell-string evaluation which is the injection
     vector we're guarding against.
  2. Args may not contain shell metacharacters (`; | & > <` redirect
     siblings, `$` substitution, backticks, newlines) — these have no
     meaning in exec mode and being there is a strong signal of
     misconfig / templating bug / outright injection attempt.
  3. HTTP url must be ``https://`` and must clear the optional
     ``host_allowlist`` (defence against SSRF + redirect-to-internal).
  4. Auth secrets reference env vars only — no inline ``value`` field
     so a fat-fingered config never leaks a token in a toml file
     someone might commit.
  5. Top level capped at 8 servers per user (D2 decision in plan).
  6. ``namespace_prefix`` collisions rejected (would cause tool name
     collisions in registry).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class SchemaValidationError(ValueError):
    """Raised by loader when a top-level rule fails (delegates to
    pydantic ValidationError for field-level errors).  Distinct
    type so callers can branch."""


# ── stdio command safety ──────────────────────────────────────────────────


_FORBIDDEN_SHELL_BASENAMES = frozenset({
    "sh", "bash", "zsh", "ksh", "fish", "dash", "ash",
    "csh", "tcsh", "powershell", "pwsh", "cmd", "cmd.exe",
})
# Public re-export so downstream validators (test suites + expert-kit
# YAML invariant checks) can pin against the SAME shell-wrapper
# allowlist instead of hand-copying the list and silently drifting
# (e.g., test forgot ``ksh`` → production schema rejects but test
# passes — vector for false-positive PRs).
FORBIDDEN_SHELL_BASENAMES = _FORBIDDEN_SHELL_BASENAMES

# shell metacharacters that have no business in an exec-form command.
# Includes: redirect (>), pipe (|), bg (&), separator (;), substitution
# ($, backtick), newline, AND comparison operators (<).  Allowed
# characters: alnum + path separators + dash + underscore + dot + space
# (space is fine inside one arg) + equals (for `--flag=value`) + comma.
_SHELL_METACHAR_RE = re.compile(r"[;|&`$\n\r><]")
SHELL_METACHAR_RE = _SHELL_METACHAR_RE  # public re-export — same rationale as above


def _basename(path: str) -> str:
    """Cross-platform basename without pulling pathlib here (light)."""
    seg = path.replace("\\", "/").rstrip("/")
    if "/" in seg:
        seg = seg.rsplit("/", 1)[-1]
    return seg


def _validate_stdio_command(cmd: List[str]) -> List[str]:
    if not cmd:
        raise ValueError("command must not be empty")
    head = cmd[0]
    if not isinstance(head, str) or not head.strip():
        raise ValueError("command[0] must be a non-empty string")
    base = _basename(head).lower()
    if base in _FORBIDDEN_SHELL_BASENAMES:
        raise ValueError(
            f"command[0]={head!r} is a shell wrapper "
            f"({sorted(_FORBIDDEN_SHELL_BASENAMES)}); use exec form "
            "with the actual binary instead (security: shell wrappers "
            "are the injection vector)"
        )
    for i, arg in enumerate(cmd):
        if not isinstance(arg, str):
            raise ValueError(f"command[{i}] must be a string, got {type(arg).__name__}")
        if _SHELL_METACHAR_RE.search(arg):
            raise ValueError(
                f"command[{i}]={arg!r} contains shell metacharacters "
                f"(; | & ` $ < > newline); these have no meaning in "
                "exec mode and indicate a misconfig or injection attempt"
            )
    return cmd


# ── namespace_prefix safety ───────────────────────────────────────────────


# Lowercase letter start, then lowercase / digit / single underscore.
# Reject double-underscore because we use `__` as the tool-name
# separator (`{prefix}__{tool}`); a prefix containing __ would
# create ambiguous tool names.
_NAMESPACE_PREFIX_RE = re.compile(r"^[a-z][a-z0-9_]*[a-z0-9]$|^[a-z]$")


def _validate_namespace_prefix(p: str) -> str:
    if not isinstance(p, str) or not p:
        raise ValueError("namespace_prefix must be a non-empty string")
    if "__" in p:
        raise ValueError(
            f"namespace_prefix={p!r} cannot contain '__' "
            "(reserved as tool-name separator)"
        )
    if not _NAMESPACE_PREFIX_RE.fullmatch(p):
        raise ValueError(
            f"namespace_prefix={p!r} must match [a-z][a-z0-9_]* "
            "(lowercase identifier-like; no dot / slash / space / "
            "uppercase / leading digit)"
        )
    return p


# ── HTTP url safety ───────────────────────────────────────────────────────


_ALLOWED_URL_SCHEMES = frozenset({"https"})


def _validate_https_url(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(
            f"url scheme must be one of {sorted(_ALLOWED_URL_SCHEMES)}; "
            f"got {parsed.scheme!r} (defense against SSRF + non-http exfil)"
        )
    if not parsed.hostname:
        raise ValueError(f"url={raw!r} has no host")
    return raw


# ── Auth ──────────────────────────────────────────────────────────────────


class AuthSpec(BaseModel):
    """HTTP MCP server auth descriptor — env-only references, no inline secrets."""

    # forbid extra fields so operator can't sneak in `value="abc"` and
    # commit a secret to toml.
    model_config = ConfigDict(extra="forbid")

    type: Literal["bearer"] = "bearer"
    env: str = Field(..., min_length=1, description="Env var name holding the secret")


# ── McpServerSpec ─────────────────────────────────────────────────────────


class McpServerSpec(BaseModel):
    """One MCP server entry.

    Either ``transport="stdio"`` (with ``command``) OR
    ``transport="http"`` (with ``url``).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Display name (human-readable)")
    namespace_prefix: str = Field(..., description="Tool name prefix; LLM sees {prefix}__{tool}")
    transport: Literal["stdio", "http"]
    enabled: bool = True
    restart_on_crash: bool = True
    max_restarts_per_hour: int = Field(5, ge=0, le=100)  # D6 default

    # stdio-only
    command: Optional[List[str]] = None
    env: Dict[str, str] = Field(default_factory=dict)

    # http-only
    url: Optional[str] = None
    auth: Optional[AuthSpec] = None
    host_allowlist: List[str] = Field(default_factory=list)
    timeout_s: int = Field(30, ge=1, le=300)

    # Sprint S-EK-V1 PR 14 — kit attribution for per-user MCP specs.
    # Set by ``_user_row_to_spec`` from the Mongo row's
    # ``source_kit_id`` field. Empty/None for operator-toml specs
    # (which aren't tied to a kit). Used by ``register_user_mcp_tools``
    # to filter tools by @-mentioned kits so the LLM only sees the
    # kit tool surface the user explicitly summoned.
    source_kit_id: Optional[str] = None

    # ── field-level validators ─────────────────────────────────────────────

    @field_validator("namespace_prefix")
    @classmethod
    def _check_namespace_prefix(cls, v: str) -> str:
        return _validate_namespace_prefix(v)

    @field_validator("command")
    @classmethod
    def _check_command(cls, v):
        if v is None:
            return v
        return _validate_stdio_command(v)

    # ── transport / fields cross-validation ────────────────────────────────

    @model_validator(mode="after")
    def _check_transport_consistency(self):
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("stdio transport requires non-empty `command`")
            if self.url is not None:
                raise ValueError("stdio transport does not accept `url`")
        elif self.transport == "http":
            if not self.url:
                raise ValueError("http transport requires `url`")
            if self.command is not None:
                raise ValueError("http transport does not accept `command`")
            _validate_https_url(self.url)
            # host_allowlist check
            if self.host_allowlist:
                host = urlparse(self.url).hostname
                if host not in self.host_allowlist:
                    raise ValueError(
                        f"url host={host!r} not in host_allowlist="
                        f"{self.host_allowlist} (defense against redirect / SSRF)"
                    )
        return self


# ── Top-level config (toml file root) ─────────────────────────────────────


_MAX_SERVERS_PER_USER = 8  # D2 decision


class McpConfigFile(BaseModel):
    """Root of ~/.aibuddy/mcp_servers.toml."""

    model_config = ConfigDict(extra="forbid")

    server: List[McpServerSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_collection(self):
        # Server count cap (D2 decision: 8/user)
        if len(self.server) > _MAX_SERVERS_PER_USER:
            raise ValueError(
                f"too many servers ({len(self.server)}); "
                f"max {_MAX_SERVERS_PER_USER} per user (anti-abuse cap)"
            )
        # Duplicate namespace_prefix rejection
        seen: Dict[str, str] = {}
        for s in self.server:
            if s.namespace_prefix in seen:
                raise ValueError(
                    f"duplicate namespace_prefix={s.namespace_prefix!r} "
                    f"(used by {seen[s.namespace_prefix]!r} and {s.name!r}); "
                    "would cause tool name collisions"
                )
            seen[s.namespace_prefix] = s.name
        return self


__all__ = [
    "AuthSpec",
    "McpConfigFile",
    "McpServerSpec",
    "SchemaValidationError",
]
