"""Integration tests for workflow memory modes (enable_memory on/off)."""

import json
import os
import sys
import types
from types import SimpleNamespace

import pytest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


def _ensure_module(module_name: str, *, force: bool = False):
    """Create a placeholder module, preserving ``__path__`` for packages that
    exist under ``src/`` so that other test files can still import sub-modules.

    When ``force=True``, always creates a fresh ModuleType even if the name
    already exists in sys.modules (used to repair stubs set by other tests)."""
    if not force and module_name in sys.modules:
        return sys.modules[module_name]
    module = types.ModuleType(module_name)
    if "." not in module_name:
        candidate = os.path.join(SRC_DIR, module_name)
        if os.path.isdir(candidate):
            module.__path__ = [candidate]
        else:
            module.__path__ = []
    sys.modules[module_name] = module
    if "." in module_name:
        parent_name, child_name = module_name.rsplit(".", 1)
        parent = _ensure_module(parent_name, force=force)
        if not hasattr(parent, "__path__"):
            parent.__path__ = []
        setattr(parent, child_name, module)
    return module


def _install_test_stubs():
    os.environ.setdefault("SERVER_NAME", "ai-web3-tradding-agent")
    os.environ.setdefault("serverEnv", "local")
    os.environ.setdefault("MEMORY_URL", "http://memory.test")

    json_repair_mod = _ensure_module("json_repair")
    json_repair_mod.loads = lambda text: json.loads(text)

    graph_mod = _ensure_module("langgraph.graph")
    graph_mod.END = "END"

    class _StateGraph:
        def __init__(self, *_args, **_kwargs):
            pass
        def add_node(self, *_args, **_kwargs):
            pass
        def set_entry_point(self, *_args, **_kwargs):
            pass
        def add_edge(self, *_args, **_kwargs):
            pass
        def compile(self):
            return self

    graph_mod.StateGraph = _StateGraph

    _ensure_module("agent")
    _ensure_module("agent.skills")
    tool_call_mod = _ensure_module("agent.skills.tool_call")

    async def _async_noop(*_a, **_kw):
        return {}

    tool_call_mod.ToolCallSkill = type("ToolCallSkill", (), {"execute": _async_noop})

    callback_mod = _ensure_module("agent.skills.callback")
    callback_mod.WorkFlowCallbackSkill = type("WorkFlowCallbackSkill", (), {"execute": _async_noop})

    utils_mod = _ensure_module("agent.utils")
    utils_mod.utc_now_iso = lambda: "2026-03-17T00:00:00Z"

    tools_base_mod = _ensure_module("agent.tools.base")
    tools_base_mod.BaseTool = object
    tools_base_mod.ToolResult = dict

    agent_schema_mod = _ensure_module("agent.schema")

    class _UserConfigModel:
        @staticmethod
        async def get_user_config(_user_id):
            return {"memory_storage_time": 30}

    agent_schema_mod.UserConfigModel = _UserConfigModel

    mcp_mod = _ensure_module("mcp.mcp_http_client")

    async def _list_tools(*_a, **_kw):
        return []

    mcp_mod.mcp_client = SimpleNamespace(list_openai_tools=_list_tools)

    llm_mod = _ensure_module("llm.llm")

    async def _ainvoke(*_a, **_kw):
        return SimpleNamespace(content="ok", tool_calls=[])

    llm_mod.llm = SimpleNamespace(ainvoke=_ainvoke)

    llm_base_mod = _ensure_module("llm.base")
    llm_base_mod.create_llm = lambda *_args, **_kwargs: None

    _ensure_module("libs")
    libs_http_mod = _ensure_module("libs.http", force=True)

    async def _http_post(*_a, **_kw):
        return {"results": []}

    libs_http_mod.post = _http_post

    async def _http_get(*_a, **_kw):
        return {"results": []}

    libs_http_mod.get = _http_get

    libs_callback_mod = _ensure_module("libs.callback")

    async def _execute_callback(*_a, **_kw):
        return None

    libs_callback_mod.execute_callback = _execute_callback
    libs_callback_mod.get_func = lambda _name: (lambda *a, **kw: None)

    libs_prompt_mod = _ensure_module("libs.load_prompt")

    async def _get_prompt(*_a, **_kw):
        return "integration prompt"

    libs_prompt_mod.get_prompt = _get_prompt

    libs_wrapper_mod = _ensure_module("libs.wrapper")
    libs_wrapper_mod.usage_time = lambda fn: fn

    libs_eureka_mod = _ensure_module("libs.eureka")
    libs_eureka_mod.eureka = SimpleNamespace(get_service_url=lambda app_name: "http://memory.test")

    _ensure_module("web")
    web_config_mod = _ensure_module("web.config")
    web_config_mod.config = SimpleNamespace(
        memory_url="http://memory.test",
        memory_server="ai-memo",
        memory_securekey="dummy_sk",
        business_line="test",
        apollo_id="test",
    )

    web_context_mod = _ensure_module("web.context")
    web_context_mod.context = SimpleNamespace(get=lambda *_args, **_kwargs: {})

    web_auth_mod = _ensure_module("web.authenticator")
    web_auth_mod.get_headers = lambda *_args, **_kwargs: {}
    web_auth_mod.delete = _async_noop
    web_auth_mod.post = _async_noop
    web_auth_mod.get = _async_noop


_install_test_stubs()

from workflow.process import WorkFLowAgent  # noqa: E402


def _build_state(enable_memory: bool) -> dict:
    return {
        "user_id": "integration-memory-user",
        "query": "BTC现货ETF最新进展如何",
        "messages": [],
        "tools": [],
        "memory": "",
        "result": None,
        "extra_query": {},
        "skill_config": {
            "enable_memory": enable_memory,
            "enable_tools": False,
            "synthesize_prompt": {},
        },
    }


@pytest.mark.asyncio
class TestWorkflowMemoryModesIntegration:
    async def test_plan_hits_memory_search_when_enabled(self) -> None:
        from libs import http
        from unittest.mock import patch

        with patch.object(http, "post", wraps=http.post) as spy:
            agent = WorkFLowAgent()
            await agent.plan(_build_state(enable_memory=True))
            query_calls = [c for c in spy.call_args_list
                           if "query" in (c.kwargs.get("json") or {})]
            assert len(query_calls) >= 1

    async def test_plan_skips_memory_search_when_disabled(self) -> None:
        from libs import http
        from unittest.mock import patch

        with patch.object(http, "post", wraps=http.post) as spy:
            agent = WorkFLowAgent()
            await agent.plan(_build_state(enable_memory=False))
            query_calls = [c for c in spy.call_args_list
                           if "query" in (c.kwargs.get("json") or {})]
            assert len(query_calls) == 0

    async def test_synthesize_hits_memory_add_when_enabled(self) -> None:
        from libs import http
        from unittest.mock import patch

        with patch.object(http, "post", wraps=http.post) as spy:
            agent = WorkFLowAgent()
            state = _build_state(enable_memory=True)
            state["messages"] = [{"role": "user", "content": state["query"]}]

            async def _mock_llm(*_a, **_kw):
                return SimpleNamespace(content='{"answer":"ok"}')

            with patch.object(agent, "_execute_llm_with_callbacks", side_effect=_mock_llm):
                await agent.synthesize(state)
            msg_calls = [c for c in spy.call_args_list
                         if "messages" in (c.kwargs.get("json") or {})]
            assert len(msg_calls) >= 1

    async def test_synthesize_skips_memory_add_when_disabled(self) -> None:
        from libs import http
        from unittest.mock import patch

        with patch.object(http, "post", wraps=http.post) as spy:
            agent = WorkFLowAgent()
            state = _build_state(enable_memory=False)
            state["messages"] = [{"role": "user", "content": state["query"]}]

            async def _mock_llm(*_a, **_kw):
                return SimpleNamespace(content='{"answer":"ok"}')

            with patch.object(agent, "_execute_llm_with_callbacks", side_effect=_mock_llm):
                await agent.synthesize(state)
            msg_calls = [c for c in spy.call_args_list
                         if "messages" in (c.kwargs.get("json") or {})]
            assert len(msg_calls) == 0
