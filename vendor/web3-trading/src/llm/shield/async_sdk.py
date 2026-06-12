# -*- coding: utf-8 -*-
'''
@Time    :   2025/11/14 19:44:15
异步版本的LLM Shield SDK，使用httpx替换requests
'''
import json
import logging
from typing import Optional

import httpx

from libs.llm_shield_sdk.llm_shield_sdk_v2 import (
    ClientV2,
    ModerateV2Request,
    ModerateV2Response,
    MessageV2,
    LLM_STREAM_SEND_EXPONENT_V2,
    ModerateV2StreamSession,
    GenerateStreamV2Request
)
from libs.wrapper import usage_time


logger = logging.getLogger(__name__)


class AsyncClient(ClientV2):
    """
    异步版本的LLM Shield客户端
    使用httpx替换requests，避免在异步上下文中使用线程池
    """

    def __init__(
        self,
        url: str,
        api_key: str,
        timeout: float,
        retries: int = 3,
        max_connections=100,
        keepalive_expiry=30,
        verify=False
    ):
        self.url = url
        self.api_key = api_key
        self.timeout = timeout
        # 使用httpx的异步客户端
        limits = httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections, keepalive_expiry=keepalive_expiry)
        transport = httpx.AsyncHTTPTransport(retries=retries, verify=verify, limits=limits)
        self.http_client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.http_client.aclose()

    @usage_time
    async def Moderate(self, request: Optional[ModerateV2Request] = None) -> ModerateV2Response:
        """异步执行内容审核"""
        if request is None:
            request = ModerateV2Request()

        request_body = request.model_dump_json(by_alias=True).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key
        }

        try:
            logger.info(f"Moderate: {request.message.content}")
            resp = await self.http_client.post(
                f"{self.url}/v2/moderate",
                content=request_body,
                headers=headers
            )
            resp.raise_for_status()

            response = ModerateV2Response.model_validate(resp.json())
            return response

        except httpx.RequestError as e:
            logger.error(f"异步请求失败: {e}")
            raise Exception(f"请求失败: {e}")
        except Exception as e:
            logger.error(f"处理响应失败: {e}")
            raise Exception(f"处理响应失败: {e}")

    # @usage_time
    async def ModerateStream(self, request: ModerateV2Request, session: ModerateV2StreamSession) -> Optional[ModerateV2Response]:
        """
        异步处理流式审核请求
        :param request: 当前流式请求片段（ModerateV2Request 类型）
        :param session: 流式会话对象（ModerateV2StreamSession 类型）
        :return: 审核响应（ModerateV2Response 类型）
        """
        # 1. 校验参数合法性
        if request is None:
            request = ModerateV2Request()  # 初始化空请求

        # 本接口仅支持流式调用（use_stream 不能为 0，且 session 不能为空）
        if request.use_stream == 0 or session is None:
            raise ValueError("use_stream cannot be 0, and session cannot be None")

        is_first_request = (session.request is None)  # 判断是否为首次请求
        is_last_request = (request.use_stream == 2)  # 判断是否为最后一次请求

        # 2. 初始化或追加会话请求（深拷贝确保隔离）
        if session.request is None:
            # 首次请求：深拷贝初始请求到 session
            session.request = ModerateV2Request(request)
        else:
            # 后续请求：追加当前请求内容到 session 积累的请求中
            if request.message and request.message.content:
                if session.request.message is None:
                    session.request.message = MessageV2()
                session.request.message.content += request.message.content
                session.request.use_stream = request.use_stream
        session.stream_send_len += len(request.message.content)

        # 3. 判断是否需要发送请求到后端
        # 只有当未检测长度 >= 10 或者是第一次或者是最后一次请求时，才发送请求
        need_send_request = is_last_request or is_first_request or (session.stream_send_len >= session.CurrentSendWindow)

        # 如果不需要发送请求，直接返回上次的默认响应（如果有）
        if not need_send_request:
            return session.default_body
        else:
            session.CurrentSendWindow = session.CurrentSendWindow * LLM_STREAM_SEND_EXPONENT_V2

        # 3. 序列化请求（使用 Pydantic 的 model_dump 方法）
        try:
            request_body = session.request.model_dump_json(by_alias=True)
        except Exception as e:
            raise IOError(f"Failed to serialize request: {str(e)}")

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key
        }

        try:
            # logger.info(f"ModerateStream: {request.message.content}")
            response = await self.http_client.post(
                f"{self.url}/v2/moderate",
                content=request_body,
                headers=headers
            )
            response.raise_for_status()  # 抛出 HTTP 错误状态码
        except httpx.RequestError as e:
            logger.error(f"异步流式请求失败: {e}")
            raise IOError(f"HTTP request failed: {str(e)}")

        # 5. 解析响应
        try:
            response_data = json.loads(response.text)
            moderate_response = ModerateV2Response(**response_data)
        except Exception as e:
            raise IOError(f"Failed to parse response: {str(e)}")

        # 6. 更新会话状态
        session.default_body = moderate_response  # 存储响应体
        session.stream_send_len = 0  # 重置未发送长度（根据实际业务调整）
        session.request.msg_id = moderate_response.result.msg_id

        return moderate_response