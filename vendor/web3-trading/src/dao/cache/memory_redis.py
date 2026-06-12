# -*- coding: utf-8 -*-
"""In-process async Redis substitute for local development."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Union


def _to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if value is None:
        return b""
    return str(value).encode()


class _MemoryPipeline:
    def __init__(self, client: "InMemoryRedis") -> None:
        self._client = client
        self._ops: list[tuple] = []

    def hset(
        self,
        redis_key: str,
        *args: Any,
        mapping: Optional[Dict[str, Any]] = None,
        key: Optional[str] = None,
        value: Any = None,
    ) -> "_MemoryPipeline":
        self._ops.append(("hset", redis_key, args, mapping, key, value))
        return self

    def expire(self, key: str, ttl: int) -> "_MemoryPipeline":
        self._ops.append(("expire", key, ttl))
        return self

    def rpush(self, key: str, value: Any) -> "_MemoryPipeline":
        self._ops.append(("rpush", key, value))
        return self

    async def execute(self) -> list:
        results = []
        for op in self._ops:
            name = op[0]
            if name == "hset":
                _, redis_key, args, mapping, field, val = op
                results.append(
                    await self._client.hset(
                        redis_key, *args, mapping=mapping, key=field, value=val
                    )
                )
            elif name == "expire":
                _, redis_key, ttl = op
                results.append(await self._client.expire(redis_key, ttl))
            elif name == "rpush":
                _, redis_key, val = op
                results.append(await self._client.rpush(redis_key, val))
        return results


class InMemoryRedis:
    """Minimal Redis API used by chat cache, fast_filter, and MCP client."""

    def __init__(self) -> None:
        self._strings: Dict[str, bytes] = {}
        self._hashes: Dict[str, Dict[str, bytes]] = {}
        self._lists: Dict[str, List[bytes]] = {}
        self._expiry: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    def pipeline(self, transaction: bool = True) -> _MemoryPipeline:
        return _MemoryPipeline(self)

    async def _purge_expired(self, key: str) -> None:
        expires_at = self._expiry.get(key)
        if expires_at is not None and expires_at <= time.monotonic():
            self._strings.pop(key, None)
            self._hashes.pop(key, None)
            self._lists.pop(key, None)
            self._expiry.pop(key, None)

    async def set(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        nx: bool = False,
    ) -> Optional[bool]:
        async with self._lock:
            await self._purge_expired(key)
            if nx and key in self._strings:
                return None
            self._strings[key] = _to_bytes(value)
            if ex:
                self._expiry[key] = time.monotonic() + ex
            elif key in self._expiry and not ex:
                self._expiry.pop(key, None)
            return True

    async def get(self, key: str) -> Optional[bytes]:
        async with self._lock:
            await self._purge_expired(key)
            return self._strings.get(key)

    async def incr(self, key: str) -> int:
        async with self._lock:
            await self._purge_expired(key)
            current = int(self._strings.get(key, b"0") or b"0")
            current += 1
            self._strings[key] = str(current).encode()
            return current

    async def expire(self, key: str, ttl: int) -> bool:
        async with self._lock:
            if key not in self._strings and key not in self._hashes and key not in self._lists:
                return False
            self._expiry[key] = time.monotonic() + ttl
            return True

    async def hset(
        self,
        redis_key: str,
        *args: Any,
        mapping: Optional[Dict[str, Any]] = None,
        key: Optional[str] = None,
        value: Any = None,
    ) -> int:
        async with self._lock:
            await self._purge_expired(redis_key)
            bucket = self._hashes.setdefault(redis_key, {})
            if mapping:
                for field, val in mapping.items():
                    bucket[str(field)] = _to_bytes(val)
                return len(mapping)
            if len(args) == 2 and key is None and value is None:
                field, val = args
                bucket[str(field)] = _to_bytes(val)
                return 1
            if len(args) == 1 and isinstance(args[0], dict):
                for field, val in args[0].items():
                    bucket[str(field)] = _to_bytes(val)
                return len(args[0])
            if key is not None:
                bucket[str(key)] = _to_bytes(value)
                return 1
            return 0

    async def hget(self, key: str, field: str) -> Optional[bytes]:
        async with self._lock:
            await self._purge_expired(key)
            return self._hashes.get(key, {}).get(str(field))

    async def hgetall(self, key: str) -> Dict[bytes, bytes]:
        async with self._lock:
            await self._purge_expired(key)
            bucket = self._hashes.get(key, {})
            return {k.encode(): v for k, v in bucket.items()}

    async def rpush(self, key: str, value: Any) -> int:
        async with self._lock:
            await self._purge_expired(key)
            bucket = self._lists.setdefault(key, [])
            bucket.append(_to_bytes(value))
            return len(bucket)

    async def lrange(self, key: str, start: int, end: int) -> List[bytes]:
        async with self._lock:
            await self._purge_expired(key)
            bucket = self._lists.get(key, [])
            if end == -1:
                end = len(bucket) - 1
            return bucket[start : end + 1]

    async def llen(self, key: str) -> int:
        async with self._lock:
            await self._purge_expired(key)
            return len(self._lists.get(key, []))

    async def publish(self, channel: str, message: Union[str, bytes]) -> int:
        return 0

    async def aclose(self) -> None:
        return None
