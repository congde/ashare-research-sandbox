# -*- coding: utf-8 -*-
"""PR-F8 sub-validator 1 — block writes when ``mode == ReadOnly``.

Recognises common write-class commands at the leading token level
(``rm`` / ``mv`` / ``mkdir`` / ``touch`` / ``cp`` / ``chmod`` / ``chown``)
and well-known sub-commands that mutate state (``git push`` / ``git
commit``).  Also blocks ``sudo``-wrapped commands wholesale because the
wrapped command's privilege exceeds anything ReadOnly can grant.

Pure function — no I/O.
"""

from __future__ import annotations

import re
import shlex

from vendor_runtime_sdk.runtime.policy.permission_mode import PermissionMode

from . import ValidationResult

_WRITE_CLASS_COMMANDS = frozenset({
    "rm", "mv", "mkdir", "rmdir", "touch", "cp",
    "chmod", "chown", "chgrp", "ln",
    "tee",
    # Raw filesystem manipulation
    "dd", "truncate", "install",
    # Package install / system mutation
    "apt", "apt-get", "yum", "dnf", "brew", "pip", "pip3",
    "npm", "pnpm", "yarn",
    # Service / kernel
    "systemctl", "service", "kill", "killall", "pkill",
    # Archive write — extracts to filesystem
    "tar", "unzip", "gunzip", "gzip", "zip",
})

_GIT_WRITE_SUBCOMMANDS = frozenset({
    "push", "commit", "merge", "rebase", "reset", "checkout",
    "tag", "branch",
    "add", "rm", "mv",
    "stash",
    "fetch",  # mutates refs
    "pull",   # fetch + merge
    "clean",
    "init",
    # PR-F8 audit follow-up — additional write subcommands.
    "restore",       # working-tree reset to a known state
    "switch",        # branch switch (mutates working tree)
    "apply",         # apply a patch
    "cherry-pick",   # apply commit(s) onto current branch
    "revert",        # create an inverse commit
    "submodule",     # add/update/init submodule
    "worktree",      # create a new worktree
    "notes",         # add/append/edit notes
    "gc",            # mutates .git/objects
    "prune",         # mutates .git/objects
    "fsck",          # may write dangling refs
})


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, comments=True, posix=True)
    except ValueError:
        # Malformed quoting — fall back to whitespace split.
        return command.split()


# Bare ``>`` / ``>>`` are file writes (descriptor numbers like ``2>&1`` are
# ignored — they reroute file descriptors without touching disk).  We match
# at the raw-string level rather than via ``shlex`` because ``shlex`` strips
# operators in posix mode.
_FILE_REDIRECT = re.compile(r"(?<!\d)>>?\s*[^\s&0-9]")


def validate(command: str, *, mode: PermissionMode) -> ValidationResult:
    if mode > PermissionMode.ReadOnly:
        return ValidationResult.allow()
    if _FILE_REDIRECT.search(command or ""):
        return ValidationResult.block(
            f"shell file-redirect (> / >>) is a write operation; "
            f"not permitted in ReadOnly mode: {command!r}"
        )
    tokens = _tokens(command)
    if not tokens:
        return ValidationResult.allow()
    head = tokens[0]
    if head == "sudo":
        return ValidationResult.block(
            f"sudo wrappers are not permitted in ReadOnly mode: {command!r}"
        )
    if head in _WRITE_CLASS_COMMANDS:
        return ValidationResult.block(
            f"{head!r} mutates filesystem / system state; not permitted in ReadOnly mode"
        )
    if head == "git" and len(tokens) >= 2:
        sub = tokens[1].lstrip("-")
        if sub in _GIT_WRITE_SUBCOMMANDS:
            return ValidationResult.block(
                f"git {sub!r} mutates repository state; not permitted in ReadOnly mode"
            )
    return ValidationResult.allow()


__all__ = ["validate"]
