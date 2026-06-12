# -*- coding: utf-8 -*-
"""
EngineConfig — PR-E1 of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E1.

Goal
----
Centralise the small set of fields the **engine layer** (``llm/`` +
``agent/`` + ``runtime/``) reads from ``web.config``. Lets the SDK be
reused by projects that don't have ai-buddy's ``web.config`` — they
call :func:`set_engine_config` at boot to install their own values.

Fields covered by PR-E1 (kept minimal — only what is currently
consumed by engine modules ``src/llm/llm.py``, ``src/agent/dag_execution.py``)::

    openai_api_base   str
    openai_api_key    str
    llm_model_name    str
    use_azure_openai  bool
    timeout           float = 60.0

Future PRs add separate Protocols for richer state:

* PR-E3 ``ContextStore`` for Mongo / SQLite / etc.
* PR-E4 ``WorkflowRepository`` / ``TaskRepository``
* PR-E5 ``RegistryStore`` extension for Redis / Mongo clients

PR-E1 fall-back design
----------------------
When no config is installed via :func:`set_engine_config`,
:func:`get_engine_config` lazily synthesises one from
``web.config.config`` so the existing ai-buddy code path keeps working
without explicit boot wiring. **This fall-back is deleted in Phase 2**
when the engine is extracted into the standalone
``kucoin-agent-runtime-sdk`` repo and ``web.config`` is no longer in
the engine's import surface.

Thread-safety
-------------
Install at boot (single-threaded) → read everywhere (lockless after
install). ``EngineConfig`` is ``frozen=True`` so the cached reference
is safe to share across async tasks without copying. Re-installing
mid-flight is supported but logs at INFO and may cause one request
to see a torn read across two fields (the dataclass instance is
swapped atomically by ``=``, so reads always see a consistent
config).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class EngineConfigNotInstalledError(RuntimeError):
    """Raised when :func:`get_engine_config` is called before
    :func:`set_engine_config` AND no legacy ``web.config.config``
    fallback is reachable.

    SDK consumers (Phase 2 onwards) MUST call
    ``set_engine_config(EngineConfig(...))`` during boot before any
    engine module runs.
    """


@dataclass(frozen=True)
class EngineConfig:
    """Engine-side view of the small subset of config fields the
    runtime / agent / llm layers actually read.

    Frozen so the engine can cache it without worrying about mutation.
    Construct once at boot; never modify in place. Re-installation via
    :func:`set_engine_config` swaps the singleton reference atomically.
    """

    openai_api_base: str
    openai_api_key: str
    llm_model_name: str
    use_azure_openai: bool = False
    # Default 60s mirrors the hard-coded value previously passed in
    # ``DefaultLLM(timeout=60)`` at ``src/llm/llm.py:656``.
    timeout: float = 60.0
    # PR-E8 — fallback workspace_id used by engine code paths where
    # an explicit workspace_id was not supplied (e.g. background
    # persistence of an AgentVersion without an active HTTP request).
    # Empty default means "no fallback"; SDK consumers should set this
    # to whatever their product calls its default workspace (ai-buddy
    # passes "kucoin" via from_legacy_config).
    default_workspace_id: str = ""

    @classmethod
    def from_legacy_config(cls, legacy_config: object) -> "EngineConfig":
        """Adapter from ai-buddy's ``web.config.config`` AttrDict.

        ``legacy_config`` is the runtime AttrDict produced by
        :func:`web.config._dict_to_attrdict`. Reads each field with
        ``getattr`` + safe default so a missing key on the AttrDict
        doesn't crash boot. Also guards against ``None`` values
        explicitly stored on the AttrDict — common when a yaml key is
        present but unset (e.g. ``openai_api_timeout: null``); a naïve
        ``float(None)`` would crash.

        Raises:
            ValueError: when ``legacy_config`` is ``None`` (i.e.
                ``web.config`` yaml init hasn't run yet).
        """
        if legacy_config is None:
            raise ValueError(
                "EngineConfig.from_legacy_config: legacy_config is "
                "None (web.config not initialised). Call after "
                "web.config init in boot order."
            )

        def _get_str(name: str, default: str = "") -> str:
            val = getattr(legacy_config, name, default)
            return default if val is None else str(val)

        def _get_bool(name: str, default: bool = False) -> bool:
            val = getattr(legacy_config, name, default)
            return default if val is None else bool(val)

        def _get_float(name: str, default: float) -> float:
            val = getattr(legacy_config, name, default)
            return default if val is None else float(val)

        return cls(
            openai_api_base=_get_str("openai_api_base"),
            openai_api_key=_get_str("openai_api_key"),
            llm_model_name=_get_str("llm_model_name"),
            use_azure_openai=_get_bool("use_azure_openai"),
            timeout=_get_float("openai_api_timeout", 60.0),
            default_workspace_id=_get_str("default_workspace_id"),
        )


# Module-level singleton — installed by business side at boot.
_engine_config: Optional[EngineConfig] = None


def set_engine_config(cfg: EngineConfig) -> None:
    """Install the EngineConfig used by all engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot
    order is auditable. ``api_key`` is NOT logged (security: never
    write secrets to log files).
    """
    global _engine_config
    if not isinstance(cfg, EngineConfig):
        raise TypeError(
            f"set_engine_config: expected EngineConfig, "
            f"got {type(cfg).__name__}"
        )
    _engine_config = cfg
    logger.info(
        "EngineConfig installed: openai_api_base=%s llm_model_name=%s "
        "use_azure_openai=%s timeout=%.1fs default_workspace_id=%s",
        cfg.openai_api_base, cfg.llm_model_name,
        cfg.use_azure_openai, cfg.timeout,
        cfg.default_workspace_id or "<unset>",
    )


def get_engine_config() -> EngineConfig:
    """Return the installed EngineConfig.

    Fall-back path (PR-E1 only; **deleted in Phase 2** of the SDK
    extraction plan): when no config is installed, lazily synthesise
    one from ``web.config.config`` so the existing ai-buddy code keeps
    working without explicit boot wiring.

    The fall-back result is intentionally **not cached** — once
    :func:`set_engine_config` is called explicitly, the new value
    takes effect immediately on the next ``get_engine_config()`` call
    instead of being shadowed by a stale fallback snapshot.

    Raises:
        EngineConfigNotInstalledError: when no config installed AND
            ``web.config`` fallback is unavailable (the SDK-extracted
            scenario) OR ``web.config.config`` is still ``None``
            (yaml init hasn't run yet).
    """
    if _engine_config is not None:
        return _engine_config

    # PR-E1 fall-back. Deleted in Phase 2 once SDK is extracted.
    try:
        from web.config import config as _legacy
    except ImportError as exc:
        raise EngineConfigNotInstalledError(
            "EngineConfig has not been installed and web.config is "
            "not importable. Call set_engine_config(EngineConfig(...)) "
            "at boot before any engine code path runs."
        ) from exc
    if _legacy is None:
        raise EngineConfigNotInstalledError(
            "EngineConfig has not been installed and web.config.config "
            "is None (web.config not initialised yet). Either install "
            "the config via set_engine_config(...) or ensure web.config "
            "init runs first."
        )
    # Synthesise on the fly — don't cache so a later set_engine_config
    # takes effect on the next call.
    return EngineConfig.from_legacy_config(_legacy)


def reset_engine_config_for_test() -> None:
    """Test-only helper to clear the installed config between cases.

    NOT for production use — production should call
    :func:`set_engine_config` exactly once at boot.
    """
    global _engine_config
    _engine_config = None


__all__ = [
    "EngineConfig",
    "EngineConfigNotInstalledError",
    "set_engine_config",
    "get_engine_config",
    "reset_engine_config_for_test",
]
