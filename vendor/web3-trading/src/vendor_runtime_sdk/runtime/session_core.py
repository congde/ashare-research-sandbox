# -*- coding: utf-8 -*-
"""
Session — 会话管理 + JSONL Journal + Compaction.

Key design:
- Append-only JSONL journal for crash recovery
- Auto-compaction when token budget exceeded (with 4-layer priority extraction)
- Session forking for sub-lanes
- Resume instruction to prevent context degradation after compaction

State machine:
  Fresh → Active (Accumulating → Compacted) → Persisted → Rotated
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, AsyncGenerator

from vendor_runtime_sdk.runtime.protocols import LLMClient, AssistantEvent, ToolResult
from vendor_runtime_sdk.runtime.prompt_builder import SystemPromptBuilder

logger = logging.getLogger(__name__)

RESUME_INSTRUCTION = (
    "Continue the conversation from where it left off. "
    "Resume directly — do not acknowledge the summary, "
    "do not recap what was happening."
)


@dataclass
class CompactionResult:
    """压缩操作结果"""

    summary: str
    removed_count: int
    compacted_messages: List[Dict]


class SessionJournal:
    """Append-only JSONL 日志 — 用于崩溃恢复"""

    def __init__(self, path: Path):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = None

    def append(self, entry: Dict) -> None:
        """追加一条记录到 JSONL 文件"""
        if self._file is None:
            self._file = open(self._path, "a", encoding="utf-8")
        entry["_ts"] = time.time()
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    @classmethod
    def read_all(cls, path: Path) -> List[Dict]:
        """读取 JSONL 文件中的所有记录"""
        if not path.exists():
            return []
        entries = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries


class Session:
    """
    对话会话 — 管理 messages + auto-compaction + JSONL journal.

    Usage:
        session = Session(session_id="abc", workspace_root=Path("/tmp/abc"))
        session.push_user_text("Hello")
        result = await session.maybe_auto_compact(llm_client, threshold=100_000)
    """

    def __init__(
        self,
        session_id: str,
        workspace_root: Optional[Path] = None,
        preamble: str = "",
        auto_compact_threshold: int = 100_000,
    ):
        self.session_id = session_id
        self.workspace_root = workspace_root
        self.messages: List[Dict] = []
        self._preamble = preamble
        self._journal: Optional[SessionJournal] = None
        self._compaction_count: int = 0
        self._cumulative_tokens: int = 0
        self._auto_compact_threshold = auto_compact_threshold
        self._lane_id: Optional[str] = None

        # Initialize journal if workspace_root provided
        if workspace_root is not None:
            runtime_dir = workspace_root / ".runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            journal_path = runtime_dir / f"session_{session_id}.jsonl"
            self._journal = SessionJournal(journal_path)

    # ──────────────── Message Operations ────────────────

    def push_user_text(self, text: str) -> None:
        """添加用户消息"""
        msg = {"role": "user", "content": text}
        self.messages.append(msg)
        self._journal_append(msg)

    def push_assistant_message(self, content: str, tool_calls: Optional[List[Dict]] = None) -> None:
        """添加助手消息"""
        msg: Dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)
        self._journal_append(msg)

    def push_tool_result(self, tool_use_id: str, content: str, is_error: bool = False) -> None:
        """添加工具执行结果"""
        msg = {
            "role": "tool",
            "tool_call_id": tool_use_id,
            "content": content,
        }
        if is_error:
            msg["is_error"] = True
        self.messages.append(msg)
        self._journal_append(msg)

    def push_system_message(self, content: str) -> None:
        """添加系统消息（通常用于 compaction 后替换 system prompt）"""
        msg = {"role": "system", "content": content}
        self.messages.append(msg)
        self._journal_append(msg)

    # ──────────────── Token Budget ────────────────

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """记录 token 消耗"""
        self._cumulative_tokens += input_tokens + output_tokens

    @property
    def cumulative_tokens(self) -> int:
        return self._cumulative_tokens

    @property
    def needs_compaction(self) -> bool:
        return self._cumulative_tokens >= self._auto_compact_threshold

    # ──────────────── Compaction ────────────────

    async def maybe_auto_compact(
        self, llm_client: LLMClient, threshold: Optional[int] = None
    ) -> Optional[CompactionResult]:
        """如果 token 累积超过阈值，触发压缩"""
        effective_threshold = threshold or self._auto_compact_threshold
        if self._cumulative_tokens < effective_threshold:
            return None
        return await self._compact(llm_client)

    async def _compact(self, llm_client: LLMClient) -> CompactionResult:
        """LLM 驱动的智能摘要压缩 (with 4-layer priority extraction)"""
        from vendor_runtime_sdk.runtime.session_compaction import compact_session

        result = await compact_session(
            messages=self.messages,
            llm_client=llm_client,
            preamble=self._preamble,
            reserve_count=4,
        )

        self.messages = result.compacted_messages
        self._compaction_count += 1
        self._cumulative_tokens = 0  # Reset after compaction

        # Journal the compaction event
        self._journal_append({
            "type": "compaction",
            "summary": result.summary,
            "removed_count": result.removed_count,
            "compaction_count": self._compaction_count,
        })

        return result

    # ──────────────── Session Fork ────────────────

    def fork(self, new_session_id: Optional[str] = None) -> "Session":
        """Fork 当前 session，生成独立的子 session（用于 Lane 隔离）"""
        sid = new_session_id or f"{self.session_id}_fork_{uuid.uuid4().hex[:8]}"
        new_session = Session(
            session_id=sid,
            workspace_root=self.workspace_root,
            preamble=self._preamble,
            auto_compact_threshold=self._auto_compact_threshold,
        )
        # Copy messages (shallow copy — don't share reference)
        new_session.messages = list(self.messages)
        return new_session

    # ──────────────── Journal ────────────────

    def _journal_append(self, msg: Dict) -> None:
        if self._journal is not None:
            self._journal.append(msg)

    def close(self) -> None:
        """关闭 journal 文件"""
        if self._journal is not None:
            self._journal.close()

    # ──────────────── Repr ────────────────

    def __repr__(self) -> str:
        return (
            f"Session(id={self.session_id!r}, "
            f"messages={len(self)}, "
            f"tokens={self._cumulative_tokens}, "
            f"compactions={self._compaction_count})"
        )

    def __len__(self) -> int:
        return len(self.messages)
