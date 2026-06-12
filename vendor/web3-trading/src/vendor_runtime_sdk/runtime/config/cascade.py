"""
Config Cascade — three-tier configuration merging (§3.4)

Load order (later overrides earlier):
  1. YAML — conf/default.yaml as baseline
  2. Env Vars — override YAML values (UPPER_CASE keys, double-underscore nesting)
  3. Apollo — override all (production/SIT only; bypassed locally)

Local dev: Apollo bypassed (APOLLO_HOSTS not set), Env > YAML
Production: Apollo > Env > YAML

This module provides utilities to *inspect* the cascade result and to
resolve individual keys across the three tiers.  The actual YAML parsing
and Apollo client live in web/config.py and libs/apollo.py respectively;
this module acts as a thin documentation + resolution helper so callers
can query "where did this value come from?" for debugging.
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ConfigSource(str, Enum):
    """Which tier supplied the value for a given key."""

    DEFAULT = "default"  # hard-coded fallback
    YAML = "yaml"  # conf/default.yaml
    ENV = "env"  # environment variable
    APOLLO = "apollo"  # Apollo config center


def _get_attr_or_key(obj: Any, key: str) -> Any:
    """Safely fetch *key* from an attr-dict or plain dict."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def resolve(config: Any, *path: str, default: Any = None) -> Any:
    """
    Resolve a nested config value using dot-path notation.

    Example::

        resolve(config, "llm", "model_name", default="qwen3-5-27b")

    Parameters
    ----------
    config : Any
        The root config object (AttrDict, dict, or any nested object).
    *path : str
        Sequence of attribute/key names to traverse.
    default : Any
        Value to return if any step in the path is missing.
    """
    current = config
    for key in path:
        current = _get_attr_or_key(current, key)
        if current is None:
            return default
    return current if current is not None else default


def resolve_with_source(
    config: Any,
    *path: str,
    env_key: Optional[str] = None,
    default: Any = None,
) -> tuple[Any, ConfigSource]:
    """
    Resolve a config value AND report which tier provided it.

    Useful for diagnostic endpoints that show "where did this config come from?"

    Parameters
    ----------
    config : Any
        Root config object (already merged YAML + Apollo + env by web/config.py).
    *path : str
        Dot-path to the value.
    env_key : str | None
        If provided, check this env var name directly.
        If None, an env key is inferred as PATH_JOINED_UPPERCASE.
    default : Any
        Fallback if not found anywhere.
    """
    # ── Env var check (highest priority after Apollo) ─────────────────────────
    effective_env_key = env_key or "_".join(k.upper() for k in path)
    env_val = os.environ.get(effective_env_key)
    if env_val is not None:
        return env_val, ConfigSource.ENV

    # ── Config object (already includes Apollo + YAML merged) ─────────────────
    value = resolve(config, *path, default=None)
    if value is not None:
        # We can't distinguish Apollo vs YAML here without a lower-level hook;
        # report as APOLLO if APOLLO_HOSTS is set, else YAML
        source = ConfigSource.APOLLO if os.environ.get("APOLLO_HOSTS") else ConfigSource.YAML
        return value, source

    return default, ConfigSource.DEFAULT


def dump_flat(config: Any, prefix: str = "", _depth: int = 0, max_depth: int = 5) -> dict[str, Any]:
    """
    Flatten a nested config object to a dot-notation dict.

    Useful for logging the effective config at startup.

    Example output::

        {
            "server_name": "ai-buddy",
            "llm.model_name": "qwen3-5-27b-instruct",
            "context.model_context_window": 32000,
        }
    """
    if _depth > max_depth:
        return {prefix: "<...>"}

    result: dict[str, Any] = {}

    # Handle dict-like objects
    items: list[tuple[str, Any]] = []
    if isinstance(config, dict):
        items = list(config.items())
    else:
        # AttrDict or namespace-like — iterate __dict__
        try:
            items = [(k, v) for k, v in vars(config).items() if not k.startswith("_")]
        except TypeError:
            return {prefix: config} if prefix else {}

    for key, value in items:
        full_key = f"{prefix}.{key}" if prefix else key

        # Don't recurse into sensitive-looking keys
        if any(s in key.lower() for s in ("key", "password", "secret", "token")):
            result[full_key] = "***"
            continue

        # Recurse into nested objects
        if isinstance(value, (dict,)) or (
            hasattr(value, "__dict__") and not isinstance(value, (str, int, float, bool, list, type))
        ):
            result.update(dump_flat(value, prefix=full_key, _depth=_depth + 1, max_depth=max_depth))
        else:
            result[full_key] = value

    return result


def log_effective_config(config: Any, logger_instance=None) -> None:
    """
    Log the entire effective config at DEBUG level on startup.

    Sensitive keys are redacted automatically.
    """
    _logger = logger_instance or logger
    flat = dump_flat(config)
    _logger.debug("Effective config (%d keys):", len(flat))
    for key, value in sorted(flat.items()):
        _logger.debug("  %s = %r", key, value)
