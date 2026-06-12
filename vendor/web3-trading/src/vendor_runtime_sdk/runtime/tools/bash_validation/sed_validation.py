# -*- coding: utf-8 -*-
"""PR-F8 sub-validator 3 — ``sed`` safety guard.

Two checks:

1. ``sed -i`` (in-place edit) is a write operation; block in ReadOnly.
   The pipe form (``sed 's/.../.../g' file``) is a stream filter and
   stays allowed because it doesn't mutate ``file``.
2. Dangerous substitution scripts (``s/.*//g`` and friends) get
   warned regardless of mode — a successful run wipes the file.

Pure function — no I/O.
"""

from __future__ import annotations

import re
import shlex

from vendor_runtime_sdk.runtime.policy.permission_mode import PermissionMode

from . import ValidationResult

_DANGEROUS_SED_SCRIPTS = (
    re.compile(r"s/\.\*//g?"),
    re.compile(r"s/\.\+//g?"),
    re.compile(r"\b1,\$\s*d\b"),  # delete every line
)


def _is_sed_command(tokens: list[str]) -> bool:
    if not tokens:
        return False
    return tokens[0] == "sed"


def _has_in_place_flag(tokens: list[str]) -> bool:
    """``-i`` / ``--in-place`` / combined flags like ``-iE`` / ``-Ei``."""
    for tok in tokens[1:]:
        if not tok.startswith("-"):
            continue
        if tok in ("-i", "--in-place"):
            return True
        if tok.startswith("--in-place="):  # GNU sed supports an inline backup suffix
            return True
        # Combined short flags: -iE, -Ei
        if tok.startswith("-") and not tok.startswith("--") and "i" in tok[1:]:
            return True
    return False


def _has_dangerous_script(command: str) -> bool:
    return any(p.search(command) for p in _DANGEROUS_SED_SCRIPTS)


def validate(command: str, *, mode: PermissionMode) -> ValidationResult:
    try:
        tokens = shlex.split(command, comments=True, posix=True)
    except ValueError:
        tokens = command.split()
    if not _is_sed_command(tokens):
        return ValidationResult.allow()
    in_place = _has_in_place_flag(tokens)
    if in_place and mode <= PermissionMode.ReadOnly:
        return ValidationResult.block(
            f"sed -i mutates file in place; not permitted in ReadOnly mode: {command!r}"
        )
    if in_place and _has_dangerous_script(command):
        return ValidationResult.warn(
            f"sed -i with broad substitution may wipe the file: {command!r}"
        )
    return ValidationResult.allow()


__all__ = ["validate"]
