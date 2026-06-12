# -*- coding: utf-8 -*-
'''
@Time    :   2026/01/03 22:01:09
'''

import json
import logging
from typing import AsyncGenerator, List, Dict

from openai import AsyncOpenAI

from web.config import config
from llm.base import BaseLLM, StreamOutput, ChatCompletionMessage, T


logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = sum(
        1
        for char in text
        if "\u4e00" <= char <= "\u9fff"
        or "\u3040" <= char <= "\u309f"
        or "\u30a0" <= char <= "\u30ff"
        or "\uac00" <= char <= "\ud7af"
    )
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4)


def estimate_messages_tokens(messages: List[Dict[str, str]]) -> int:
    total = 0
    for message in messages:
        total += 4
        total += estimate_tokens(message.get("content", ""))
    return total


def truncate_tool_result(text: str, max_chars: int = 60000) -> str:
    if not text or len(text) <= max_chars:
        return text
    marker = (
        f"\n\n... [TOOL RESULT TRUNCATED: original {len(text)} chars, "
        f"kept {max_chars} chars] ...\n\n"
    )
    keep = max_chars - len(marker)
    head_len = int(keep * 0.7)
    tail_len = keep - head_len
    return text[:head_len] + marker + text[-tail_len:]


def flatten_tool_messages_for_chat(messages: List[Dict]) -> List[Dict]:
    """Normalize messages for strict Chat Completions providers (DeepSeek/OpenAI).

    Some code paths emit ``assistant`` (without ``tool_calls``) + ``tool`` pairs
    to pass tool output into the final synthesis prompt. That is rejected with
    400: "Messages with role 'tool' must be a response to a preceding message
    with 'tool_calls'". Convert those pairs — and orphan ``tool`` messages —
    into plain ``user`` context blocks.
    """
    flat: List[Dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role")
        if (
            role == "assistant"
            and i + 1 < len(messages)
            and messages[i + 1].get("role") == "tool"
            and not msg.get("tool_calls")
        ):
            tool_msg = messages[i + 1]
            tool_label = tool_msg.get("name") or tool_msg.get("tool_call_id") or "tool"
            content = tool_msg.get("content") or ""
            flat.append({
                "role": "user",
                "content": f"[Tool result: {tool_label}]\n{content}",
            })
            i += 2
            continue
        if role == "tool":
            tool_label = msg.get("name") or msg.get("tool_call_id") or "tool"
            content = msg.get("content") or ""
            flat.append({
                "role": "user",
                "content": f"[Tool result: {tool_label}]\n{content}",
            })
            i += 1
            continue
        flat.append(msg)
        i += 1
    return flat


def qwen_extra_body(model: str, *, enable_thinking: bool = False, enable_research: bool = False):
    """Qwen-only chat template flags; DeepSeek/OpenAI models must not receive these."""
    if not (model or "").lower().startswith("qwen"):
        return None
    body = {"chat_template_kwargs": {"enable_thinking": enable_thinking}}
    if enable_research:
        body["chat_template_kwargs"]["enable_research"] = enable_research
    return body


async def stream_llm(
    client: AsyncOpenAI,
    messages,
    model="Qwen3.5-27B",
    max_tokens=6000,
    temperature=0.7,
    timeout=900,
    extra_body=None,
    **kwargs
):
    if extra_body is None:
        extra_body = qwen_extra_body(model)
    async with client.chat.completions.stream(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        extra_body=extra_body,
        **kwargs
    ) as stream:
        async for event in stream:
            if event.type == "content.delta":
                yield event.delta


def _get_model_context_limit() -> int:
    """从配置获取模型上下文窗口大小。"""
    try:
        ctx = getattr(config, "context", None)
        return int(getattr(ctx, "model_context_window", 262144)) if ctx else 262144
    except Exception:
        return 262144


def _get_tool_result_max_chars() -> int:
    """从配置获取工具返回结果最大字符数。"""
    try:
        ctx = getattr(config, "context", None)
        return int(getattr(ctx, "tool_result_max_chars", 60000)) if ctx else 60000
    except Exception:
        return 60000


def _truncate_messages_to_fit(
    messages: List[Dict[str, str]],
    max_tokens: int,
) -> List[Dict[str, str]]:
    """
    在发送给 LLM 之前，检查 messages 总 token 数是否超出上下文窗口。
    如果超出，按内容长度从大到小截断最大的消息（通常是工具返回结果或系统提示）。

    策略：
    - 保持消息结构和顺序不变
    - 仅截断内容最长的消息
    - 每次截一半，直到总 token 数 < max_tokens
    """
    total = estimate_messages_tokens(messages)
    if total <= max_tokens:
        return messages

    logger.warning(
        f"Context overflow detected: {total} tokens > {max_tokens} limit. "
        f"Truncating large messages."
    )

    tool_result_max_chars = _get_tool_result_max_chars()
    result = []
    for msg in messages:
        content = msg.get("content", "")
        if content and len(content) > tool_result_max_chars:
            original_len = len(content)
            content = truncate_tool_result(content, tool_result_max_chars)
            logger.warning(
                f"Truncated {msg.get('role', '?')} message: "
                f"{original_len} -> {len(content)} chars"
            )
            msg = {**msg, "content": content}
        result.append(msg)

    final_total = estimate_messages_tokens(result)
    logger.info(
        f"After truncation: {total} -> {final_total} tokens "
        f"(limit={max_tokens})"
    )
    return result


async def final_response(
    client: AsyncOpenAI,
    messages: List[Dict[str, str]],
    model="Qwen3.5-27B",
    max_tokens=6000,
    temperature=0.7,
    timeout=900,
    extra_body=None,
    system_prompt_name: str = None,
    system_prompt_vars: dict = None,
    **kwargs
):
 
    
    if system_prompt_name:
        from mcp.mcp_http_client import mcp_client

        system_prompt = await mcp_client.get_prompt(system_prompt_name, data=system_prompt_vars)
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}, *[m for m in messages if m.get("role") != "system"]]

    # 在发送给 LLM 之前，检查并截断超长上下文
    messages = flatten_tool_messages_for_chat(messages)
    context_limit = _get_model_context_limit() - max_tokens  # 留出输出空间
    messages = _truncate_messages_to_fit(messages, context_limit)

    messages_json = json.dumps(messages, ensure_ascii=False, indent=2)
    logger.info(f"LLM final_response system prompt（{system_prompt_name}），messages_json:\n{messages_json}\n\n")

    # 如果是 coin_screener 工具，temperature 设为 0
    if system_prompt_vars and system_prompt_vars.get("tool_name") == "coin_screener":
        temperature = 0

    async for content in stream_llm(
        client,
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        extra_body=extra_body,
        **kwargs
    ):
        yield content


class DefaultLLM(BaseLLM):
    async def ainvoke(self, *args, **kwargs) -> T | ChatCompletionMessage:
        return await super()._invoke(*args, **kwargs)

    async def stream(self, *args, **kwargs) -> AsyncGenerator[StreamOutput, None]:
        async for event in super()._stream(*args, **kwargs):
            yield event


llm = DefaultLLM(
    base_url=config.openai_api_base,
    api_key=config.openai_api_key,
    default_model_name=config.llm_model_name,
    timeout=60
)
