# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/20 19:20:03
'''

import asyncio
import logging
from typing import List
from collections import defaultdict

from libs import http
from web.config import config


logger = logging.getLogger(__name__)


class BaseMemory(object):

    def __init__(self, user_id: str = None):
        if user_id is None:
            from web.context import context
            user_id = context.get("request")
        self._user_id = user_id
        self._host = config.memory_url
        self._cache = defaultdict(lambda: defaultdict(dict))

    async def add(self, messages: List[dict], sync: bool = False):
        raise NotImplementedError

    async def recall(self, query: str):
        raise NotImplementedError

    async def init_search(self, query: str):
        raise NotImplementedError
