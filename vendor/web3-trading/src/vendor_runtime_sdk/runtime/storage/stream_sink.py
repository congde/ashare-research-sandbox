# -*- coding: utf-8 -*-
"""
StreamSink Protocol — SSE 事件队列 + 状态 + 通道 的统一注入点。

Sprint 0 PR-A (docs/TUI-Web-Runtime同构化技术方案.md §A2)。

现状 (drift 源头)
-----------------
``ConversationRuntime`` 通过 ``RedisCache`` 直接消费 3 个 Redis 抽象：

* ``cache.session_queue.append_token(event_str)`` ([_resume.py:200])
* ``cache.session_meta.update_session_status(status, log)`` ([_resume.py:202])
* ``cache.session_channel.publish_complete()`` ([_resume.py:201])
* ``cache.session_meta.get_session_meta()`` ([chat.py:315])
* ``cache.session_queue.get_token_count() / get_tokens(start, end)``
  ([chat.py:330,332])

`RedisCache` 只有一个实现 (Redis-backed)，CLI/TUI 想换成本地 in-memory
就要 fork 整个 ``web.api.chat.cache`` 模块。本 Protocol 把这 3 件套抽
象成一个被动接口；SQLite/TUI backend 提供 ``InMemoryStreamSink`` 实
现 (asyncio.Queue + dict 状态)，零 Redis 依赖。

Sprint 0 阶段：Protocol 仅定义，无实现迁移。Sprint 1 PR-E 才把 mixin
的 ``cache.X`` 调用替换为 ``self._storage.stream_sink.X``。

工作签名锚定
-----------
方法签名照搬 [web.api.chat.cache](../../../web/api/chat/cache.py) 现有
``SessionQueue / SessionMeta / SessionChannel`` 的形状，让 Mongo
backend 的 wrapper 实现成本接近 0：

* ``append_token`` 参数名 ``token`` (str) — 与 ``SessionQueue.append_token``
  一致 (line 109)。Mongo backend wrap = 直接转发给 RedisCache 实例。
* ``update_session_status`` 返回值忽略 — Redis 实现返回 ``[modified, ok]``
  tuple；调用方目前从来不读返回值。
* ``publish_complete`` 无返回。
* ``get_session_meta`` 返回 ``Optional[dict]`` — Redis hash 解码后的 dict，
  字段含 ``status`` ``log`` ``createdAt`` 等；In-memory 实现直接返回内部 dict。
* ``get_token_count`` / ``get_tokens`` — SSE consumer 用来拉新 token；
  In-memory 实现 = ``len(queue)`` + ``list(queue)[start:end]``。

所有方法都带 ``session_id`` + ``qa_id`` kwarg 显式 — Redis 实现的
``RedisCache`` 是按 (session, qa) 一对一构造，本 Protocol 接受这两
个 id 作参数后再内部寻址，方便 backend 实现多 session 共享 sink。
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable


@runtime_checkable
class StreamSink(Protocol):
    """SSE 事件落盘 + 状态 + 完成通知的统一接口。

    Mongo backend (``_RedisStreamSink``) wraps ``RedisCache``;
    SQLite/TUI backend (``_InMemoryStreamSink``) holds asyncio.Queue +
    dict in-process. Either way the mixin code doesn't care.
    """

    async def append_token(
        self,
        *,
        session_id: str,
        qa_id: str,
        token: str,
        ttl: int = 600,
    ) -> int:
        """追加一个 SSE event JSON 到 (session, qa) 的 token 队列。

        返回追加后队列的总长（Redis ``RPUSH`` 返回值；In-memory 实现返
        回 ``len(queue)``）。``ttl`` 仅在 Redis 实现有意义（key
        expiration）；In-memory 实现忽略。
        """
        ...

    async def update_session_status(
        self,
        *,
        session_id: str,
        qa_id: str,
        status: str,
        log: str = "",
        ttl: int = 600,
    ) -> None:
        """更新 session 的 meta status — ``PENDING`` / ``COMPLETED`` /
        ``FAILED`` / ``CANCELED``。是 SSE 消费侧 break-out-of-poll 的
        判定字段。
        """
        ...

    async def publish_complete(
        self, *, session_id: str, qa_id: str
    ) -> None:
        """向 (session, qa) 通道发"流结束"信号。

        Redis 实现走 Pub/Sub channel；In-memory 实现 set asyncio.Event。
        """
        ...

    async def get_session_meta(
        self, *, session_id: str, qa_id: str
    ) -> Optional[dict]:
        """读 session meta — 含 ``status`` / ``log`` / ``createdAt`` 等。

        未创建返回 None。SSE consumer 用它做轮询判定。
        """
        ...

    async def get_token_count(
        self, *, session_id: str, qa_id: str
    ) -> int:
        """token 队列当前长度（SSE consumer offset 用）。"""
        ...

    async def get_tokens(
        self,
        *,
        session_id: str,
        qa_id: str,
        start: int = 0,
        end: int = -1,
    ) -> List[bytes]:
        """按 start/end (Redis LRANGE 风格 inclusive) 切片返回 token 字节流。

        Redis 实现直接 ``LRANGE``。In-memory 实现 = ``list(queue)[start:end+1]``
        转 bytes (``token.encode()``)。
        """
        ...
