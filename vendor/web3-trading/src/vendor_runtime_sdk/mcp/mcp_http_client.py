# -*- coding: utf-8 -*-
"""Lazy bridge to local project mcp client implementation.

Importing ``mcp.mcp_http_client`` eagerly can trigger circular imports in this
repository. Keep this bridge lazy and only resolve symbols when accessed.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


def _target() -> Any:
	return import_module("mcp.mcp_http_client")


def __getattr__(name: str) -> Any:
	return getattr(_target(), name)


def __dir__() -> list[str]:
	return sorted(set(dir(_target())))
