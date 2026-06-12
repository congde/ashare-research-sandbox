# -*- coding: utf-8 -*-
"""
runtime.types.chat — Chat request DTO models shared between web layer
and engine call sites (PR-E*c of the Agent Engine SDK extraction plan).

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 PR-E*c.

Why this module
---------------
``ExtraBodyModel`` (and its companions ``StaffMemberItem`` /
``ImportedDocument``) used to live exclusively in
``src/web/api/chat/items.py``. Three engine modules needed to
construct or accept the model:

* ``src/agent/base.py`` — ``BaseAgent.__init__`` accepts an
  ``extra_body: ExtraBodyModel`` so subclasses (DeepThink, Coder,
  CoordinatorDelegate, …) can read staff/persona/issue payload from
  the request.
* ``src/agent/schedule/agent_task_dispatcher.py`` — constructs an
  empty ``ExtraBodyModel()`` when no operator-supplied extra body is
  available (e.g. background scheduler dispatch).
* ``src/runtime/conversation/_resume.py`` — reconstructs the original
  turn's ``extra_body`` from the cached Redis session meta so the
  HITL-resumed continuation runs with the same persona/workspace.

That gave engine code a direct dependency on a ``web.api.*`` module,
which violates the SDK extraction boundary (``scripts/check_engine_imports.py``).

PR-E*c moves the DTO definitions HERE (pure Pydantic, zero web/dao/lark
coupling). ``src/web/api/chat/items.py`` keeps the symbols as a
back-compat re-export so existing FastAPI routers / Pydantic schema
generators / OpenAPI emitters keep working unchanged.

Phase 2 (post-extraction): the re-export from ``web.api.chat.items``
is dropped; web code imports directly from ``runtime.types.chat``.
"""

from __future__ import annotations

import base64
import binascii
import sys
from enum import Enum
from typing import Any, Dict, List, Optional

if sys.version_info >= (3, 11):
    from enum import StrEnum  # noqa: F401 — kept for parity with the
                              # legacy web.api.chat.items module which
                              # also defined this fallback for callers
                              # importing StrEnum from that surface.
else:
    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


from pydantic import BaseModel, Field, field_validator


class StaffMemberItem(BaseModel):
    """One roster member when the user @-mentions multiple colleagues."""

    staff_id: Optional[str] = Field(None, description="员工 ID")
    staff_name: Optional[str] = Field(None, description="显示名")
    staff_role: Optional[str] = Field(None, description="角色标签")
    staff_persona: Optional[str] = Field(None, description="口吻与职责说明")


class ImportedDocument(BaseModel):
    """One user-imported reference document for this turn.

    Pre-fix the document body was concatenated into the ``query`` string,
    which (1) tripped the 50 KB ``query`` max_length cap (returning a
    "parameter error" toast before the agent ever ran) and (2) polluted
    both the chat-bubble render and the persisted ``qa.query`` field.
    Now the body travels via this dedicated channel and gets injected
    into ``append_system_prompt`` by ``ResponseMixin``; the chat bubble
    only ever sees a filename chip.

    Caps are tight by design — see docs/导入文档功能修复方案.md §2.1:
      • ``content`` ≤ 1,000,000 chars (~250K tokens; FE pre-truncates
        to 800 K so we have ~1.25× headroom for edge cases)
      • ``name`` ≤ 512 chars (filename injection defence)
    """

    name: str = Field(..., min_length=1, max_length=512, description="文档文件名")
    content: str = Field(
        ...,
        min_length=1,
        max_length=1_000_000,
        description="文档正文（前端已截断到 800K）",
    )
    file_base64: Optional[str] = Field(
        None,
        description=(
            "Optional original file bytes (base64). When present and workspace "
            "is bound, backend writes the binary to attachments/ before agent run."
        ),
    )
    mime_type: Optional[str] = Field(
        None,
        max_length=128,
        description="MIME type of the original upload (metadata only).",
    )

    @field_validator("file_base64")
    @classmethod
    def _validate_file_base64_size(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return value
        try:
            decoded = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"invalid file_base64: {exc}") from exc
        max_bytes = 10 * 1024 * 1024
        if len(decoded) > max_bytes:
            raise ValueError(f"file_base64 exceeds {max_bytes} bytes")
        return value


class ExtraBodyModel(BaseModel):
    # eventId: Optional[str] = Field(None, description="主动触达的事件ID")
    # eventSummary: str = Field("", description="主动触达的事件摘要")

    staff_id: Optional[str] = Field(None, description="被 @ 的员工 ID（前端与在线列表一致）")
    staff_ids: Optional[List[str]] = Field(None, description="多 @mention 的员工 ID 列表（触发 Coordinator）")
    staff_name: Optional[str] = Field(None, description="员工显示名")
    staff_role: Optional[str] = Field(None, description="角色标签，如 PM / Quant，用于展示与提示词")
    staff_persona: Optional[str] = Field(None, description="该角色的职责与口吻说明，注入回复提示词")
    staff_members: Optional[List[StaffMemberItem]] = Field(
        None,
        description="多人 @ 时全员列表；≥2 时触发圆桌讨论式回复",
    )
    staff_panel_everyone: Optional[bool] = Field(
        None,
        description="为 True 时表示用户 @all / 全员；要求名单内每人至少发言一次，多轮讨论",
    )

    ticket_id: Optional[str] = Field(None, description="协作工单 ID（TKT-xxxxxxxx）")
    ticket_title: Optional[str] = Field(None, description="工单标题缓存，供模型上下文")
    ticket_status: Optional[str] = Field(None, description="工单状态缓存：open / in_progress / …")

    # Issue subtask — Story / workflow node tasks executed via ConversationRuntime (human + LLM).
    issue_id: Optional[str] = Field(None, description="子任务 Issue UUID（issues.id，issue_type=task）")
    issue_title: Optional[str] = Field(None, description="子任务标题缓存（首屏用户消息前缀，可与 DB 对齐）")
    parent_issue_id: Optional[str] = Field(None, description="父 Story Issue UUID")
    workflow_run_id: Optional[str] = Field(None, description="runtime_workflow_runs.id")
    workflow_graph_node_id: Optional[str] = Field(None, description="DAG 节点 id")

    # Claude Code–style system prompt orchestration (see agent.prompt.effective_system)
    override_system_prompt: Optional[str] = Field(
        None,
        description="完全替换默认 MCP system prompt（最高优先级）",
    )
    custom_system_prompt: Optional[str] = Field(
        None,
        description="替换 MCP 模板正文（不经过 Jinja/MCP 拉取；与 override 二选一语义：仍低于 override）",
    )
    append_system_prompt: Optional[str] = Field(
        None,
        description="在有效 system prompt 末尾追加（与 conf context.append_system_prompt / 环境变量叠加）",
    )

    environment_id: Optional[str] = Field(None, description="执行环境 ID，绑定到 Session（§12.1）")

    collab_workspace_relative: Optional[str] = Field(
        None,
        description=(
            "Staff AI 协同工作目录名（相对段，如 aibuddy-workspace）。解析到 "
            "collab-workspaces/{workspace_id}/<name>，不依赖 AGENT_WORKSPACE_ROOT。"
        ),
    )
    collab_workspace_path: Optional[str] = Field(
        None,
        description=(
            "Staff AI 协同绝对路径（用户在本机选择的工作目录）。当次对话绑定为 "
            "file_tools / bash 沙箱根；本地开发允许本机任意目录，生产环境需在允许根下。"
        ),
    )
    staff_ai_collab: Optional[bool] = Field(
        None,
        description=(
            "kubuddy-web AI 协同页发起的对话。为 true 时文件/git 工具仅使用用户选择的工作目录，"
            "未选择时不回退 AGENT_WORKSPACE_ROOT。"
        ),
    )
    schedule_create_mode: Optional[bool] = Field(
        None,
        description=(
            "定时任务对话创建模式。为 true 时 Gateway 仅暴露 staff_schedule_create + "
            "direct_response，禁止 write_file/bash 等 mutating 工具。"
        ),
    )
    schedule_tz_offset_minutes: Optional[int] = Field(
        None,
        description=(
            "Browser local timezone offset east of UTC in minutes "
            "(e.g. 480 for UTC+8). Used by staff_schedule_create to convert "
            "local frequency+time into UTC cron."
        ),
    )

    # Phase 7.2 — Multimodal Input
    # Each entry is either a data URI (``data:image/png;base64,...``) or a raw
    # base64 string.  Max 10 images per message; unsupported formats are silently
    # skipped.  Gated by the ``multimodal_input`` ModuleToggle.
    images: Optional[List[str]] = Field(
        None,
        description="Base64-encoded images (data URI or raw base64). Max 10 per message.",
    )

    # Sprint 9 follow-up — attachment_id refs uploaded via
    # ``POST /api/v1/coder/attachments``. Gateway.dispatch resolves
    # each id to inline image content via ``resolve_attachment_refs``
    # and stores the result on ``agent._user_attachments``.
    # ResponseMixin then injects them as multimodal content blocks in
    # the final-response LLM call. Preferred over raw base64 ``images``
    # because uploads are deduped (SHA-256), survive across turns, and
    # never inflate the SSE request payload.
    # max_length=10 stops a runaway / forged client from sending 10k ids
    # before Pydantic deserialises them all into memory; the same cap is
    # re-asserted in Gateway as belt-and-braces in case the field shape
    # ever changes.
    attachment_ids: Optional[List[str]] = Field(
        None,
        max_length=10,
        description=(
            "List of attachment_id (hex uuid4) values previously uploaded via "
            "POST /api/v1/coder/attachments. Gateway resolves to inline image "
            "content for multimodal LLM calls. Max 10 per message."
        ),
    )

    # User-imported reference documents for this turn — content travels
    # OUT-OF-BAND from ``query`` so it doesn't (a) trip the 50 KB query
    # cap or (b) pollute the bubble / persisted qa.query field.
    # ``ResponseMixin._build_llm_context`` injects each entry into the
    # ``append_system_prompt`` slot as a ``<document name="...">…</document>``
    # block so the LLM sees them as authoritative context. Not persisted
    # into qa.uploadedFile — these are turn-scoped LLM context, not
    # conversation transcript artefacts.
    imported_documents: Optional[List[ImportedDocument]] = Field(
        None,
        max_length=5,
        description=(
            "Reference documents for this turn (5 × 1M ≈ 1.25M tokens, "
            "aligned with Claude 1M context). Inject into append_system_prompt; "
            "do NOT write to qa.query."
        ),
    )

    model: Optional[str] = Field(
        None,
        description=(
            "User-selected chat / reasoning model display key (e.g. 'GLM_5_1', "
            "'QWEN_3_5'). When provided, the Gateway threads this through to "
            "the Router so intent classification runs on the same model the "
            "user chose, falling back to the configured router_llm chain only "
            "if that model errors."
        ),
    )

    selectedTools: Optional[List[Dict[str, Any]]] = Field(
        None,
        description=(
            "kubuddy-web AI 协同工具选择：每项含 name，可选 source=mcp|cli。"
            "Gateway 在 ToolPolicy mode=full 时将 ToolRegistry 缩到所选工具 "
            "+ direct_response；协同请求还会在 primitive 模式下注入 bash_exec。"
        ),
    )

    selectedSkills: Optional[List[Dict[str, Any]]] = Field(
        None,
        description=(
            "kubuddy-web AI 协同 Skill Hub 选择：每项含 hub_id（及可选 name/description）。"
            "服务端把每条 hub_id 注入 catalog 为 ``collab_hub__<hub_id>`` 条目（Phase 2 可看到完整 "
            "SKILL.md），并把这些 key prepend 到 Phase 1 LLM 选择结果前面 + 改 ``primary_intent``。"
            "注意：**Phase 1 LLM 仍照常运行**（不跳过），hub 选择只是 merge 不是 lock —— "
            "LLM 自选的工具仍保留。要真正硬锁工具调用，请使用 ``selectedTools``。"
            "(meegle 是特例：``selectedSkills`` 里 name 含 'meegle' 会触发 hard bypass 到 meegle 工具。)"
        ),
    )

    model_config = {
        "extra": "allow"
    }


__all__ = [
    "ExtraBodyModel",
    "ImportedDocument",
    "StaffMemberItem",
    "StrEnum",
]
