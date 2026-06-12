"""
Plugin Hook system — pre/post lifecycle hooks (§5.13)

Hooks are composed into ConversationRuntime and invoked at defined
lifecycle points (pre_llm_call, post_llm_call, session_start, session_end,
tool_use_failure).
"""

from vendor_runtime_sdk.runtime.hooks.base import (
    HookContext,
    HookDispatcher,
    PluginHook,
    ToolFailureContext,
)
from vendor_runtime_sdk.runtime.hooks_core import HookRunner, PreHookResult, PostHookResult

__all__ = [
    "PluginHook",
    "HookContext",
    "ToolFailureContext",
    "HookDispatcher",
    "HookRunner",
    "PreHookResult",
    "PostHookResult",
]
