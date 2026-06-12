# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/27 19:30:34
'''

import asyncio
import os
import logging
import json
import time
from pathlib import Path
from typing import Optional

from web.config import config
from libs import http
from libs.wrapper import usage_time
from mcp.types import *
from libs.eureka import eureka
from web.context import context
from web.authenticator import get_headers, split_securekey
from libs.language import ENGLISH_NAME_TO_CODE_MAP
from agent.utils import jinja_render_text
from libs.sub_task import sub_task
from dao.redis_bootstrap import get_redis_client
from web.component import component
from agent.utils import jinja_render

logger = logging.getLogger(__name__)

SendRequestT = TypeVar("SendRequestT", ClientRequest, ServerRequest)
SendResultT = TypeVar("SendResultT", ClientResult, ServerResult)
SendNotificationT = TypeVar("SendNotificationT", ClientNotification, ServerNotification)
ReceiveRequestT = TypeVar("ReceiveRequestT", ClientRequest, ServerRequest)
ReceiveResultT = TypeVar("ReceiveResultT", bound=BaseModel)
ReceiveNotificationT = TypeVar("ReceiveNotificationT", ClientNotification, ServerNotification)
RequestId = str | int


def _redis():
    return get_redis_client()


def _local_mcp_disabled() -> bool:
    return (
        os.environ.get("serverEnv", "").lower() == "local"
        and os.environ.get("MCP_CLIENT_ENABLED", "false").lower()
        not in ("1", "true", "yes", "y")
    )


async def _local_tool_defs() -> list:
    """Built-in tools that run in-process (no MCP / Eureka / Apollo)."""
    from mcp.types import Tool
    from agent.tools.dexscan_open_api import DexScanOpenAPITool
    from agent.tools.kucoin_openapi_public import KucoinOpenApiPublicTool
    from agent.tools.trading_decision import TradingDecisionTool
    from agent.tools.valuescan_open_api import ValueScanOpenAPITool

    tools = []
    for cls in (
        ValueScanOpenAPITool,
        KucoinOpenApiPublicTool,
        DexScanOpenAPITool,
        TradingDecisionTool,
    ):
        inst = cls()
        tools.append(
            Tool(
                name=inst.name,
                description=inst.description,
                inputSchema=inst.parameters,
            )
        )
    return tools


async def build_local_tools_info(client: "McpHttpClient") -> ToolsInfo:
    tools = await _local_tool_defs()
    openai_tools = client.to_openai_tools(tools)
    tools_name = [tool.name for tool in tools]
    tools_desc = "\n".join(
        "<tool>\n<tool_name>" + tool.name + "</tool_name>\n<tool_desc>\n"
        + tool.description + "\n</tool_desc>\n</tool>"
        for tool in tools
    )
    return ToolsInfo(
        tools=tools,
        tools_name_map={tool.name: tool for tool in tools},
        openai_tools=openai_tools,
        tools_name=tools_name,
        tools_desc=tools_desc,
    )


class McpError(Exception):
    def __init__(self, error: str):
        super().__init__(error)
        self.error = error


class CallToolError(McpError):
    pass


class McpHttpClient(object):

    LISTEN_TOOLS_TASK_NAME = f"mcp_list_tools_task:{config.mcp_project_id}"
    LISTEN_PROMPTS_TASK_NAME = f"mcp_list_prompts_task:{config.mcp_project_id}"
    REDIS_LIST_TOOLS_KEY = f"kia:mcp:list_tools:{config.mcp_project_id}"
    REDIS_LIST_PROMPTS_KEY = f"kia:mcp:list_prompts_hash:{config.mcp_project_id}"

    def __init__(
        self,
        timeout_seconds: int = 15,
    ):
        self._request_id = 0
        self._timeout_seconds = timeout_seconds
        self._name_tool_map = {}
        self._shutdown_event = asyncio.Event()

    async def _wait_or_stop(self, seconds: float) -> bool:
        """Wait for interval or stop early when shutdown is requested.

        Returns True when shutdown is requested, else False.
        """
        if self._shutdown_event.is_set():
            return True
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=max(0.1, float(seconds)))
            return True
        except asyncio.TimeoutError:
            return False

    async def _listen_list_tools(self):
        while not self._shutdown_event.is_set():
            try:
                await self._list_tools()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"mcp list_tools background loop error: {e}")
            if await self._wait_or_stop(config.mcp_list_tools_interval):
                break

    async def _listen_list_prompts(self):
        while not self._shutdown_event.is_set():
            try:
                await self._list_prompts()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"mcp list_prompts background loop error: {e}")
            if await self._wait_or_stop(config.mcp_list_prompts_interval):
                break

    async def initialize(self):
        """Initialize MCP client and verify tools availability"""
        self._shutdown_event.clear()
        try:
            await sub_task.create_task(self._listen_list_tools(), task_name=self.LISTEN_TOOLS_TASK_NAME)
            await sub_task.create_task(self._listen_list_prompts(), task_name=self.LISTEN_PROMPTS_TASK_NAME)
        except Exception as e:
            logger.error(f"Failed to initialize MCP client: {e}")

    async def shutdown(self):
        """Request MCP background loops to stop and cancel loop tasks."""
        self._shutdown_event.set()
        for task_name in (self.LISTEN_TOOLS_TASK_NAME, self.LISTEN_PROMPTS_TASK_NAME):
            try:
                if sub_task.has_task(task_name):
                    await sub_task.cancel_task(task_name, timeout=2.0)
            except Exception as e:
                logger.warning(f"Failed to cancel MCP task '{task_name}': {e}")

    async def send_request(
        self,
        method: str,
        request: SendRequestT,
        result_type: type[ReceiveResultT],
        retries: int = 0
    ) -> ReceiveResultT:
        request_id = self._request_id
        self._request_id = request_id + 1

        request_data = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        jsonrpc_request = JSONRPCRequest(
            jsonrpc="2.0",
            id=str(request_id),
            **request_data,
        )
        request_data = jsonrpc_request.model_dump(mode="json")
        start_time = time.time()
        resp = {}
        try:
            mcp_client_server = os.environ.get("MCP_CLIENT_SERVER", "DC-AI-LINKU")
            url = eureka.get_service_url(app_name=mcp_client_server).strip('/') + "/mcp"
            ak, sk = split_securekey(config.mcp_client_securekey)
            headers = get_headers(
                app_name=mcp_client_server,
                method="POST",
                url=url,
                headers=context.get('headers', {}),
                sk=sk,
                ak=ak,
                name=ak
            )
            resp = await http._fetch(
                url,
                method=method.upper(),
                json=request_data,
                headers=headers,
                timeout=self._timeout_seconds,
                retries=retries
            )
            if "code" in resp and int(resp.get("code", 500)) != 200:
                raise ValueError(f"{resp}")
        except Exception as e:
            logger.warning(f'Mcp http fetch error, {e}')
            return
        interface_cost = int((time.time() - start_time) * 1000)
        if request.method == "tools/list":
            resp_info = [item["name"] for item in resp.get("result", {}).get("tools", [])]
            logger.info(f"Mcp interface_cost={interface_cost}ms, Mcp url={url}, request={request_data}, tools={resp_info}, count={len(resp_info)}")
        else:
            logger.info(f"Mcp interface_cost={interface_cost}ms, Mcp url={url}, request={request_data}, response={resp}")
        
        # 检查是否是 JSON-RPC 错误响应
        if "error" in resp:
            error_data = resp["error"]
            raise McpError(ErrorData(
                code=error_data.get("code", -1),
                message=error_data.get("message", "Unknown error"),
                data=error_data.get("data")
            ))
        
        # 检查是否有 result 字段
        if "result" not in resp:
            raise McpError(ErrorData(
                code=-1,
                message="No result field in response",
                data=resp
            ))
        
        return result_type(**resp["result"])

    async def get_tools_info(self) -> Optional[ToolsInfo]:
        result = await self.list_tools()
        if not result:
            if _local_mcp_disabled():
                logger.info("MCP disabled/unavailable locally — using built-in tools")
                info = await build_local_tools_info(self)
                self._name_tool_map = {tool.name: tool for tool in info.tools}
                return info
            logger.warning("No tools available - MCP service may be unavailable")
            return None
        self._name_tool_map = {tool.name: tool for tool in result.tools}
        try:
            openai_tools = self.to_openai_tools(result.tools)
            tools_name = [tool.name for tool in result.tools]
            tools_desc = "\n".join([
                "<tool>\n<tool_name>" + tool.name + "</tool_name>\n<tool_desc>\n" + tool.description + "\n</tool_desc>\n</tool>"
                for tool in result.tools
            ])
            return ToolsInfo(
                tools=result.model_dump(mode="json").get("tools", []),
                tools_name_map={tool.name: tool.model_dump(mode="json") for tool in result.tools},
                openai_tools=openai_tools,
                tools_name=tools_name,
                tools_desc=tools_desc
            )
        except Exception as e:
            logger.error(f"Failed to process tools info: {e}")
            return None

    async def _list_tools(self) -> Optional[ListToolsResult]:
        try:
            result = await self.send_request(
                method="POST",
                request=ListToolsRequest(method='tools/list', projectId=str(config.mcp_project_id)),
                result_type=ListToolsResult
            )
            if result:
                from agent.tools.customer_service_kb import CustomerServiceKBTool
                from agent.tools.kucoin_openapi_public import KucoinOpenApiPublicTool
                from mcp.types import Tool
                customer_service_kb = CustomerServiceKBTool()
                kucoin_openapi_public = KucoinOpenApiPublicTool()
                result.tools.append(Tool(
                    name=customer_service_kb.name,
                    description=await customer_service_kb.mcp_description(),
                    inputSchema=customer_service_kb.parameters
                ))
                result.tools.append(Tool(
                    name=kucoin_openapi_public.name,
                    description=await kucoin_openapi_public.mcp_description(),
                    inputSchema=kucoin_openapi_public.parameters
                ))
                status = await _redis().set(self.REDIS_LIST_TOOLS_KEY, result.model_dump_json())
                tools_name = [tool.name for tool in result.tools]
                logger.info(f"The saved result of list_tools: {status}, tools_count: {len(result.tools)}, tools_name: {tools_name}")
            else:
                logger.error("list_tools is empty")
            return result
        except McpError as e:
            logger.error(f"Failed to list tools: {e.error.message}")
            return
        except Exception as e:
            logger.exception(f"Unexpected error when listing tools: {e}")
            return

    async def list_openai_tools(self, available_tools: list[str] = []) -> Optional[ListToolsResult]:
        tools = await mcp_client.list_tools()
        if not tools:
            return None
        if available_tools:
            tools = [t for t in tools.tools if t.name in available_tools]
        else:
           tools = tools.tools 
        return mcp_client.to_openai_tools(tools)

    async def list_tools(self) -> Optional[ListToolsResult]:
        if _local_mcp_disabled():
            return ListToolsResult(tools=await _local_tool_defs())
        try:
            result = await _redis().get(self.REDIS_LIST_TOOLS_KEY)
            if result:
                return ListToolsResult(**json.loads(result.decode()))

            return await self._list_tools()
        except Exception as e:
            logger.exception(f"Unexpected error when listing tools: {e}")
            return
    
    def to_openai_tools(self, tools: list[Tool]):
        openai_tools = []
        for tool in tools:
            tool_schema = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {}
                }
            }
            input_schema = tool.inputSchema

            parameters = {
                "type": input_schema.get("type", "object"),
                "properties": input_schema.get("properties", {}),
                "required": input_schema.get("required", []),
                "additionalProperties": False  # 不允许额外参数，这是安全考虑
            }

            # 特殊处理枚举类型参数
            for prop in parameters["properties"].values():
                if "enum" in prop:
                    prop["description"] = f"可选值: {', '.join(prop['enum'])}"
            
            # 如果参数中没有query参数，则添加query参数
            if "query" not in parameters["properties"]:
                parameters["properties"]["query"] = {
                    "type": "string",
                    "description": "The search query or request that will be executed by the tool and displayed to the user. This should be contextually refined and optimized based on the current conversation and user intent.",
                }
                parameters["required"].append("query")

            # 出入金工具的语种参数为lang，先从参数列表中删掉lang参数，后面再添加
            if tool.name == "recharge_and_withdraw":
                if "lang" in parameters["properties"]:
                    del parameters["properties"]["lang"]
                    if "lang" in parameters["required"]:
                        parameters["required"].remove("lang")

            # 如果参数中没有detect_language参数，则添加detect_language参数，
            if "detect_language" not in parameters["properties"]:
                parameters["properties"]["detect_language"] = {
                    "type": "string",
                    "description": "Detect the **writing language** (linguistic system) used in the user's query text. For example: 'What's the weather in Paris' is written in English, even though it mentions Paris. If the user explicitly requests a specific language for the response (e.g., 'please reply in XX language' or '請以 XX 語回覆我'), set this field to that requested language. Value constraints: (1) If the detected language or requested language is in the supported languages list, the value MUST exactly match one of the language names from the supported languages list. Supported languages: " + ", ".join([name for name in ENGLISH_NAME_TO_CODE_MAP.keys()]) + " (2) If the detected language or requested language is NOT in the supported languages list, you may use your understanding to output the language name in English. Note: You must carefully distinguish between Simplified Chinese and Traditional Chinese. If you are uncertain, prefer Traditional Chinese as much as possible. "
                }
                parameters["required"].append("detect_language")

            tool_schema["function"]["parameters"] = parameters
            openai_tools.append(tool_schema)

        return openai_tools

    @usage_time
    async def call_tool(self, params: CallToolRequestParams, retries=0) -> CallToolResult:
        logger.info(f'Call tool params: {params.model_dump(mode="json")}')
        try:
            project_id = str(self._name_tool_map[params.name].projectId)
        except (KeyError, AttributeError):
            project_id = str(config.mcp_project_id)
        result = await self.send_request(
            method="POST",
            request=CallToolRequest(method='tools/call', params=params, projectId=project_id),
            result_type=CallToolResult,
            retries=retries
        )
        if not result or result.isError:
            raise CallToolError(ErrorData(code=500, message=f'Call tool error, isError is true'))
        for tool in result.content:
            if not tool.type in ("resource", "text"):
                raise CallToolError(ErrorData(code=500, message=f'Call tool response type error, type={tool.type}'))
            
            if tool.text:
                try:
                    tool_text = json.loads(tool.text)
                except (json.JSONDecodeError, TypeError):
                    logger.debug(f"Tool '{params.name}' returned non-JSON text, skipping JSON validation")
                    continue

                if isinstance(tool_text, dict):
                    if 'success' in tool_text and not tool_text.get("success"):
                        error_msg = tool_text.get("message") or tool_text.get("error") or tool_text.get("msg") or "success is false"
                        raise CallToolError(ErrorData(code=500, message=f"Call tool '{params.name}' response error: {error_msg}"))
                    data = tool_text.get("data")
                    if isinstance(data, dict) and "success" in data and not data.get("success"):
                        error_msg = data.get("message") or data.get("error") or data.get("msg") or "unknown"
                        logger.warning(f"Tool '{params.name}' nested data.success is false: {error_msg}")

            if params.name == "web_search":
                continue

            try:
                parsed = json.loads(tool.text)
                if not isinstance(parsed, dict):
                    continue
                text = parsed.get("result", {})
            except (json.JSONDecodeError, TypeError):
                continue

            if not isinstance(text, dict) or 'success' not in text:
                continue

            if not text.get("success"):
                error_msg = text.get("message") or text.get("error") or text.get("msg") or "unknown"
                raise CallToolError(ErrorData(code=500, message=f"Call tool '{params.name}' mcpServer response error: {error_msg}"))
            if isinstance(text.get('data'), dict) and not text.get("data", {}).get("success"):
                error_msg = text.get("data", {}).get("message") or text.get("data", {}).get("error") or "unknown"
                raise CallToolError(ErrorData(code=500, message=f"Call tool '{params.name}' mcpServer nested response error: {error_msg}"))

        return result

    async def _list_prompts(self):
        mcp_client_server = os.environ.get("MCP_CLIENT_SERVER", "DC-AI-LINKU")
        url = eureka.get_service_url(app_name=mcp_client_server).strip('/') + "/api/v1/prompt/page"
        ak, sk = split_securekey(config.mcp_client_securekey)
        headers = get_headers(
            app_name=mcp_client_server,
            method="POST",
            url=url,
            headers=context.get('headers', {}),
            sk=sk,
            ak=ak,
            name=ak
        )
        project_id = str(config.mcp_project_id)
        resp = await http.post(
            url,
            json={
                "projectId": project_id,
                "current": 1,
                "pageSize": 1000,
            },
            headers=headers,
            timeout=self._timeout_seconds,
            retries=3
        )
        result = {}
        for item in resp.get("items", []):
            if str(item.get("projectId")) != project_id:
                continue
            result[item.get("ticketNo", "")] = item

        if result:
            prompt_base_dir = Path(__file__).parent.parent / "agent/prompt"
            for k, v in result.items():
                status = await _redis().hset(self.REDIS_LIST_PROMPTS_KEY, k, json.dumps(v))
                prompt_content = v.get("prompt", "").strip()
                if prompt_content and not os.getenv("NO_SAVE_LOCAL_PROMPT"):
                    prompt_file = prompt_base_dir / v["ticketNo"]
                    prompt_file.write_text(prompt_content, encoding="utf-8")
                    logger.info(f"Saved prompt to {prompt_file}")
            
            logger.info(f"The saved result of list_prompts: {status}, prompts_count: {len(result)}, prompts_name: {list(result.keys())}")
        else:
            logger.error("list_tools is empty")

    async def get_prompt(self, name: str, data: Optional[dict] = None) -> str:
        try:
            load_template = False
            result = await _redis().hget(self.REDIS_LIST_PROMPTS_KEY, name)
            if not result:
                load_template = True
            else:
                item = json.loads(result.decode())
                prompt = item.get("prompt")
                if not prompt:
                    load_template = True

            if os.getenv("LOAD_LOCAL_PROMPT"):
                load_template = True
                prompt = name

            if load_template:
                return jinja_render(name, data)
            return jinja_render_text(prompt, data)
        except Exception as e:
            logger.warning(f"mcp get_prompt error: {e}")
            return ""


mcp_client = McpHttpClient()
