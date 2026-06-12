# -*- coding: utf-8 -*-
"""
kcbot S2S 内部接口 — 供 kcbot 后端调用的 HTTP POST JSON 接口
"""

import logging
import time
from typing import List, Optional

from fastapi import Body

from agent.customer_service import run_cs_workflow
from agent.schema import (
    AgentType,
    QAModel,
    StepModel,
    StepType,
    StepStatusType,
)
from llm.shield.handler import llm_shield
from web.config import config, is_risk_control_enabled
from web.router import BaseRouter

logger = logging.getLogger(__name__)


class CustomerServiceApi(BaseRouter):
    def __init__(self):
        super().__init__(prefix="/api/csagent")

        @self._router.post("/chat")
        async def agent_chat(
            query: str = Body(..., min_length=1, max_length=30000, description="用户输入"),
            userId: str = Body(..., description="用户ID"),
            sessionId: str = Body(..., min_length=32, max_length=32, description="会话ID"),
            agentType: str = Body("CUSTOMER_SERVICE", description="Agent类型"),
            language: str = Body("en_US", description="语言码"),
            uploadedFiles: Optional[List[str]] = Body(None, description="用户上传的图片URL列表"),
        ):
            """
            kcbot S2S 对接接口 — 非流式 JSON 返回

            resultType 枚举:
              ANSWER          — 正常回答 / 澄清反问，展示 answer + relatedIssues
              HUMAN_TRANSFER  — 转人工
              BLOCKED         — 风控拦截，展示 answer（风控提示语）
            """
            logger.info(
                f"[/api/csagent/chat] query={query[:50]}, "
                f"userId={userId}, sessionId={sessionId}, agentType={agentType}"
            )

            # ── 入口风控 — 复用框架 LLMShield（risk_control_enabled=false 时跳过）──
            if is_risk_control_enabled():
                try:
                    if config.risk_enable:
                        risk_result = await llm_shield.check(query, language)
                    else:
                        risk_result = llm_shield._local_sensitive_check(query, language)

                    if risk_result.has_risk and risk_result.should_terminate:
                        logger.warning(f"[入口风控] BLOCKED: {risk_result.risk_category}")
                        return {
                            "resultType": "BLOCKED",
                            "userIssue": query,
                            "answer": risk_result.fallback_message or "该问题无法回答。",
                            "searchSource": [],
                            "relatedIssues": [],
                            "sessionId": sessionId,
                            "qaId": "",
                        }
                except Exception as e:
                    logger.exception(f"[入口风控] 异常，降级放行: {e}")

            # ── 执行客服 Workflow ──
            start_time = time.time()
            result = await run_cs_workflow(
                query=query,
                user_id=userId,
                session_id=sessionId,
                language=language,
                uploaded_files=uploadedFiles or [],
            )

            # ── 持久化 QA（支持多轮历史） ──
            try:
                qa = QAModel(
                    userId=userId,
                    sessionId=sessionId,
                    agentType=AgentType.CUSTOMER_SERVICE,
                    query=query,
                )
                step = StepModel(type=StepType.CUSTOMER_SERVICE_RESPONSE)
                step.step = {StepType.CONTENT: result.get("answer", "")}
                step.status = StepStatusType.SUCCEEDED
                step.elapsedMs = int((time.time() - start_time) * 1000)
                qa.answer.append(step)
                qa.elapsedMs = step.elapsedMs
                await qa.save(check_canceled=False)
                result["qaId"] = qa.id
            except Exception as e:
                logger.warning(f"[QA持久化] 失败，不影响返回: {e}")

            return result
