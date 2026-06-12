"""Sprint 7 · External MCP server configuration package.

Operator declares MCP servers in ``~/.aibuddy/mcp_servers.toml``;
this package parses + validates + manages their lifecycle so the
Coder Agent's tool registry can expose them as namespaced LLM tools
(``{namespace_prefix}__{tool_name}``).

Public surface:
  * :class:`McpServerSpec` — single server config
  * :class:`McpConfigFile` — full toml file (list of servers + global limits)
  * :func:`load_mcp_servers` — toml → validated specs (or empty when file absent)

Toggle-gated by ``coder_mcp_external_servers`` (default OFF).
Per docs/Sprint7-MCP-工具扩展技术方案.md.
"""
from vendor_runtime_sdk.runtime.mcp_config.loader import load_mcp_servers  # noqa: F401
from vendor_runtime_sdk.runtime.mcp_config.manager import (  # noqa: F401
    McpServerManager,
    McpServerStatus,
)
from vendor_runtime_sdk.runtime.mcp_config.schema import (  # noqa: F401
    AuthSpec,
    McpConfigFile,
    McpServerSpec,
    SchemaValidationError,
)
from vendor_runtime_sdk.runtime.mcp_config.startup import bootstrap_external_mcp_or_none  # noqa: F401

__all__ = [
    "AuthSpec",
    "McpConfigFile",
    "McpServerManager",
    "McpServerSpec",
    "McpServerStatus",
    "SchemaValidationError",
    "bootstrap_external_mcp_or_none",
    "load_mcp_servers",
]
