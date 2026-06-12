# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/20 19:20:03
'''
import os
import time
import asyncio
import logging
from typing import List
from datetime import datetime, timezone, timedelta

from libs import http
from web.config import config
from memory.base import BaseMemory
from libs.eureka import eureka
from web.authenticator import get_headers, delete, post, get
from web.context import context
from libs.wrapper import usage_time
from agent.schema import UserConfigModel


logger = logging.getLogger(__name__)


def _memory_enabled() -> bool:
    if os.environ.get("MEMORY_ENABLED", "").strip().lower() in ("0", "false", "no", "off"):
        return False
    if os.environ.get("serverEnv", "") == "local" and not (os.environ.get("MEMORY_URL") or "").strip():
        return False
    return True


class Mem0Memory(BaseMemory):

    _add_api = "/memories"
    _search_api = "/search"
    _get_all_api = "/memories"
    _delete_api = "/memories"
    _delete_all_api = "/memories/delete_all"

    ADD_FUNC_NAME = "Mem0Memory:add"

    def get_headers(self, url, method="POST", app_name=config.memory_server, **kwargs):
        kwargs["name"] = os.getenv("SERVER_NAME").upper()
        sk = config.memory_securekey or os.environ.get("SECUREKEY")
        return get_headers(
            app_name=app_name,
            method=method,
            url=url,
            headers=context.get('headers', {}),
            sk=sk,
            **kwargs
        )

    async def _add(self, messages: List[dict]) -> None:
        if not _memory_enabled():
            logger.debug("Mem0 add skipped (local/disabled)")
            return []
        """
        上一个answer和本次的query，首个session时assistant的内容为空
        [
            {"role": "user": "context": "xxx"},
            {"role": "assistant": "context": "xxx"}
        ]
        """
        request_data = {
            "messages": messages,
            "user_id": self._user_id
        }
        
        try:
            if os.environ.get('serverEnv', '') == 'local':
                memory_url = os.environ.get('MEMORY_URL').strip('/')
            else:
                memory_url = eureka.get_service_url(app_name=config.memory_server).strip('/')
            
            url = f"{memory_url}{self._add_api}"
            headers = self.get_headers(url, app_name=os.environ.get('MEMORY_SERVER', 'ai-memo'))
            resp = await http.post(
                url,
                json=request_data,
                timeout=30,
                headers=headers
            )
            logger.info(f"Add memory, reponse={resp}")
            return resp.get("results", [])
        except Exception as e:
            logger.warning(f'Add query error, {e}')

    async def add(self, messages: List[dict], sync: bool = False):
        if sync:
            return await self._add(messages)
        task = asyncio.create_task(self._add(messages))
        await asyncio.sleep(0)
        return task

    async def init_search(self, query):
        if not _memory_enabled():
            noop = asyncio.create_task(asyncio.sleep(0))
            self._cache["search"][query]["task"] = noop
            self._cache["search"][query]["result"] = []
            return
        _task = asyncio.create_task(self._search(query))
        self._cache["search"][query]["task"] = _task
        await asyncio.sleep(0)

    async def recall(self, query: str) -> list:
        task = self._cache.get("search", {}).get(query, {}).get("task")
        if task:
            await task
            return self._cache.get("search", {}).get(query, {}).get("result", [])
        return await self._search(query)

    async def _search(self, query: str) -> list:
        if not _memory_enabled():
            return []
        user_config = await UserConfigModel.get_user_config(self._user_id)
        valid_days = int(user_config.get("memory_storage_time", 30))
        request_data = {
            "query": query,
            "user_id": self._user_id,
            "filters": {
                "size_limit": 10, # 返回的记忆条数上限
                "similarity_threshold": 0.6, # 相似度阈值
                "time_filter": {
                    "start_time": (datetime.now(timezone.utc) - timedelta(days=valid_days)).isoformat(),
                },
            }
        }
        logger.info(f"Memory search query, request_data={request_data}")
        
        try:
            if os.environ.get('serverEnv', '') == 'local':
                memory_url = os.environ.get('MEMORY_URL').strip('/')
            else:
                memory_url = eureka.get_service_url(app_name=config.memory_server).strip('/')
            
            url = f"{memory_url}{self._search_api}"
            headers = self.get_headers(url, app_name=os.environ.get('MEMORY_SERVER', 'ai-memo'))
            resp = await http.post(
                url,
                json=request_data,
                headers=headers
            )
            logger.info(f"Recall mem0 result: {resp}")
        except Exception as e:
            logger.warning(f'Search query error, {e}')
            return []
        
        result = resp.get("results", [])
        self._cache["search"][query]["result"] = result
        return result

    @usage_time
    async def get_recent_memories(self, limit=30):
        """
        获取用户最近的limit条记忆，并根据用户配置的valid_days进行时间过滤。
        """
        try:
            if os.environ.get('serverEnv', '') == 'local':
                memory_url = os.environ.get('MEMORY_URL').strip('/')
            else:
                memory_url = eureka.get_service_url(app_name=config.memory_server).strip('/')
            params = {
                "user_id": self._user_id,
                "limit": limit
            }
            url = f"{memory_url}{self._get_all_api}"
            headers = self.get_headers(
                url,
                method="GET",
                app_name=os.environ.get('MEMORY_SERVER', 'ai-memo'),
                params=params
            )
            logger.info(f"Get recent memories request, url={url}, params={params}")
            resp = await http.get(
                url,
                params=params,
                headers=headers
            )
            logger.info(f"Get recent memories result: {resp}")
        except Exception as e:
            logger.warning(f'Get recent memories error, {e}')
            return []

        memories = resp.get("results", [])
        
        # 再次用valid_days做时间过滤
        db_start_time = time.time()
        # TODO: 再次用valid_days做时间过滤
        user_config = await UserConfigModel.get_user_config(self._user_id)
        valid_days = int(user_config.get("memory_storage_time", 30))
        logger.info(f"Get user config time: {int((time.time() - db_start_time) * 1000)}ms")

        # 计算有效时间范围
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=valid_days)
        
        # 过滤记忆，优先使用updated_at，如果为空则使用created_at
        filtered_memories = []
        for memory in memories:
            # 优先使用updated_at，如果为空则使用created_at
            time_str = memory.get('updated_at') or memory.get('created_at')
            if time_str:
                try:
                    # 解析时间字符串
                    memory_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    # 检查是否在有效时间范围内
                    if memory_time >= cutoff_time:
                        filtered_memories.append(memory)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse time for memory {memory.get('id', 'unknown')}: {e}")
                    # 如果时间解析失败，为了安全起见，保留该记忆
                    filtered_memories.append(memory)
            else:
                # 如果两个时间字段都为空，为了安全起见，保留该记忆
                logger.warning(f"Memory {memory.get('id', 'unknown')} has no time information")
                filtered_memories.append(memory)

        return filtered_memories

    
    async def delete_memory(self, memory_id: str):
        """
        删除一条记忆
        """
        try:
            resp = await post(
                app_name=os.environ.get('MEMORY_SERVER', 'ai-memo'),
                api=self._delete_api + f"/{memory_id}",
                params={"memory_id": memory_id}
            )
            logger.info(f"Delete memory result: {resp}")
        except Exception as e:
            logger.warning(f'Delete memory error, {e}')


    async def delete_all_memories(self):
        """
        删除所有相关的memory
        """
        try:
            resp = await post(
                app_name=os.environ.get('MEMORY_SERVER', 'ai-memo'),
                api=self._delete_all_api
            )
            logger.info(f"Delete all memories result: {resp}")
            return resp
        except Exception as e:
            logger.warning(f'Delete all memories error, {e}')