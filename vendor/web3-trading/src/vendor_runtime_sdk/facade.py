# -*- coding: utf-8 -*-
"""Single-entry facade for vendorized runtime SDK access."""

from __future__ import annotations

from typing import Any


def get_runtime_module() -> Any:
    """Return vendorized runtime package module."""
    import vendor_runtime_sdk.runtime as runtime_module

    return runtime_module


def get_conversation_runtime_class() -> type:
    """Return ConversationRuntime class lazily."""
    from vendor_runtime_sdk.runtime.conversation import ConversationRuntime

    return ConversationRuntime


def get_task_token_lifecycle_factory() -> Any:
    """Return singleton factory for ephemeral git token lifecycle."""
    from vendor_runtime_sdk.runtime.vault.task_token_lifecycle import get_task_token_lifecycle

    return get_task_token_lifecycle
