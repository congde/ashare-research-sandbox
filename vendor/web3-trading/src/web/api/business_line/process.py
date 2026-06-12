# -*- coding: utf-8 -*-
'''
@Time    :   2026/02/05 11:02:20
workflow通用能力
'''

import json
import time
import logging
from enum import StrEnum
from typing import List, Dict, Any, Optional

from fastapi import Request, Body, BackgroundTasks, Header
from pydantic import BaseModel, Field

from web.router import BaseRouter
from agent.schema import SourceType as SchemaSourceType
from web.context import context
from workflow.process import create_workflow
from web.config import workflow_config
from web.exceptions import HttpException
from web import code_msg


logger = logging.getLogger(__name__)


class SourceType(StrEnum):
    pass


class SkillName(StrEnum):
    seo_faq_generator = "seo_faq_generator"  # SEO FAQ 内容生成


class RequestModel(BaseModel):
    query: str = Field("", description="问句")
    extraQuery: Optional[dict] = Field({}, description="额外问句参数")
    skillName: SkillName = Field(..., description="技能名称")
    callbackUrl: str = Field(..., description="回调地址")
    extraBody: Optional[dict] = Field({}, description="额外参数")


# ════════════════════════════════════════════════════════════════════
# /sync_process 同步接口模型
# ════════════════════════════════════════════════════════════════════

class SyncRequestModel(BaseModel):
    """POST /api/business_line/sync_process 同步请求体。

    后端通过 skillName 指定技能，query 虽然必填但 copilot 场景一般传
    null（对话数据放在 extraBody 中）。
    """
    query: Optional[str] = Field(None, description="问句（可为 null）")
    extraQuery: Optional[dict] = Field(None, description="问句相关的额外信息")
    skillName: str = Field(..., description="技能名称，如 copilot_agent / seo_faq_generator")
    extraBody: Optional[dict] = Field(None, description="额外参数；copilot_agent 场景下包含完整 task 请求")


def _sync_response(
    code: str = "200",
    msg: str = "success",
    data: Optional[Dict[str, Any]] = None,
    retry: bool = False,
    success: bool = True,
) -> Dict[str, Any]:
    """构造 /sync_process 统一响应体"""
    return {
        "code": code,
        "msg": msg,
        "data": data or {},
        "retry": retry,
        "success": success,
    }


async def _run_copilot_agent(extra_body: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 extraBody 解析 copilot task 并同步执行，返回结果。

    extraBody 约定字段：
      - user_id:      用户 ID（必填）
      - task:         任务类型（必填）：classify / analysis / comfort / conclusion / extract / query / search
      - site_type:    站点类型，默认 GLOBAL
      - title:        工单标题
      - data:         对话消息数组 或 文本（conclusion 专用）
      - level_1/level_2/level_3: query 任务的客服确认分类
      - type:         query 任务的查询类型
      - input_params: query 任务的客服参数
      - query:        search 任务的检索关键词
      - top_k:        search 任务的返回上限
    """
    from agent.copilot.agent import copilot_agent
    from agent.copilot.schemas import CopilotRequest, ChatMessage

    user_id = extra_body.get("user_id", "")
    task = extra_body.get("task", "")
    if not user_id or not task:
        return {
            "success": False,
            "error": "extraBody 中缺少 user_id 或 task",
        }

    # 将 data 中的 dict 转为 ChatMessage
    raw_data = extra_body.get("data")
    parsed_data = raw_data
    if isinstance(raw_data, list) and task != "search":
        parsed_data = []
        for item in raw_data:
            if isinstance(item, dict):
                parsed_data.append(ChatMessage(**item))
            elif isinstance(item, ChatMessage):
                parsed_data.append(item)

    copilot_req = CopilotRequest(
        user_id=user_id,
        site_type=extra_body.get("site_type", "GLOBAL"),
        task=task,
        title=extra_body.get("title", ""),
        data=parsed_data,
        level_1=extra_body.get("level_1", ""),
        level_2=extra_body.get("level_2", ""),
        level_3=extra_body.get("level_3", ""),
        type=extra_body.get("type", ""),
        input_params=extra_body.get("input_params", {}),
        query=extra_body.get("query", ""),
        top_k=extra_body.get("top_k", 20),
    )

    response = await copilot_agent.process(copilot_req)
    return response.model_dump()


class WorkFlowApi(BaseRouter):
    def __init__(self):
        super().__init__(prefix="/api/business_line")

        @self._router.post("/process")
        async def process(
            request: RequestModel,
            background_tasks: BackgroundTasks,
        ):
            skill_name = request.skillName.value
            skill_config = workflow_config.get(skill_name, {})
            if not skill_config.get("enable", False):
                logger.warning(f"skill {skill_name} disabled, please check workflow config")
                raise HttpException(code=code_msg.CODE_SKILL_DISABLED, skill_name=skill_name)
            graph = create_workflow(skill_name)
            background_tasks.add_task(
                graph.ainvoke,
                {
                    "start_time": time.time(),
                    "user_id": context.get("user_id"),
                    "query": request.query,
                    "extra_query": request.extraQuery,
                    "skill_config": skill_config,
                    "extra_body": request.extraBody,
                    "callback_url": request.callbackUrl,

                    "messages": [],
                    "tools": [],

                    "result": None,
                    "status": "Ok",
                    "reason": "",
                }
            )

        @self._router.post("/sync_process")
        async def sync_process(
            request: SyncRequestModel,
            x_user_id: Optional[str] = Header(None, alias="X-USER-ID"),
        ):
            """
            同步业务线处理接口。

            与 /process（异步回调）不同，/sync_process 同步等待执行完成后直接返回结果。

            请求体：
              - query:      问句（copilot 场景一般为 null，对话放在 extraBody）
              - extraQuery:  额外问句参数
              - skillName:   技能名称
                             - copilot_agent: copilot 客服助手（extraBody 包含 task 等字段）
                             - seo_faq_generator: 其他已注册工作流（同步执行）
              - extraBody:   额外参数，copilot_agent 下包含完整请求数据

            copilot_agent 的 extraBody 约定：
              {
                "user_id":      "用户 ID",
                "task":         "classify / analysis / comfort / conclusion / extract / query / search",
                "site_type":    "GLOBAL",
                "title":        "工单标题",
                "data":         [对话消息数组],
                "level_1":      "一级分类（query 任务）",
                "level_2":      "二级分类",
                "level_3":      "三级分类",
                "type":         "查询类型",
                "input_params": {},
                "query":        "检索关键词（search 任务）",
                "top_k":        20
              }

            响应格式：
              {
                "code": "200",
                "msg": "success",
                "data": {
                  "query":     "原始问句",
                  "extraBody": { ...copilot 输出或工作流结果... },
                  "result":    ""
                },
                "retry": false,
                "success": true
              }
            """
            extra_body = request.extraBody or {}
            user_id = x_user_id or extra_body.get("user_id", "")

            # ── copilot_agent：copilot 全部 task 统一入口 ──────────
            if request.skillName == "copilot_agent":
                try:
                    copilot_result = await _run_copilot_agent(extra_body)
                    copilot_success = copilot_result.get("success", True)
                    copilot_retry = copilot_result.get("retry", False)

                    return _sync_response(
                        code="200" if copilot_success else "500",
                        msg=copilot_result.get("msg", "success"),
                        data={
                            "query": request.query,
                            "extraBody": copilot_result.get("data") or {},
                            "result": "",
                        },
                        retry=copilot_retry,
                        success=copilot_success,
                    )
                except Exception as e:
                    logger.error(f"[sync_process] copilot_agent error: {e}", exc_info=True)
                    return _sync_response(
                        code="500",
                        msg=str(e),
                        data={
                            "query": request.query,
                            "extraBody": {},
                            "result": "",
                        },
                        retry=False,
                        success=False,
                    )

            # ── 其他工作流技能：同步执行 LangGraph 工作流 ──────────
            skill_config = workflow_config.get(request.skillName, {})
            if not skill_config.get("enable", False):
                return _sync_response(
                    code="400",
                    msg=f"Skill '{request.skillName}' is disabled or not found",
                    retry=False,
                    success=False,
                )

            try:
                graph = create_workflow(request.skillName)
                state = await graph.ainvoke({
                    "start_time": time.time(),
                    "user_id": user_id,
                    "query": request.query or "",
                    "extra_query": request.extraQuery,
                    "skill_config": skill_config,
                    "extra_body": extra_body,
                    "callback_url": "",

                    "messages": [],
                    "tools": [],

                    "result": None,
                    "status": "Ok",
                    "reason": "",
                })

                workflow_status = state.get("status", "Ok")
                workflow_result = state.get("result", "")
                if isinstance(workflow_result, dict):
                    workflow_result = json.dumps(workflow_result, ensure_ascii=False)

                return _sync_response(
                    code="200" if workflow_status == "Ok" else "500",
                    msg="success" if workflow_status == "Ok" else state.get("reason", ""),
                    data={
                        "query": request.query,
                        "extraBody": extra_body,
                        "result": workflow_result or "",
                    },
                    retry=False,
                    success=(workflow_status == "Ok"),
                )
            except Exception as e:
                logger.error(f"[sync_process] workflow error: skill={request.skillName}, {e}", exc_info=True)
                return _sync_response(
                    code="500",
                    msg=str(e),
                    data={
                        "query": request.query,
                        "extraBody": extra_body,
                        "result": "",
                    },
                    retry=False,
                    success=False,
                )
