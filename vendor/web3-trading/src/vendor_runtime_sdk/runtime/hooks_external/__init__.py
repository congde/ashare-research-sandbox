"""S2.1 · External-process hook protocol (Claude Code parity).

Subpackage layout:

  * ``protocol.py`` — JSON wire format for the three hook events
    (PreToolUse / PostToolUse / PostToolUseFailure)
  * ``runner.py``   — subprocess execution with timeout + stderr cap
  * ``config.py``   — TOML loader for ``~/.aibuddy/hooks.toml`` +
                      ``<workspace>/.coder/hooks.toml``

Toggle: ``external_process_hooks`` (default OFF).  Operators must
explicitly opt in because hooks are arbitrary subprocess execution.
"""
from __future__ import annotations

from .protocol import (
    EVENT_POST_TOOL_USE,
    EVENT_POST_TOOL_USE_FAILURE,
    EVENT_PRE_TOOL_USE,
    HookInput,
    HookOutput,
    decode_output,
    encode_input,
)

__all__ = [
    "EVENT_PRE_TOOL_USE",
    "EVENT_POST_TOOL_USE",
    "EVENT_POST_TOOL_USE_FAILURE",
    "HookInput",
    "HookOutput",
    "decode_output",
    "encode_input",
]
