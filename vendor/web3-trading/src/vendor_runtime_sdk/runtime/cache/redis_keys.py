"""Redis key name builders — enforce the ``ws:{workspace_id}:...`` /
``global:...`` prefix convention from ``docs/服务端数据本地化整改技术方案.md`` §4.

Two public helpers:

``ws_key(module, *parts)``
    Build a workspace-scoped key. The workspace_id is resolved from the
    :mod:`web.middleware` context var. **Fails fast** with ``ValueError``
    if the context is unset or the literal string ``"global"`` — callers
    outside HTTP request scope (Celery tasks, CLI scripts) must invoke
    ``set_ownership()`` first. Silent fallback to a placeholder
    workspace_id was rejected during review because it made cross-workspace
    leakage invisible.

``global_key(module, *parts)``
    Build a deliberately-global key (OAuth state, cluster registry,
    tenant-scoped token, cross-workspace rate limit). The call site MUST
    document *why* it is global in the surrounding module docstring —
    the CI lint in ``scripts/check_redis_keys.py`` scans for this.

Backwards compatibility — :func:`legacy_dual_write_keys` returns BOTH the
new key and the original legacy key during the double-write migration
window (tri-state ``redis_key_normalized`` selector = ``migration``). See
§4.4 of the plan.
"""
from __future__ import annotations

from vendor_runtime_sdk.runtime.config.toggles import get_redis_key_mode

__all__ = [
    "ws_key",
    "global_key",
    "legacy_dual_write_keys",
    "is_normalized_key",
    "current_mode",
]

_WS_PREFIX = "ws"
_GLOBAL_PREFIX = "global"
# Reserved words rejected as workspace_id (checked case-insensitively after
# strip). An empty/whitespace-only string is caught separately so the error
# message can distinguish "unset" from "placeholder".
_RESERVED_WS_ID = frozenset({"global", "default", "none", "null"})


def _resolve_workspace_id() -> str:
    """Pull workspace_id from the ownership context var. Lazy-imported so
    :mod:`runtime.cache.redis_keys` stays importable from Celery / CLI scripts
    that may not have the web layer on the module path yet."""
    # PR-E2 (SDK extraction §5 PR-E2): get_workspace_id is now sourced
    # from runtime.context.  The legacy web.middleware.get_workspace_id
    # continues to populate the same value via the fallback path, so
    # the runtime behaviour is unchanged in Phase 0.  Phase 2 removes
    # the fallback when web/ leaves the engine import surface.
    try:
        from vendor_runtime_sdk.runtime.context import get_workspace_id
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "runtime.cache.redis_keys requires runtime.context.get_workspace_id; "
            "if you are inside a Celery worker, ensure runtime.context is "
            f"on the PYTHONPATH. Underlying import error: {exc}"
        ) from exc
    return get_workspace_id() or ""


def ws_key(module: str, *parts: str) -> str:
    """Build ``ws:{workspace_id}:{module}:{...parts}`` — workspace-scoped key.

    Raises:
        ValueError — if workspace_id is empty or a reserved placeholder.
    """
    if not module:
        raise ValueError("ws_key: module must be a non-empty string")
    ws = _resolve_workspace_id().strip()
    if not ws or ws.lower() in _RESERVED_WS_ID:
        raise ValueError(
            f"ws_key requires a non-placeholder workspace_id, got {ws!r}. "
            "If this key is intentionally global, use global_key() instead. "
            "If this is a Celery / CLI call site, call set_ownership(...) first."
        )
    return ":".join((_WS_PREFIX, ws, module, *(_coerce(p) for p in parts)))


def global_key(module: str, *parts: str) -> str:
    """Build ``global:{module}:{...parts}`` — deliberately non-workspace-scoped.

    Document *why* in the caller module's docstring (see §4.1 rule 2).
    """
    if not module:
        raise ValueError("global_key: module must be a non-empty string")
    return ":".join((_GLOBAL_PREFIX, module, *(_coerce(p) for p in parts)))


def legacy_dual_write_keys(new_key: str, legacy_key: str) -> tuple[str, ...]:
    """Return the tuple of keys that should be written during dual-write.

    * ``off``       — ``(legacy_key,)``  (pre-remediation baseline)
    * ``migration`` — ``(new_key, legacy_key)``
    * ``on``        — ``(new_key,)``

    Callers typically do::

        for key in legacy_dual_write_keys(new, old):
            await redis.set(key, value, ex=ttl)
    """
    mode = get_redis_key_mode()
    if mode == "on":
        return (new_key,)
    if mode == "migration":
        return (new_key, legacy_key) if new_key != legacy_key else (new_key,)
    return (legacy_key,)


def is_normalized_key(key: str) -> bool:
    """True if the key starts with an approved prefix."""
    if not isinstance(key, str):
        return False
    return key.startswith(f"{_WS_PREFIX}:") or key.startswith(f"{_GLOBAL_PREFIX}:")


def current_mode() -> str:
    """Expose the current tri-state mode — convenience for tests / debug logs."""
    return get_redis_key_mode()


def _coerce(part: object) -> str:
    if part is None:
        raise ValueError("redis key parts cannot be None")
    s = str(part)
    if not s:
        raise ValueError("redis key parts cannot be empty")
    if ":" in s:
        raise ValueError(
            f"redis key part {s!r} contains ':' — use separate *parts arguments"
        )
    return s
