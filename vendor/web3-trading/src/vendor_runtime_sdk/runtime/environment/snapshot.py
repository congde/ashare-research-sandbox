# -*- coding: utf-8 -*-
"""
EnvironmentSnapshot — §5.5.1 / §5.5.2 (Phase 4 P0)

Session creation-time snapshot of the Environment's non-sensitive runtime
constraints.  Used for immutability: updating/archiving the live Environment
does NOT affect already-running Sessions.

Design rules (§5.5.1):
  - env_vars are NEVER stored in the snapshot — only their sha256 fingerprint
    (for drift detection).
  - Snapshot is taken atomically at Session creation time.
  - Snapshot is immutable once written.

Resume rules (§5.5.2):
  - On Session resume, the live Environment is checked:
    * If the live Environment no longer exists → fail-closed, refuse resume.
    * If env_vars_sha256 has drifted → log warning but allow (Vault credentials
      are always fetched live per §12.2 design intent).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from vendor_runtime_sdk.runtime.environment.environment import Environment, EnvironmentConfig


@dataclass
class EnvironmentSnapshot:
    """
    Immutable snapshot of an Environment captured at Session creation.

    Stored inside Session.creation_snapshot.environment_config.
    """

    environment_id: str
    config: EnvironmentConfig
    env_vars_sha256: str  # fingerprint only — never raw values
    snapshot_at: float = field(default_factory=time.time)

    @classmethod
    def capture(cls, env: Environment) -> EnvironmentSnapshot:
        """Create a snapshot from a live Environment at Session creation time."""
        return cls(
            environment_id=env.environment_id,
            config=env.to_config(),
            env_vars_sha256=env.env_vars_sha256(),
            snapshot_at=time.time(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment_id": self.environment_id,
            "environment_config": self.config.to_dict(),
            "env_vars_sha256": self.env_vars_sha256,
            "snapshot_at": self.snapshot_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> EnvironmentSnapshot:
        return cls(
            environment_id=d["environment_id"],
            config=EnvironmentConfig.from_dict(d.get("environment_config", {})),
            env_vars_sha256=d.get("env_vars_sha256", ""),
            snapshot_at=d.get("snapshot_at", 0),
        )


class ResumeChecker:
    """
    Fail-closed resume validation — §5.5.2.

    Before resuming a Session, verify the referenced Environment still
    exists and is accessible.  If not, refuse to resume.
    """

    @staticmethod
    def check(
        snapshot: EnvironmentSnapshot,
        live_env: Optional[Environment],
    ) -> "ResumeCheckResult":
        """
        Validate that the live Environment is still compatible with the snapshot.

        Returns ResumeCheckResult with allowed=False if the Environment is
        missing or archived (fail-closed).  Drift in env_vars is logged as
        a warning but does not block resume (Vault credentials are fetched live).
        """
        if live_env is None:
            return ResumeCheckResult(
                allowed=False,
                reason=f"Environment '{snapshot.environment_id}' no longer exists",
            )

        if live_env.is_archived:
            return ResumeCheckResult(
                allowed=False,
                reason=f"Environment '{snapshot.environment_id}' has been archived",
            )

        try:
            return ResumeChecker._check_compatibility(snapshot, live_env)
        except Exception as exc:
            return ResumeCheckResult(
                allowed=False,
                reason=f"Environment config validation error: {type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _check_compatibility(
        snapshot: EnvironmentSnapshot,
        live_env: Environment,
    ) -> "ResumeCheckResult":
        """Internal: compare snapshot with live env. May raise on corrupt config."""
        warnings: list[str] = []

        # Check env_vars drift
        current_sha = live_env.env_vars_sha256()
        if snapshot.env_vars_sha256 and current_sha != snapshot.env_vars_sha256:
            warnings.append(
                f"env_vars have changed since session creation "
                f"(snapshot: {snapshot.env_vars_sha256[:12]}…, "
                f"current: {current_sha[:12]}…)"
            )

        # Check config drift (informational; does not block resume)
        live_config = live_env.to_config()
        if live_config.base_image != snapshot.config.base_image:
            warnings.append(
                f"base_image changed: {snapshot.config.base_image} → {live_config.base_image}"
            )

        return ResumeCheckResult(allowed=True, warnings=warnings)


@dataclass
class ResumeCheckResult:
    """Result of a fail-closed resume validation."""

    allowed: bool
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
