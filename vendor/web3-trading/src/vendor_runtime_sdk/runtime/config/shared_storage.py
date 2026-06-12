"""Shared-storage env resolver.

Central source of truth for the eight env vars introduced by
``docs/服务端数据本地化整改技术方案.md`` §2.

All callers (WorkspaceManager, CheckpointManager, TrajectoryRecorder,
AuditLog hook, agent sandbox file tools, Coder milestone executor, the
FastAPI lifespan pre-flight) MUST go through these helpers — resolving
``os.environ`` at each call site invited drift in the original code and
made it hard to unit-test.

Resolution rules:
    * ``ENVIRONMENT=local`` (default) — env var may be unset; we fall back
        to a writable user path (``~/.ai-buddy/shareData``).
  * ``ENVIRONMENT=production`` — env vars SHOULD be set by the k8s manifest
        (`/app/ai-buddy/shareData/...``). When unset, we still fall back to
        ``/app/ai-buddy/shareData``. Pre-flight (``shared_storage_enforce``)
        toggle) is what actually refuses to boot on a misconfigured pod.
    This module itself never raises — it just reports what it found.

The helpers return ``pathlib.Path`` objects; they do **not** create the
directories. Callers (especially ones on the hot path) should use
``path.mkdir(parents=True, exist_ok=True)`` on first use.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Env var names (single source of truth) ────────────────────────────────────

ENV_ENVIRONMENT = "ENVIRONMENT"
ENV_POD_ID = "POD_ID"
ENV_SHARED_DATA_ROOT = "AIBUDDY_SHARED_DATA_ROOT"
ENV_WORKSPACE_BASE = "AIBUDDY_WORKSPACE_BASE"
ENV_AGENT_WORKSPACE_ROOT = "AGENT_WORKSPACE_ROOT"
ENV_CHECKPOINT_BASE = "AIBUDDY_CHECKPOINT_BASE"
ENV_TRAJECTORY_BASE = "AIBUDDY_TRAJECTORY_BASE"
ENV_AUDIT_FALLBACK_BASE = "AIBUDDY_AUDIT_FALLBACK_BASE"

# Required envs checked by pre-flight (§5)
REQUIRED_PRODUCTION_ENVS: tuple[str, ...] = (
    ENV_SHARED_DATA_ROOT,
    ENV_WORKSPACE_BASE,
    ENV_AGENT_WORKSPACE_ROOT,
    ENV_CHECKPOINT_BASE,
)

# Hard-coded production mount — pre-flight asserts every required path
# resolves under this prefix.
PRODUCTION_MOUNT_PREFIX = "/app/ai-buddy/shareData"

# Default fallback base when env var is unset.
# In production, k8s envs should point to /app/ai-buddy/shareData.
# For local/dev, default to a writable home directory.
_DEFAULT_LOCAL_SHARED_DATA_ROOT = Path.home() / ".ai-buddy" / "shareData"


def is_production() -> bool:
    """True iff ``ENVIRONMENT=production``. Any other value (incl. unset) = dev/local."""
    return os.environ.get(ENV_ENVIRONMENT, "local").strip().lower() == "production"


def get_pod_id() -> str:
    """Return POD_ID (``dev-local`` if unset). Used for per-pod audit fallback files."""
    return os.environ.get(ENV_POD_ID, "dev-local").strip() or "dev-local"


def shared_data_root() -> Path:
    """Resolve ``AIBUDDY_SHARED_DATA_ROOT``; fall back to default shareData path."""
    val = os.environ.get(ENV_SHARED_DATA_ROOT)
    if val:
        return Path(val)
    if is_production():
        return Path(PRODUCTION_MOUNT_PREFIX)
    return _DEFAULT_LOCAL_SHARED_DATA_ROOT


def workspace_base() -> Path:
    """Resolve workspace root (``AIBUDDY_WORKSPACE_BASE``)."""
    val = os.environ.get(ENV_WORKSPACE_BASE)
    if val:
        return Path(val)
    return shared_data_root() / "workspaces"


def agent_workspace_root() -> Path:
    """Resolve agent sandbox root (``AGENT_WORKSPACE_ROOT``).

    Note: pre-remediation default was ``/tmp/agent_workspace``. With this
    helper, ``ENVIRONMENT=local`` resolves to
    ``~/.ai-buddy/shareData/agent-workspace`` when env unset.
    """
    val = os.environ.get(ENV_AGENT_WORKSPACE_ROOT)
    if val:
        return Path(val)
    return shared_data_root() / "agent-workspace"


def checkpoint_base() -> Path:
    """Resolve checkpoint blob base (``AIBUDDY_CHECKPOINT_BASE``)."""
    val = os.environ.get(ENV_CHECKPOINT_BASE)
    if val:
        return Path(val)
    return shared_data_root() / "checkpoints"


def trajectory_base() -> Path:
    """Resolve trajectory JSONL fallback base (``AIBUDDY_TRAJECTORY_BASE``).

    Primary path in production is Mongo; this filesystem path is for the
    fallback-only write when Mongo is unreachable.
    """
    val = os.environ.get(ENV_TRAJECTORY_BASE)
    if val:
        return Path(val)
    return shared_data_root() / "trajectories"


def audit_fallback_base() -> Path:
    """Resolve AuditLog Mongo-outage fallback base (``AIBUDDY_AUDIT_FALLBACK_BASE``).

    Audit fallback writes use ``{base}/{pod_id}/{YYYYMMDD}.jsonl`` so multi-pod
    writers never share a file.
    """
    val = os.environ.get(ENV_AUDIT_FALLBACK_BASE)
    if val:
        return Path(val)
    return shared_data_root() / "audit-fallback"


def collect_violations() -> list[str]:
    """Return a list of human-readable violations for the pre-flight check.

    An empty list means every required env points somewhere sane for
    production. Applied only when ``is_production() and shared_storage_enforce``.

    Rules:
      * every ``REQUIRED_PRODUCTION_ENVS`` must be set
      * resolved path MUST NOT contain a ``/tmp`` segment
      * resolved path MUST NOT start with ``$HOME``
      * resolved path MUST start with ``PRODUCTION_MOUNT_PREFIX``
    """
    violations: list[str] = []
    home_str = str(Path.home())
    for name in REQUIRED_PRODUCTION_ENVS:
        val = os.environ.get(name)
        if not val:
            violations.append(f"{name} unset")
            continue
        try:
            resolved = Path(val).resolve()
        except Exception as exc:  # pragma: no cover — extremely unusual
            violations.append(f"{name}={val!r} unresolvable: {exc}")
            continue
        if "tmp" in resolved.parts or "/tmp" in str(resolved):
            violations.append(f"{name}={val} points to /tmp")
        if str(resolved).startswith(home_str):
            violations.append(f"{name}={val} points to HOME")
        if not str(resolved).startswith(PRODUCTION_MOUNT_PREFIX):
            violations.append(f"{name}={val} not under {PRODUCTION_MOUNT_PREFIX}")
    return violations
