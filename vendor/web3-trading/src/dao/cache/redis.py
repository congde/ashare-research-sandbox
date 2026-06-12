# -*- coding: utf-8 -*-
'''
@Time    :   2025/11/04 19:27:30
'''
import logging
from contextlib import asynccontextmanager
from functools import wraps
from typing import ParamSpec, TypeVar, List

from redis.asyncio.client import AbstractRedis
from redis.asyncio.cluster import AbstractRedisCluster
from typing import Any, Awaitable, Callable, Union, Optional, Tuple
from redis import asyncio as aioredis
from redis.asyncio.lock import Lock
from redis.asyncio.cluster import ClusterNode, ClusterPipeline as _ClusterPipeline, RedisClusterException
from redis.commands.core import PubSubCommands
from redis.retry import Retry
from redis.backoff import default_backoff

from dao.client import BaseClient
from web.component import component
from dao.cache import CacheInterface


logger = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")


class ClusterPipeline(_ClusterPipeline, PubSubCommands):
    pass


class RedisCluster(aioredis.RedisCluster, PubSubCommands):

    def pipeline(
        self, transaction: Optional[Any] = None, shard_hint: Optional[Any] = None
    ) -> "ClusterPipeline":
        if shard_hint:
            raise RedisClusterException("shard_hint is deprecated in cluster mode")

        return ClusterPipeline(self, transaction)
    

class RedisClient(BaseClient):
    @property
    def client(self) -> Union[AbstractRedis, AbstractRedisCluster]:
        return self.redis

    def __init__(
        self,
        nodes: List[dict],
        read_model="SLAVE",
        cluster_mode=None,
        max_connections=64,
        username=None,
        password=None,
        socket_connect_timeout=5,
        socket_timeout=5,
        health_check_interval=30,
        load_balancing_strategy="round_robin"
    ) -> None:
        try:
            # cluster_mode=True 强制用 RedisCluster（单节点也适用）；None 时按 nodes 数量决定
            use_cluster = cluster_mode if cluster_mode is not None else len(nodes) > 1
            if len(nodes) == 1 and not use_cluster:
                node = nodes[0]
                self.redis = aioredis.Redis(
                    host=node.get('host', 'localhost'),
                    port=node.get('port', 6379),
                    username=username,
                    password=password,
                    max_connections=max_connections,
                    socket_connect_timeout=socket_connect_timeout,
                    socket_timeout=socket_timeout,
                    health_check_interval=health_check_interval,
                )
                logger.info(f"Redis standalone initialized successfully: {node.get('host')}:{node.get('port')}")
            else:
                self.redis = RedisCluster(
                    startup_nodes=[ClusterNode(**node) for node in nodes],
                    username=username,
                    password=password,
                    retry=Retry(backoff=default_backoff(), retries=5),
                    read_from_replicas=bool(read_model == "SLAVE"),
                    max_connections=max_connections,
                    socket_connect_timeout=socket_connect_timeout,
                    socket_timeout=socket_timeout,
                    health_check_interval=health_check_interval,
                    load_balancing_strategy=self._map_load_balancing_strategy(load_balancing_strategy)
                )
                logger.info(f"Redis cluster initialized successfully, {self.redis}")
        except Exception as e:
            logger.error(f"Failed to initialize Redis cluster: {e}")
            raise e

    def _map_load_balancing_strategy(self, strategy: str):
        from redis.cluster import LoadBalancingStrategy
        strategy_map = {
            "round_robin": LoadBalancingStrategy.ROUND_ROBIN,
            "round_robin_replicas": LoadBalancingStrategy.ROUND_ROBIN_REPLICAS,
            "random_replica": LoadBalancingStrategy.RANDOM_REPLICA,
        }
        return strategy_map.get(strategy, LoadBalancingStrategy.ROUND_ROBIN) 
    
    async def close(self):
        await self.redis.aclose()


class RedisCache(CacheInterface):
    def __init__(self, redis: Union[AbstractRedis, AbstractRedisCluster], prefix: str = 'cache') -> None:
        self.redis = redis
        self.prefix = prefix
        self.is_cluster = isinstance(redis, AbstractRedisCluster)

    async def get_with_ttl(self, key: str) -> Tuple[int, Optional[bytes]]:
        key = f"{self.prefix}:{key}"
        async with self.redis.pipeline(transaction=not self.is_cluster) as pipe:
            return await pipe.ttl(key).get(key).execute()

    async def get(self, key: str) -> Optional[bytes]:
        return await self.redis.get(f"{self.prefix}:{key}")

    async def set(self, key: str, value: Any, expire: Optional[float] = None) -> None:
        await self.redis.set(f"{self.prefix}:{key}", value, ex=expire or None)

    async def delete(self, key: str) -> Optional[int]:
        return await self.redis.delete(f"{self.prefix}:{key}")


def redis_lock(key: Any, name: str = 'redis', timeout: float = 10) -> Callable[P, Awaitable[R]]:
    def wrapper(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper_function(*args: P.args, **kwargs: P.kwargs) -> R:
            async with Lock(component.get(name).client, key, timeout=timeout):
                logger.info('redis_lock: %s' % key)
                return await func(*args, **kwargs)

        return wrapper_function

    return wrapper


@asynccontextmanager
async def with_redis_lock(key: Any, name: str = 'redis', timeout: float = 10) -> Lock:
    lock = Lock(component.get(name).client, key, timeout=timeout)
    await lock.acquire()
    try:
        yield lock
    finally:
        await lock.release()
