# -*- coding: utf-8 -*-
"""
Session Compaction — LLM-driven summarization with 4-layer priority extraction.

Priority levels (from claw-code V2):
  Priority 0: Headers, Core Details          ← Always preserved
  Priority 1: Section Headers
  Priority 2: Bullet Points
  Priority 3: Everything Else                ← Discarded first

Compaction sequence:
  1. Extract priority blocks from messages
  2. Memory flush (persist critical state)
  3. LLM summarization (preserving P0/P1 blocks)
  4. Build compacted messages: [system_summary] + [recent N messages]
  5. Inject RESUME_INSTRUCTION to prevent context degradation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, List, Optional

from vendor_runtime_sdk.runtime.protocols import LLMClient, AssistantEvent

logger = logging.getLogger(__name__)


# ──────────────── Priority Extraction ────────────────


class BlockPriority(IntEnum):
    """4 层优先级 — 数字越小越重要"""

    HEADERS = 0           # 标题 / 核心元数据 — 总是保留
    SECTION_HEADERS = 1   # 段落标题
    BULLETS = 2           # 列表项
    OTHER = 3             # 普通文本 — 优先丢弃


@dataclass
class PrioritizedBlock:
    """按优先级分级的消息块"""

    priority: BlockPriority
    content: str
    source_message_index: int


def extract_priority_blocks(
    messages: List[Dict],
) -> Dict[BlockPriority, List[PrioritizedBlock]]:
    """从消息列表提取按优先级分组的块"""
    blocks: Dict[BlockPriority, List[PrioritizedBlock]] = {p: [] for p in BlockPriority}

    for idx, msg in enumerate(messages):
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("# "):
                blocks[BlockPriority.HEADERS].append(
                    PrioritizedBlock(BlockPriority.HEADERS, line, idx)
                )
            elif stripped.startswith("## "):
                blocks[BlockPriority.SECTION_HEADERS].append(
                    PrioritizedBlock(BlockPriority.SECTION_HEADERS, line, idx)
                )
            elif stripped.startswith(("- ", "* ", "1. ")):
                blocks[BlockPriority.BULLETS].append(
                    PrioritizedBlock(BlockPriority.BULLETS, line, idx)
                )
            else:
                blocks[BlockPriority.OTHER].append(
                    PrioritizedBlock(BlockPriority.OTHER, line, idx)
                )
    return blocks


def build_priority_preserved_text(
    blocks: Dict[BlockPriority, List[PrioritizedBlock]],
    max_chars: int = 8192,
) -> str:
    """按优先级构建保留文本 — P0 全部保留，P1/P2 按预算裁剪，P3 仅摘要"""
    result_parts: List[str] = []

    # Priority 0: Always preserved
    for block in blocks.get(BlockPriority.HEADERS, []):
        result_parts.append(block.content)

    current_len = sum(len(p) for p in result_parts)

    # Priority 1: Section headers — preserved within budget
    for block in blocks.get(BlockPriority.SECTION_HEADERS, []):
        if current_len + len(block.content) + 1 <= max_chars:
            result_parts.append(block.content)
            current_len += len(block.content) + 1

    # Priority 2: Bullets — preserved within remaining budget
    for block in blocks.get(BlockPriority.BULLETS, []):
        if current_len + len(block.content) + 1 <= max_chars:
            result_parts.append(block.content)
            current_len += len(block.content) + 1

    return "\n".join(result_parts)


# ──────────────── Compaction Engine ────────────────


@dataclass
class CompactionResult:
    """压缩操作结果"""

    summary: str
    removed_count: int
    compacted_messages: List[Dict]


async def compact_session(
    messages: List[Dict],
    llm_client: LLMClient,
    preamble: str = "",
    reserve_count: int = 4,
) -> CompactionResult:
    """
    对 session messages 执行压缩:
    1. 提取 4 层优先级块
    2. LLM 摘要旧消息
    3. 保留最近 N 条消息
    4. 组装压缩后消息列表
    """
    from vendor_runtime_sdk.runtime.session_core import RESUME_INSTRUCTION

    if len(messages) <= reserve_count + 1:
        # 消息太少，不需要压缩
        return CompactionResult(
            summary="",
            removed_count=0,
            compacted_messages=messages,
        )

    old_messages = messages[:-reserve_count]
    recent = messages[-reserve_count:]

    # Step 1: Extract priority blocks from old messages
    prioritized = extract_priority_blocks(old_messages)
    preserved_text = build_priority_preserved_text(prioritized)

    # Step 2: LLM summarization
    summary = await _generate_summary(llm_client, old_messages, preserved_text)

    # Step 3: Build compacted messages
    system_content = f"{preamble}\n\n" if preamble else ""
    system_content += f"[Conversation Summary]\n{summary}\n\n"
    if preserved_text:
        system_content += f"[Preserved Headers]\n{preserved_text}\n\n"
    system_content += (
        "Recent messages are preserved verbatim.\n\n"
        f"{RESUME_INSTRUCTION}"
    )

    compacted = [{"role": "system", "content": system_content}] + recent

    return CompactionResult(
        summary=summary,
        removed_count=len(old_messages),
        compacted_messages=compacted,
    )


async def _generate_summary(
    llm_client: LLMClient,
    old_messages: List[Dict],
    preserved_text: str,
) -> str:
    """使用 LLM 生成旧消息的语义摘要"""
    # Build a condensed representation of old messages for summarization
    conversation_text = _messages_to_text(old_messages)

    summarization_prompt = (
        "Summarize the following conversation concisely, preserving key facts, "
        "decisions, and outcomes. Do not add any commentary. "
        "Output the summary directly.\n\n"
        f"--- Conversation ---\n{conversation_text}\n--- End ---"
    )

    try:
        result = await llm_client.complete(
            messages=[{"role": "user", "content": summarization_prompt}],
            system_prompt="You are a conversation summarizer. Be concise and factual.",
            tools=[],
            max_tokens=2048,
        )
        return result.text.strip()
    except Exception as e:
        logger.warning("Compaction summarization failed, using fallback: %s", e)
        # Fallback: use preserved headers as summary
        if preserved_text:
            return f"[Auto-summary fallback — preserved headers]\n{preserved_text}"
        return "[Compaction summary unavailable — conversation was too long]"


def _messages_to_text(messages: List[Dict], max_chars: int = 32000) -> str:
    """将消息列表转为纯文本（用于 LLM 摘要输入）"""
    parts: List[str] = []
    total_len = 0
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = str(content)
        line = f"[{role}]: {content}"
        if total_len + len(line) > max_chars:
            break
        parts.append(line)
        total_len += len(line)
    return "\n".join(parts)
