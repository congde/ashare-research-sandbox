# -*- coding: utf-8 -*-
'''
@Time    :   2026/02/05 11:02:20
'''

import asyncio
import logging
from enum import StrEnum
from typing import Any, Dict, Optional

import httpx
from fastapi import BackgroundTasks, Header
from pydantic import BaseModel, Field

from web.router import BaseRouter
from agent.currency_insight import create_currency_insight_workflow
from web.context import context


logger = logging.getLogger(__name__)
currency_insight_graph = create_currency_insight_workflow()


# ════════════════════════════════════════════════════════════════════
# /resources 原有模型
# ════════════════════════════════════════════════════════════════════

class SourceType(StrEnum):
    currency_insights = "currency_insights"  # 货币洞察


class MarketType(StrEnum):
    spot = "spot"       # 现货
    future = "future"   # 期货


class BodyModel(BaseModel):
    symbol: str = Field(..., description="货币")
    marketType: MarketType = Field(MarketType.spot, description="市场类型，现货/期货")
    callbackUrl: str = Field(..., description="回调地址")


class ResourcesRequestModel(BaseModel):
    body: BodyModel = Field(..., description="请求体")
    source: SourceType = Field(SourceType.currency_insights, description="业务线类型")
    extra: dict = Field({}, description="额外参数")


# ════════════════════════════════════════════════════════════════════
# /process 通用接口模型
# ════════════════════════════════════════════════════════════════════

class ProcessRequestModel(BaseModel):
    """POST /api/business_line/process 请求体"""
    query: str = Field(..., description="问句")
    extraQuery: Optional[Dict[str, Any]] = Field(None, description="问句相关的额外信息，辅助澄清问句意图")
    skillName: str = Field(..., description="技能名称，枚举值：seo_faq_generator（SEO内容生成）")
    callbackUrl: str = Field(..., description="数据回传 URL")
    extraBody: Optional[Dict[str, Any]] = Field(None, description="其它额外参数，该参数会回传给业务方")


def _process_response(
    code: str = "200",
    msg: str = "success",
    data: Optional[Dict[str, Any]] = None,
    retry: bool = False,
    success: bool = True,
) -> Dict[str, Any]:
    """构造通用响应格式"""
    return {
        "code": code,
        "msg": msg,
        "data": data or {},
        "retry": retry,
        "success": success,
    }


async def _callback(
    callback_url: str,
    query: str,
    extra_body: Optional[Dict],
    result: str,
    status: str,
    reason: str,
) -> None:
    """异步回调业务方接口"""
    payload = {
        "query": query,
        "extraBody": extra_body or {},
        "result": result,
        "status": status,
        "reason": reason,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(callback_url, json=payload)
            logger.info(f"[business_line/process] callback {callback_url} -> {resp.status_code}")
    except Exception as e:
        logger.warning(f"[business_line/process] callback failed: {e}")


async def _run_skill(
    skill_name: str,
    query: str,
    extra_query: Optional[Dict],
    extra_body: Optional[Dict],
    callback_url: str,
    user_id: Optional[str],
) -> None:
    """后台执行技能并回调"""
    try:
        if skill_name == "seo_faq_generator":
            # SEO 内容生成技能（占位，按实际业务扩展）
            result = await _skill_seo_faq_generator(query, extra_query, user_id)
            await _callback(callback_url, query, extra_body, result, "Ok", "")
        else:
            reason = f"Unknown skillName: {skill_name}"
            logger.warning(f"[business_line/process] {reason}")
            await _callback(callback_url, query, extra_body, "", "Failed", reason)
    except Exception as e:
        logger.error(f"[business_line/process] skill={skill_name} error: {e}", exc_info=True)
        await _callback(callback_url, query, extra_body, "", "Failed", str(e))


async def _skill_seo_faq_generator(
    query: str,
    extra_query: Optional[Dict],
    user_id: Optional[str],
) -> str:
    """
    SEO FAQ 内容生成技能（占位实现）。

    TODO: 按实际业务逻辑替换此实现。
    """
    logger.info(f"[seo_faq_generator] query={query!r}, user_id={user_id}")
    # 示例：直接返回 query；实际应调用 LLM 或搜索服务
    return f"FAQ content for: {query}"


# ════════════════════════════════════════════════════════════════════
# 路由注册
# ════════════════════════════════════════════════════════════════════

class BusinessLineApi(BaseRouter):
    def __init__(self):
        super().__init__(prefix="/api/business_line")

        @self._router.post("/resources")
        async def currency_insight(
            request: ResourcesRequestModel,
            background_tasks: BackgroundTasks,
        ):
            background_tasks.add_task(
                currency_insight_graph.ainvoke,
                {
                    "user_id": context.get("user_id"),
                    "symbol": request.body.symbol,
                    "market_type": request.body.marketType,
                    "callback_url": request.body.callbackUrl,
                    "source": request.source.value,
                    "extra": request.extra,
                    "status": "Ok",
                    "reason": ""
                }
            )

        @self._router.post("/process")
        async def process(
            request: ProcessRequestModel,
            background_tasks: BackgroundTasks,
            x_user_id: Optional[str] = Header(None, alias="X-USER-ID"),
        ):
            """
            通用业务线处理接口。

            请求体字段：
              - query:       问句（必填）
              - extraQuery:  问句相关的额外信息
              - skillName:   技能名称，当前支持 seo_faq_generator
              - callbackUrl: 数据回传 URL（必填）
              - extraBody:   额外参数，原样回传给业务方

            处理方式：异步后台执行技能，立即返回受理成功响应；
            技能执行完成后通过 callbackUrl 回传结果。

            回传格式（POST callbackUrl）：
              {
                "query":      "问句",
                "extraBody":  {},
                "result":     "结果字符串或 JSON 字符串",
                "status":     "Ok" | "Failed",
                "reason":     "失败原因"
              }
            """
            user_id = x_user_id or context.get("user_id")

            # 技能名称校验
            supported_skills = {"seo_faq_generator"}
            if request.skillName not in supported_skills:
                return _process_response(
                    code="400",
                    msg=f"Unsupported skillName: {request.skillName}. Supported: {sorted(supported_skills)}",
                    retry=False,
                    success=False,
                )

            # 提交后台任务，立即返回受理成功
            background_tasks.add_task(
                _run_skill,
                request.skillName,
                request.query,
                request.extraQuery,
                request.extraBody,
                request.callbackUrl,
                user_id,
            )

            return _process_response(
                code="200",
                msg="success",
                data={
                    "query": request.query,
                    "extraBody": request.extraBody or {},
                    "result": "",
                    "status": "Ok",
                    "reason": "",
                },
            )
