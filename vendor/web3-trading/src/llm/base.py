# -*- coding: utf-8 -*-
'''
@Time    :   2025/11/06 16:43:20
'''
import re
import os
import json_repair
import logging
from typing import Any, List, Optional, Dict, AsyncGenerator, overload, TypeVar, Iterable, NamedTuple

import httpx
from pydantic import BaseModel
from openai import AsyncOpenAI
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_tool_union_param import ChatCompletionToolUnionParam
from openai._types import NotGiven, NOT_GIVEN

T = TypeVar('T', bound=BaseModel)



logger = logging.getLogger(__name__)


def create_llm(**kwargs):
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_API_BASE")
    llm = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=60.0,
        http_client=httpx.AsyncClient(verify=False),
        **kwargs
    )
    from web.config import config
    model_name = config.llm_model_name
    logger.info(f"LLM service initialization completed with OpenAI, base_url={base_url}, model: {model_name}")
    return llm, model_name


class StreamOutput(BaseModel):
    thinking: Optional[str] = None
    thinking_snapshot: Optional[str] = None
    thinking_end: Optional[bool] = None
    answer: Optional[str] = None
    answer_snapshot: Optional[str] = None
    answer_end: Optional[bool] = None


class ResponseResult(NamedTuple):
    thinking: str
    answer: str



class BaseLLM(object):

    _thinking_pattern = re.compile(r'</?think>', flags=re.DOTALL)
    # Qwen3: <think>...</think>; Qwen3.5: 可能无 <think>，仅 </think> 结束。兼容两种格式
    _content_pattern = re.compile(r'(<think>)?.*?</think>', flags=re.DOTALL)

    def __init__(
        self,
        base_url: str = None,
        api_key: str = None,
        default_model_name: str = None,
        max_retries: int = 3,
        timeout: float = 1800,
        max_connections=100,
        keepalive_expiry=1800,
        verify=False,
        **kwargs
    ):
        http_client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(
                verify=verify,
                limits=httpx.Limits(
                    max_connections=max_connections,
                    max_keepalive_connections=max_connections,
                    keepalive_expiry=keepalive_expiry
                )
            )
        )
        self._client = AsyncOpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=base_url or os.environ.get("OPENAI_API_BASE"),
            max_retries=max_retries,
            timeout=timeout,
            http_client=http_client,
            **kwargs
        )
        self._default_model_name = default_model_name
        self._base_url = base_url or os.environ.get("OPENAI_API_BASE") or ""

    @staticmethod
    def _record_log(messages: List[dict], tools=None):
        """记录日志"""
        items = messages.copy()
        if tools and tools is not NOT_GIVEN:
            items.append({"role": "tool", "content": tools})
        messages_str = "\n".join([f"[{msg['role']}]: {msg.get('content', '')}" for msg in items])
        logger.debug(f"LLM Messages:\n{messages_str}\n")

    async def create(self, *args, **kwargs):
        return await self._client.chat.completions.create(*args, **kwargs)

    @overload
    async def invoke(
        self,
        messages: List[dict],
        model: str = None,
        response_format: type[T] = None,
        extra_body: dict = {"chat_template_kwargs": {"enable_thinking": False}},
        temperature: float = 0.7,
        tools: Iterable[ChatCompletionToolUnionParam] | NotGiven = NOT_GIVEN,
        stream: bool = False,
        **kwargs
    ) -> T | ChatCompletionMessage:
        """非流式调用"""

    @overload
    async def invoke(
        self,
        messages: List[dict],
        model: str = None,
        # response_format: type[T] = None,
        extra_body: dict = {"chat_template_kwargs": {"enable_thinking": False}},
        temperature: float = 0.7,
        # tools: Iterable[ChatCompletionToolUnionParam] | NotGiven = NOT_GIVEN,
        stream: bool = True,
        **kwargs
    ) -> T | ChatCompletionMessage:
        """流式调用"""

    def invoke(
        self,
        messages: List[dict],
        model: str = None,
        response_format: Optional[BaseModel] = None,
        extra_body: dict = {"chat_template_kwargs": {"enable_thinking": False}},
        temperature: float = 0.7,
        tools: Iterable[ChatCompletionToolUnionParam] | NotGiven = NOT_GIVEN,
        stream: bool = False,
        **kwargs
    ) -> T | ChatCompletionMessage | AsyncGenerator[StreamOutput, None]:
        model = model or self._default_model_name
        if model is None:
            raise ValueError("Model name must be specified either in the method call or as the default model name.")
        self._record_log(messages, tools=tools)
        if stream:
            return self._stream(
                messages=messages,
                model=model,
                temperature=temperature,
                extra_body=extra_body,
                **kwargs
            )
        return self._invoke(
            messages=messages,
            model=model,
            response_format=response_format,
            extra_body=extra_body,
            temperature=temperature,
            tools=tools,
            **kwargs
        )

    async def _stream(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        extra_body: dict = {"chat_template_kwargs": {"enable_thinking": False}},
        temperature: float = 0.7,
        **kwargs
    ) -> AsyncGenerator[StreamOutput, None]:
        """
        流式调用的实现

            async for event in llm._stream(
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "介绍一下自己吧！"}
                ],
                extra_body={"chat_template_kwargs": {"enable_thinking": True}},
                temperature=0.0
            ):
                if event.thinking_end is False and event.thinking is None:
                    print("\n[思考中....]\n-----------------")
                elif event.thinking:
                    print(event.thinking, end='', flush=True)
                elif event.thinking_end:
                    print("\n[思考结束]\n-----------------")
                elif event.answer_end is False and event.answer is None:
                    print("\n[回答中....]\n-----------------")
                elif event.answer:
                    print(event.answer, end='', flush=True)
                elif event.answer_end:
                    print("\n\n[回答结束]\n-----------------")
        """
        in_thinking = extra_body.get("chat_template_kwargs", {}).get("enable_thinking", False)
        in_answering = False
        async with self._client.chat.completions.stream(
            model=model or self._default_model_name,
            messages=messages,
            temperature=temperature,
            extra_body=extra_body,
            **kwargs
        ) as stream:
            async for event in stream:
                if event.type == "content.delta":
                    content = event.delta
                    if in_thinking:
                        if content == "<think>":
                            yield StreamOutput(thinking_end=False)
                            continue
                        elif content == "</think>":
                            in_thinking = False
                            yield StreamOutput(
                                thinking_snapshot=self._thinking_pattern.sub('', event.snapshot),
                                thinking_end=True
                            )
                            continue
                        else:
                            yield StreamOutput(thinking=content, thinking_end=False)
                    else:
                        if in_answering is False:
                            yield StreamOutput(answer_end=False)
                            in_answering = True
                        yield StreamOutput(answer=content, answer_end=False)
                
                elif event.type == "content.done":
                    yield StreamOutput(
                        answer_snapshot=self._content_pattern.sub('', event.content),
                        answer_end=True
                    )

    async def _invoke(
        self,
        messages: List[dict],
        model: str = None,
        response_format: Optional[BaseModel] = None,
        extra_body: dict = {"chat_template_kwargs": {"enable_thinking": False}},
        temperature: float = 0.7,
        tools: Iterable[ChatCompletionToolUnionParam] | NotGiven = NOT_GIVEN,
        **kwargs
    ) -> T | ChatCompletionMessage:
        """
        非流式调用的实现
            示例1:
                result = await llm._invoke(
                    messages=[
                        {"role": "user", "content": "你好，介绍一下自己吧！"}
                    ]
                )
            示例2（返回JSON对象）:
                class OutputFormatModel(BaseModel):
                    content: str

                result = await llm._invoke(
                    messages=[
                        {"role": "user", "content": "你好，介绍一下自己吧！"}
                    ],
                    response_format=OutputFormatModel
                )
        """
        model_name = model or self._default_model_name
        response_model = self._response_model(response_format)
        if response_model is not None and self._requires_plain_json_response(model_name):
            response = await self._create_completion(
                model=model_name,
                messages=messages,
                extra_body=extra_body,
                temperature=temperature,
                tools=tools,
                **kwargs,
            )
            return self._parse_response_model(response.choices[0].message, response_model)

        func = self._client.chat.completions.create if response_format is None else self._client.chat.completions.parse
        try:
            response = await func(
                model=model_name,
                messages=messages,
                extra_body=extra_body,
                temperature=temperature,
                response_format=response_format,
                tools=tools,
                **kwargs
            )
        except Exception as exc:
            if response_model is None or not self._is_response_format_unsupported(exc):
                raise
            logger.warning("LLM response_format unsupported by provider, retrying with local JSON parsing: %s", exc)
            response = await self._create_completion(
                model=model_name,
                messages=messages,
                extra_body=extra_body,
                temperature=temperature,
                tools=tools,
                **kwargs,
            )
            return self._parse_response_model(response.choices[0].message, response_model)
        message = response.choices[0].message
        if response_model is not None:
            return message.parsed
        if message.tool_calls:
            for tool_call in message.tool_calls:
                tool_call.function.arguments = json_repair.loads(tool_call.function.arguments)
        return message

    async def _create_completion(
        self,
        *,
        model: str,
        messages: List[dict],
        extra_body: dict | None,
        temperature: float,
        tools: Iterable[ChatCompletionToolUnionParam] | NotGiven,
        **kwargs,
    ):
        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            **kwargs,
        }
        if extra_body is not None:
            request_kwargs["extra_body"] = extra_body
        if tools is not NOT_GIVEN:
            request_kwargs["tools"] = tools
        return await self._client.chat.completions.create(**request_kwargs)

    @staticmethod
    def _response_model(response_format: Any) -> type[BaseModel] | None:
        if response_format is None or isinstance(response_format, dict):
            return None
        try:
            if issubclass(response_format, BaseModel):
                return response_format
        except TypeError:
            return None
        return None

    def _requires_plain_json_response(self, model: str | None) -> bool:
        model_text = (model or "").lower()
        base_url = self._base_url.lower()
        return "deepseek" in model_text or "api.deepseek.com" in base_url

    @staticmethod
    def _is_response_format_unsupported(exc: Exception) -> bool:
        message = str(exc).lower()
        return "response_format" in message and any(
            word in message for word in ("unavailable", "unsupported", "not support", "invalid_request_error")
        )

    @staticmethod
    def _parse_response_model(message: ChatCompletionMessage, response_model: type[T]) -> T:
        content = (message.content or "").strip()
        # 去掉 <think>...</think> 标签（部分模型会输出思考过程）
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
        if "{" in content and "}" in content:
            content = content[content.find("{"): content.rfind("}") + 1]
        data = json_repair.loads(content)
        # 兼容：如果模型返回裸 signal 对象（没有 summary/signals 包装），
        # 且 response_model 期望 signals 列表，则自动包装
        if isinstance(data, dict) and "signals" not in data and hasattr(response_model, "model_fields"):
            fields = response_model.model_fields
            if "signals" in fields:
                # 裸信号对象 → 包装为 {"summary": "", "signals": [data]}
                data = {"summary": "", "signals": [data]}
            elif "signal" in data:
                data = {"summary": data.get("summary", ""), "signals": [data["signal"]]}
        elif isinstance(data, list):
            # 模型返回了信号数组 → 包装
            if hasattr(response_model, "model_fields") and "signals" in response_model.model_fields:
                data = {"summary": "", "signals": data}
        return response_model.model_validate(data)

    def split_think(self, content: str) -> ResponseResult:
        answer = self._content_pattern.sub('', content)
        thinking = self._thinking_pattern.sub('', content.replace(answer, ""))
        return ResponseResult(thinking=thinking, answer=answer)
