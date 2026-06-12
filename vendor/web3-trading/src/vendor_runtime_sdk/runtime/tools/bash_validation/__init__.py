# -*- coding: utf-8 -*-
"""PR-F8 — Bash command 6-sub-validator safety net.

Per :doc:`docs/CoderAgent-多文件任务完成率根因修复方案` §3.F8.

Each sub-module exposes a pure ``validate(command, ...)`` function that
returns a :class:`ValidationResult`. The composite
:mod:`mode_validation` chains them and emits the final decision.

Toggle: ``coder_bash_validation_v2`` (default OFF; canary).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ValidationStatus(Enum):
    """Outcome of a single sub-validator."""

    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


@dataclass(frozen=True)
class ValidationResult:
    """Pure result object — no I/O, no side effects.

    Composition (in :mod:`mode_validation`):
    - any ``BLOCK`` short-circuits the chain
    - else any ``WARN`` propagates
    - else ``ALLOW``
    """

    status: ValidationStatus
    reason: str = ""

    @classmethod
    def allow(cls, reason: str = "") -> "ValidationResult":
        return cls(status=ValidationStatus.ALLOW, reason=reason)

    @classmethod
    def warn(cls, reason: str) -> "ValidationResult":
        return cls(status=ValidationStatus.WARN, reason=reason)

    @classmethod
    def block(cls, reason: str) -> "ValidationResult":
        return cls(status=ValidationStatus.BLOCK, reason=reason)


def toggle_enabled() -> bool:
    """Return True iff ``coder_bash_validation_v2`` is on."""
    try:
        from vendor_runtime_sdk.runtime.config.toggles import get_toggles

        return bool(get_toggles().is_enabled("coder_bash_validation_v2"))
    except Exception:  # pragma: no cover — defensive
        return False


# Re-export sub-modules for ergonomic imports
# (``from runtime.tools.bash_validation import read_only_validation``).
# NB: imports placed AFTER the dataclass definitions because the
# sub-modules reference :class:`ValidationResult` / :class:`ValidationStatus`.
from . import (  # noqa: E402
    command_semantics,
    destructive_command_warning,
    mode_validation,
    path_validation,
    read_only_validation,
    sed_validation,
)

__all__ = [
    "ValidationResult",
    "ValidationStatus",
    "command_semantics",
    "destructive_command_warning",
    "mode_validation",
    "path_validation",
    "read_only_validation",
    "sed_validation",
    "toggle_enabled",
]
