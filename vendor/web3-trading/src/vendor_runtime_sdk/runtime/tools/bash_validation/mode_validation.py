# -*- coding: utf-8 -*-
"""PR-F8 sub-validator 6 — composite that runs the other 5.

Composition rules:

1. ``destructive_command_warning`` runs FIRST and unconditionally —
   ``rm -rf /`` blocks regardless of mode.
2. ``read_only_validation`` runs next — gates write-class commands when
   mode == ReadOnly.
3. ``sed_validation`` is mode-aware (in-place sed in ReadOnly).
4. ``path_validation`` runs when ``workspace_root`` is supplied.
5. (``command_semantics`` is consulted by the F7 enforcer outside this
   composite — exposed but not chained here.)

Returns the FIRST blocking result; otherwise the FIRST warning result;
otherwise allow.
"""

from __future__ import annotations

from typing import Optional

from vendor_runtime_sdk.runtime.policy.permission_mode import PermissionMode

from . import (
    ValidationResult,
    ValidationStatus,
    destructive_command_warning,
    path_validation,
    read_only_validation,
    sed_validation,
)


def validate(
    command: str,
    *,
    mode: PermissionMode,
    workspace_root: Optional[str] = None,
) -> ValidationResult:
    chain = [
        destructive_command_warning.validate(command),
        read_only_validation.validate(command, mode=mode),
        sed_validation.validate(command, mode=mode),
        path_validation.validate(command, workspace_root=workspace_root),
    ]
    first_warn: Optional[ValidationResult] = None
    for result in chain:
        if result.status == ValidationStatus.BLOCK:
            return result
        if result.status == ValidationStatus.WARN and first_warn is None:
            first_warn = result
    return first_warn or ValidationResult.allow()


__all__ = ["validate"]
