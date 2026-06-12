# -*- coding: utf-8 -*-
'''
@Time    :   2025/11/04 19:27:30
'''
from abc import ABCMeta, abstractmethod

from typing import ParamSpec, TypeVar


from typing import Any, Optional, Tuple


P = ParamSpec("P")
R = TypeVar("R")


class CacheInterface(metaclass=ABCMeta):
    @abstractmethod
    async def get_with_ttl(self, key: str) -> Tuple[int, Optional[bytes]]:
        pass

    @abstractmethod
    async def get(self, key: str) -> Optional[bytes]:
        pass

    @abstractmethod
    async def set(self, key: str, value: Any, expire: Optional[float] = None) -> None:
        pass

    @abstractmethod
    async def delete(self, key: str) -> Optional[int]:
        pass
