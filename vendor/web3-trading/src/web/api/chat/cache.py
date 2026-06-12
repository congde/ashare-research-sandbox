# -*- coding: utf-8 -*-
'''
@Time    :   2025/11/09 15:41:02
'''


import asyncio
import logging
from enum import StrEnum
from typing import Dict, List, Optional

from dao.redis_bootstrap import get_redis_client
from web.config import config
from agent.schema import get_timestamp, AgentType, QAModel, SessionModel
from web.context import context
from libs.sub_task import SubTaskManager
from .items import ExtraBodyModel


logger = logging.getLogger(__name__)


def _redis():
    return get_redis_client()


class SessionStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"


class SessionMeta(object):

    _cancel_status = SessionStatus.CANCELED.value.encode()
    _pending_status = SessionStatus.PENDING.value.encode()

    def __init__(self, session_id: str, qa_id: str):
        self._session_meta_key = f"session:{session_id}:{qa_id}:meta"
        self._session_id = session_id
        self._qa_id = qa_id
        self.redis = _redis()

    async def create_session(
        self,
        query: str,
        agent_type: AgentType,
        extra_body: ExtraBodyModel,
        ttl: int = 60 * 60
    ) -> bool:
        session_meta = {
            "sessionId": self._session_id,
            "qaId": self._qa_id,
            "createdAt": get_timestamp(),
            "status": SessionStatus.PENDING.value,
            "query": query,
            "agentType": agent_type.value,
            "extraBody": extra_body.model_dump_json(),
            "log": ""
        }
        logger.info(f"create session: key={self._session_meta_key}, value={session_meta}")
        pipeline = self.redis.pipeline()
        pipeline.hset(self._session_meta_key, mapping=session_meta)
        pipeline.expire(self._session_meta_key, ttl)
        await pipeline.execute()
        # items = await redis.hgetall(self._session_meta_key)
        # logger.info(f"session meta: {items}")
        return True

    async def get_session_meta(self) -> Optional[dict]:
        return await self.redis.hgetall(self._session_meta_key)

    async def is_cancelled(self) -> bool:
        status = await self.redis.hget(self._session_meta_key, "status")
        return status == self._cancel_status

    async def get_status(self):
        return await self.redis.hget(self._session_meta_key, "status")

    async def update_session_status(self, status: str, log: str = "", ttl: int = 10 * 60):
        pipeline = self.redis.pipeline()
        pipeline.hset(self._session_meta_key, key="status", value=status)
        if log:
            pipeline.hset(self._session_meta_key, key="log", value=log)
        pipeline.expire(self._session_meta_key, ttl)
        result = await pipeline.execute()
        logger.info(f"sessionId={self._session_id}, qa={self._qa_id} updated to status {status}, result={result}")
        return True


class SessionQueue(object):

    def __init__(self, session_id: str, qa_id: str):
        self._session_tokens_key = f"session:{session_id}:{qa_id}:tokens"
        self.redis = _redis()

    async def append_token(self, token: str, ttl: int = 10 * 60) -> int:
        pipeline = self.redis.pipeline()
        pipeline.rpush(self._session_tokens_key, token)
        pipeline.expire(self._session_tokens_key, ttl)
        result = await pipeline.execute()
        if config.resume_config.redis_list.enable_debug_logger:
            logger.info(f"Append token, list_key={self._session_tokens_key}, result: {result}, list: {token}")

    
    async def get_tokens(self, start: int = 0, end: int = -1) -> List[str]:
        return await self.redis.lrange(self._session_tokens_key, start, end)

    async def get_token_count(self) -> int:
        return await self.redis.llen(self._session_tokens_key)


class SessionChannel(object):
    def __init__(self, session_id: str, qa_id: str):
        self._session_token_key = f"session:{session_id}:{qa_id}:token"
        self._session_cancel_key = f"session:{session_id}:{qa_id}:cancel"
        self._session_complete_key = f"session:{session_id}:{qa_id}:complete"
        self.redis = _redis()

    async def publish_token(self, token: str):
        await self.redis.publish(self._session_token_key, token)

    async def publish_complete(self):
        await self.redis.publish(self._session_complete_key, SessionStatus.COMPLETED.value)

    async def publish_cancel(self):
        await self.redis.publish(self._session_cancel_key, SessionStatus.CANCELED.value)


class RedisCache(object):

    def __init__(self, session_id: str, qa_id: str):
        self.session_meta = SessionMeta(session_id=session_id, qa_id=qa_id)
        self.session_queue = SessionQueue(session_id=session_id, qa_id=qa_id)
        self.session_channel = SessionChannel(session_id=session_id, qa_id=qa_id)
        self.is_canceled = False
        self._cancel_id: str = None
        self.sub_task = SubTaskManager(name=self.__class__.__name__)

    async def cancel(self, qa: QAModel, session: SessionModel):
        logger.info("The conversation is being cancelled.")
        await qa.cancel()
        await session.cancel()
        await self.cancel_listener()

    async def _check_cancel(self):
        while True:
            status = await self.session_meta.get_status()
            if not status:
                break
            if status == self.session_meta._pending_status:
                await asyncio.sleep(0.5)
                # logger.info("111")
                continue
            if status == self.session_meta._cancel_status:
                logger.info(f"Canceled by user, sessionId={self.session_meta._session_id}, qaId={self.session_meta._qa_id}")
                context.set("is_cancelled", True)
                self.is_canceled = True

            break

    async def listen_cancel(self):
        self._cancel_id = await self.sub_task.create_task(asyncio.wait_for(
            self._check_cancel(),
            config.resume_config.redis_session.ttl
        ))

    async def cancel_listener(self):
        if self._cancel_id:
            await self.sub_task.cancel_task(self._cancel_id)
            self._cancel_id = None
