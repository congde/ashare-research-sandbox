# -*- coding: utf-8 -*-
"""Sprint 7 PR-1 · ~/.aibuddy/mcp_servers.toml loader.

Returns a list of validated :class:`McpServerSpec` instances.
File-absent is the default healthy state — returns ``[]`` quietly.
File-present-but-malformed raises so the operator notices loud and
clear at boot rather than silently running with an empty MCP set.
"""
from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import List, Optional

from pydantic import ValidationError

from vendor_runtime_sdk.runtime.mcp_config.schema import (
    McpConfigFile,
    McpServerSpec,
    SchemaValidationError,
)

logger = logging.getLogger(__name__)


_DEFAULT_CONFIG_PATH = Path.home() / ".aibuddy" / "mcp_servers.toml"


def load_mcp_servers(
    config_path: Optional[Path] = None,
) -> List[McpServerSpec]:
    """Parse + validate ``~/.aibuddy/mcp_servers.toml`` into a list of specs.

    Behaviour
    ---------
    * Missing file → ``[]`` (default healthy state; no warnings)
    * Malformed toml / pydantic validation error →
      :class:`SchemaValidationError` (loud at boot)
    * OS-level read errors → propagate so daemon refuses to start with
      half-known config

    Returns disabled servers too (caller filters via ``spec.enabled``);
    the loader's job is parse + validate, not policy.
    """
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH

    if not path.is_file():
        logger.debug("mcp_servers.toml absent at %s — empty config", path)
        return []

    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise SchemaValidationError(
            f"mcp_servers.toml ({path}) is not valid TOML: {exc}"
        ) from exc

    try:
        cfg = McpConfigFile.model_validate(raw)
    except ValidationError as exc:
        # Pydantic V2 ValidationError already carries the field path.
        raise SchemaValidationError(
            f"mcp_servers.toml ({path}) failed schema validation:\n{exc}"
        ) from exc

    return list(cfg.server)


__all__ = ["load_mcp_servers"]
