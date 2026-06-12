# -*- coding: utf-8 -*-
"""PR-F8 sub-validator 5 — classify a command into a privilege bucket.

Returns a :class:`CommandIntent` whose ``required_mode`` feeds into the
F7 :class:`PermissionEnforcer.check_with_required_mode` API. Buckets:

* ``read``    → :attr:`PermissionMode.ReadOnly`
* ``write``   → :attr:`PermissionMode.WorkspaceWrite`
* ``network`` → :attr:`PermissionMode.DangerFullAccess`
* ``danger``  → :attr:`PermissionMode.DangerFullAccess`
* ``unknown`` → :attr:`PermissionMode.DangerFullAccess` (conservative —
  unrecognised commands MUST clear the highest bar)
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Literal

from vendor_runtime_sdk.runtime.policy.permission_mode import PermissionMode

_READ_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "less", "more",
    "stat", "file", "wc", "du", "df",
    "find", "grep", "rg", "ag", "ack",
    "echo", "printf",
    "pwd", "whoami", "id", "uname", "hostname",
    "date", "tty", "type", "which",
    "diff", "cmp", "sort", "uniq", "awk", "tr", "cut",
    "xxd", "hexdump", "od",
    # Read-only language tools
    "python", "python3", "node", "ruby", "perl",
})

_WRITE_COMMANDS = frozenset({
    "rm", "mv", "mkdir", "rmdir", "touch", "cp",
    "chmod", "chown", "chgrp", "ln",
    "tar", "zip", "unzip", "gzip", "gunzip",
    "tee", "patch",
    # PR-F8 audit follow-up — raw FS manipulation.
    "dd", "truncate", "install",
})

_NETWORK_COMMANDS = frozenset({
    "curl", "wget", "fetch",
    "ssh", "scp", "sftp", "rsync",
    "nc", "ncat", "socat",
    "ping", "traceroute", "dig", "nslookup",
    "ftp", "telnet",
})

_DANGER_COMMANDS = frozenset({
    "sudo", "su",
    "systemctl", "service", "launchctl",
    "kill", "killall", "pkill",
    "mount", "umount",
    "iptables", "ufw",
    "passwd",
})


@dataclass(frozen=True)
class CommandIntent:
    """Classification result + the required PermissionMode it implies."""

    category: Literal["read", "write", "network", "danger", "unknown"]
    required_mode: PermissionMode


_GIT_READ_SUBCOMMANDS = frozenset({"status", "diff", "log", "show", "blame", "ls-files"})


def classify(command: str) -> CommandIntent:
    try:
        tokens = shlex.split(command, comments=True, posix=True)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return CommandIntent(category="unknown", required_mode=PermissionMode.DangerFullAccess)
    head = tokens[0]
    # ``git`` is a multi-mode tool; classify by sub-command.
    if head == "git" and len(tokens) >= 2:
        sub = tokens[1].lstrip("-")
        if sub in _GIT_READ_SUBCOMMANDS:
            return CommandIntent(category="read", required_mode=PermissionMode.ReadOnly)
        # Anything else (push/commit/...) is at least workspace-write.
        return CommandIntent(category="write", required_mode=PermissionMode.WorkspaceWrite)
    if head in _DANGER_COMMANDS:
        return CommandIntent(category="danger", required_mode=PermissionMode.DangerFullAccess)
    if head in _NETWORK_COMMANDS:
        return CommandIntent(category="network", required_mode=PermissionMode.DangerFullAccess)
    if head in _WRITE_COMMANDS:
        return CommandIntent(category="write", required_mode=PermissionMode.WorkspaceWrite)
    if head in _READ_COMMANDS:
        return CommandIntent(category="read", required_mode=PermissionMode.ReadOnly)
    # Conservative default: unknown commands get the strictest mode.
    return CommandIntent(category="unknown", required_mode=PermissionMode.DangerFullAccess)


__all__ = ["CommandIntent", "classify"]
