# -*- coding: utf-8 -*-
"""PR-F8 sub-validator 2 — always-on destructive command guard.

Catches the catastrophic-but-rare commands that no PermissionMode
should ever allow:

* ``rm -rf /`` and equivalents (with --recursive / --force long forms)
* ``mkfs`` / ``fdisk`` (filesystem rewrites)
* ``dd if=... of=/dev/...`` (raw device writes)
* fork bombs (`:(){ :|:& };:`)
* ``> /dev/sd*`` / ``>> /dev/sd*`` (redirect into raw device)

Even ``DangerFullAccess`` mode does NOT bypass this validator — these
commands kill systems and are virtually never legitimate inside an LLM-
driven CoderAgent. Operators who need them should run them outside the
agent.
"""

from __future__ import annotations

import re

from . import ValidationResult

_RM_RF_ROOT = re.compile(
    r"\brm\s+(?:-[^\s]*r[^\s]*f[^\s]*|-[^\s]*f[^\s]*r[^\s]*|--recursive\s+--force|--force\s+--recursive)"
    r"\s+/\S*",
    re.IGNORECASE,
)

_MKFS = re.compile(r"\bmkfs(?:\.[a-z0-9]+)?\b", re.IGNORECASE)
_FDISK = re.compile(r"\b(?:fdisk|parted|gdisk)\b", re.IGNORECASE)

_DD_TO_DEVICE = re.compile(
    r"\bdd\b[^\n]*\bof=\s*/dev/(?:sd[a-z]|nvme|hd[a-z])",
    re.IGNORECASE,
)

# Fork bomb: :(){ :|:& };:  with optional whitespace
_FORK_BOMB = re.compile(r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:\s*&[^}]*\}\s*;\s*:")

_REDIRECT_DEVICE = re.compile(
    r">>?\s*/dev/(?:sd[a-z]|nvme|hd[a-z])",
    re.IGNORECASE,
)


def validate(command: str) -> ValidationResult:
    cmd = command or ""
    if _RM_RF_ROOT.search(cmd):
        return ValidationResult.block(
            f"refusing rm -rf against /; command: {command!r}"
        )
    if _MKFS.search(cmd):
        return ValidationResult.block(
            f"refusing filesystem-format command (mkfs); command: {command!r}"
        )
    if _FDISK.search(cmd):
        return ValidationResult.block(
            f"refusing partition-table editor; command: {command!r}"
        )
    if _DD_TO_DEVICE.search(cmd):
        return ValidationResult.block(
            f"refusing dd to raw device; command: {command!r}"
        )
    if _FORK_BOMB.search(cmd):
        return ValidationResult.block(
            f"fork bomb pattern detected; command: {command!r}"
        )
    if _REDIRECT_DEVICE.search(cmd):
        return ValidationResult.block(
            f"refusing redirect to raw device; command: {command!r}"
        )
    return ValidationResult.allow()


__all__ = ["validate"]
