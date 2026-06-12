# -*- coding: utf-8 -*-

import os
import sys
from unittest.mock import MagicMock


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def test_vendor_runtime_imports():
    import vendor_runtime_sdk.runtime as runtime_module
    from vendor_runtime_sdk.runtime.alert.consumer import AlertPolicyConsumer
    from vendor_runtime_sdk.runtime.vault.ephemeral_git_token import EphemeralGitTokenIssuer

    assert runtime_module.__name__ == "vendor_runtime_sdk.runtime"
    assert AlertPolicyConsumer.__name__ == "AlertPolicyConsumer"
    assert EphemeralGitTokenIssuer.__name__ == "EphemeralGitTokenIssuer"


def _vendor_deps_stubbed() -> bool:
    for name in ("libs", "httpx", "aiohttp"):
        mod = sys.modules.get(name)
        if mod is not None and (isinstance(mod, MagicMock) or type(mod).__name__ == "_Stub"):
            return True
    return False


def test_vendor_bridge_imports():
    if _vendor_deps_stubbed():
        import pytest

        pytest.skip("libs stubbed by another test module")
    import vendor_runtime_sdk.llm.base as llm_base
    import vendor_runtime_sdk.mcp.mcp_http_client as mcp_http
    import vendor_runtime_sdk.libs.wrapper as wrapper

    assert llm_base is not None
    assert mcp_http is not None
    assert hasattr(wrapper, "usage_time")


def test_vendor_facade():
    from vendor_runtime_sdk.facade import (
        get_conversation_runtime_class,
        get_runtime_module,
        get_task_token_lifecycle_factory,
    )

    runtime_module = get_runtime_module()
    conversation_runtime = get_conversation_runtime_class()
    lifecycle_factory = get_task_token_lifecycle_factory()

    assert runtime_module.__name__ == "vendor_runtime_sdk.runtime"
    assert conversation_runtime.__name__ == "ConversationRuntime"
    assert callable(lifecycle_factory)


def test_vendor_conversation_runtime_smoke():
    from vendor_runtime_sdk.facade import get_conversation_runtime_class

    conversation_runtime = get_conversation_runtime_class()
    runtime = conversation_runtime(session_id="vendor-smoke", workspace_id="ws-smoke")

    assert runtime is not None
    assert conversation_runtime.get_active("vendor-smoke") is not None
