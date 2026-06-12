# -*- coding: utf-8 -*-
import time
import logging
from typing import Any, Dict

from agent.skills.base import BaseSkill
from web.config import config
from web import authenticator as auth

logger = logging.getLogger(__name__)


class WorkFlowCallbackSkill(BaseSkill):
    """
    回调技能
    
    将生成的洞察数据发送到业务方提供的回调 URL。
    """
    name = "callback"
    description = "Send data to callback URL"

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行回调。
        """

        callback_url = state.get("callback_url")
        try:
            data = {
                "query": state.get("query"),
                "extraBody": state.get("extra_body", {}),
                "result": state.get("result"),
                "status": state.get("status"),
                "reason": state.get("reason")
            }
            logger.info(f"Sending data to callback URL: {callback_url}, data: {data}")
            resp = await auth.post(
                app_name=config.dc_kia_qingniao_server.server_name,
                api=callback_url,
                json=data,
                retries=3,
                securekey=config.dc_kia_qingniao_server.securekey,
            )
            cost_time = int((time.time() - state.get("start_time", time.time())) * 1000)
            logger.info(f"Callback to {callback_url} completed in {cost_time}ms, response: {resp}")
        except Exception:
            cost_time = int((time.time() - state.get("start_time", time.time())) * 1000)
            logger.exception(f"Callback to {callback_url} failed after {cost_time}ms")

        return state


class CallbackSkill(BaseSkill):
    """
    回调技能
    
    将生成的洞察数据发送到业务方提供的回调 URL。
    """
    name = "callback"
    description = "Send data to callback URL"

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行回调。
        
        Args:
            state: 当前工作流状态，包含 callback_url 和 insight_data
            
        Returns:
            更新后的状态，包含 status 标识
        """
        if not state.get("callback_url"):
            logger.info("No callback_url provided, skipping callback")
            return state

        try:
            logger.info(f"Sending data to callback URL: {state.get('callback_url')}")
            data = {
                "data": state.get("insight_data", {}),
                "extra": state.get("extra", {}),
                "source": state.get("source", ""),
                "status": state.get("status", "Ok"),
                "reason": state.get("reason", "")
            }
            resp = await auth.post(
                app_name=config.dc_kia_qingniao_server.server_name,
                api=state.get("callback_url", ""),
                json=data,
                retries=3,
                securekey=config.dc_kia_qingniao_server.securekey,
            )
            logger.info(f"Callback response result: {resp}")
        except Exception:
            logger.exception(f"Callback to {state.get('callback_url')} failed")

        return state
