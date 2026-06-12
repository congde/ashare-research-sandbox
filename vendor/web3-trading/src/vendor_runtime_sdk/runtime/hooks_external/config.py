"""S2.1 · TOML loader for external hook specs.

File layout (claw-code parity):

  ~/.aibuddy/hooks.toml         — global / user hooks
  <workspace>/.coder/hooks.toml — project hooks (run AFTER user hooks)

Each TOML file may declare arrays for the three event types:

  [[pre_tool_use]]
  name = "lint-check"
  command = "/usr/bin/lint-pre"
  timeout_seconds = 5
  allowed_tools = ["write_file", "edit_file"]
  blocked_tools = []

Validation is strict at load time so operators see config bugs at
boot rather than silently getting hooks that never fire.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Final, Iterable, List, Optional, Tuple

# Python 3.11+ ships ``tomllib`` in stdlib; we require 3.12.
import tomllib  # type: ignore[import]

from .runner import HookSpec

logger = logging.getLogger(__name__)


_VALID_EVENT_TABLES: Final[frozenset[str]] = frozenset({
    "pre_tool_use",
    "post_tool_use",
    "post_tool_use_failure",
})


@dataclass(frozen=True)
class HookSpecRoute:
    """A hook spec + its tool-routing filters."""

    spec: HookSpec
    allowed_tools: Tuple[str, ...] = ()
    blocked_tools: Tuple[str, ...] = ()

    def matches(self, tool_name: str) -> bool:
        """Return True iff this hook should fire for *tool_name*.

        ``blocked_tools`` always wins.  Empty ``allowed_tools`` =
        match all tools (the default for global / catch-all hooks).
        """
        if tool_name in self.blocked_tools:
            return False
        if not self.allowed_tools:
            return True
        return tool_name in self.allowed_tools


@dataclass(frozen=True)
class HookConfig:
    """Loaded + validated hook configuration.

    Each event-type array is ordered: user hooks first, then project
    hooks (more specific = closer to the tool = run last).
    """

    pre_tool_use: Tuple[HookSpecRoute, ...] = ()
    post_tool_use: Tuple[HookSpecRoute, ...] = ()
    post_tool_use_failure: Tuple[HookSpecRoute, ...] = ()


def load_hook_config(
    *,
    user_path: Optional[Path] = None,
    project_path: Optional[Path] = None,
) -> HookConfig:
    """Load + validate hook config from one or both TOML files.

    Either path may be ``None`` (skip) or point at a missing file
    (treated as empty).  Returns an empty :class:`HookConfig` when
    neither file contributes any hooks.

    Raises ``ValueError`` on:
      * malformed TOML
      * unknown top-level table name (``[[pre_tool]]`` typo etc.)
      * missing ``name`` / ``command`` in any entry
      * non-positive ``timeout_seconds``
    """
    user_pre, user_post, user_fail = _load_one(user_path)
    proj_pre, proj_post, proj_fail = _load_one(project_path)

    return HookConfig(
        pre_tool_use=tuple(user_pre + proj_pre),
        post_tool_use=tuple(user_post + proj_post),
        post_tool_use_failure=tuple(user_fail + proj_fail),
    )


def _load_one(
    path: Optional[Path],
) -> Tuple[List[HookSpecRoute], List[HookSpecRoute], List[HookSpecRoute]]:
    """Load a single TOML file.  Empty / missing path → empty lists."""
    if path is None or not Path(path).exists():
        return [], [], []
    raw_path = Path(path)
    try:
        body = tomllib.loads(raw_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ValueError(
            f"failed to load hook config {raw_path}: {exc}"
        ) from exc

    unknown = set(body.keys()) - _VALID_EVENT_TABLES
    if unknown:
        raise ValueError(
            f"unknown hook event table(s) in {raw_path}: "
            f"{sorted(unknown)} "
            f"(valid: {sorted(_VALID_EVENT_TABLES)})"
        )

    pre = _parse_routes(body.get("pre_tool_use") or [], raw_path, "pre_tool_use")
    post = _parse_routes(body.get("post_tool_use") or [], raw_path, "post_tool_use")
    fail = _parse_routes(
        body.get("post_tool_use_failure") or [],
        raw_path, "post_tool_use_failure",
    )
    return pre, post, fail


def _parse_routes(
    entries: Iterable[Dict[str, Any]],
    src_path: Path,
    table_name: str,
) -> List[HookSpecRoute]:
    routes: List[HookSpecRoute] = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(
                f"{src_path}: [[{table_name}]] entry #{idx} is not a table"
            )
        try:
            spec = HookSpec(
                name=str(entry.get("name") or ""),
                command=str(entry.get("command") or ""),
                timeout_seconds=float(
                    entry.get("timeout_seconds", 10.0) or 10.0
                ),
            )
        except ValueError as exc:
            raise ValueError(
                f"{src_path}: [[{table_name}]] #{idx} invalid — {exc}"
            ) from exc

        allowed = entry.get("allowed_tools") or []
        blocked = entry.get("blocked_tools") or []
        if not isinstance(allowed, list) or not all(
            isinstance(t, str) for t in allowed
        ):
            raise ValueError(
                f"{src_path}: [[{table_name}]] #{idx} allowed_tools "
                f"must be a list of strings"
            )
        if not isinstance(blocked, list) or not all(
            isinstance(t, str) for t in blocked
        ):
            raise ValueError(
                f"{src_path}: [[{table_name}]] #{idx} blocked_tools "
                f"must be a list of strings"
            )

        routes.append(HookSpecRoute(
            spec=spec,
            allowed_tools=tuple(allowed),
            blocked_tools=tuple(blocked),
        ))
    return routes


# ── Default config-path resolution ──────────────────────────────────────────


def default_user_config_path() -> Path:
    """``~/.aibuddy/hooks.toml`` — overridable via env in the future."""
    return Path.home() / ".aibuddy" / "hooks.toml"


def default_project_config_path(workspace_root: Path) -> Path:
    """``<workspace>/.coder/hooks.toml`` — claw-code parity."""
    return Path(workspace_root) / ".coder" / "hooks.toml"
