# -*- coding: utf-8 -*-
"""PR-F8 sub-validator 4 — flag command paths that escape the workspace.

Heuristic: scan every shlex-token of the command and reject any token
that is an absolute path NOT under ``workspace_root``, OR a relative
path containing ``..`` that would escape it.

Pure function — no actual filesystem access (only string-level path
manipulation).  Workspace-root containment is a string-prefix check
after :func:`os.path.normpath`.

If ``workspace_root=None`` the validator is a no-op (tests / contexts
that don't have a workspace boundary just want the other validators).
"""

from __future__ import annotations

import os
import shlex
from typing import Optional

from . import ValidationResult

# Tokens we never treat as paths (operators, redirects, etc).
_NON_PATH_PREFIXES = ("-", "&", ">", "<", "|", ";", "$", "\"", "'")

# Common system roots agents legitimately read; treat as ALLOW even
# when no workspace is set explicitly. This keeps the validator
# pragmatic — agents call ``cat /etc/os-release`` for diagnostics.
_ALLOWED_ABSOLUTE_PREFIXES = ("/tmp/", "/var/tmp/")


def _looks_like_path(token: str) -> bool:
    if not token:
        return False
    if token.startswith(_NON_PATH_PREFIXES):
        return False
    if token.startswith("/"):
        return True
    if "/" in token:
        return True
    if token.startswith(".."):
        return True
    return False


def _path_inside(path: str, root: str) -> bool:
    norm = os.path.normpath(path)
    norm_root = os.path.normpath(root).rstrip("/")
    if norm == norm_root:
        return True
    return norm.startswith(norm_root + os.sep)


def validate(command: str, *, workspace_root: Optional[str]) -> ValidationResult:
    if not workspace_root:
        return ValidationResult.allow()
    try:
        tokens = shlex.split(command, comments=True, posix=True)
    except ValueError:
        tokens = command.split()
    norm_root = os.path.normpath(workspace_root).rstrip("/")
    for tok in tokens[1:]:  # skip the command itself
        if not _looks_like_path(tok):
            continue
        if tok.startswith("/"):
            # Absolute path — must be inside workspace OR an explicitly-allowed
            # system path (/tmp etc).
            if any(tok.startswith(prefix) for prefix in _ALLOWED_ABSOLUTE_PREFIXES):
                continue
            if not _path_inside(tok, norm_root):
                return ValidationResult.block(
                    f"path argument {tok!r} escapes workspace {norm_root!r}"
                )
        else:
            # Relative path — resolve against workspace and check containment.
            resolved = os.path.normpath(os.path.join(norm_root, tok))
            if not _path_inside(resolved, norm_root):
                return ValidationResult.block(
                    f"relative path argument {tok!r} resolves outside workspace "
                    f"{norm_root!r}"
                )
    return ValidationResult.allow()


__all__ = ["validate"]
