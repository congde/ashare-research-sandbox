# -*- encoding: utf-8 -*-

'''
@Time        :   2024/07/01 15:13:38
'''

import os
import logging
import copy
import re
from urllib.parse import quote_plus

from motor.motor_asyncio import AsyncIOMotorClient
from dao.client import BaseClient
from libs.wrapper import async_property
from web.config import config

logger = logging.getLogger(__name__)


class MongodbClient(BaseClient):

    def __init__(self) -> None:
        self.client = None

    def _validate_mongo_url(self, url):
        mongo_url_pattern = r'^mongodb(\+srv)?://'
        if not re.match(mongo_url_pattern, url):
            raise ValueError(f"Invalid MongoDB URL format: {url}")

        if '{username}' not in url or '{password}' not in url:
            raise ValueError("MongoDB URL must contain {username} and {password} placeholders")

        return True

    def get_url(
        self,
        url,
        username=None,
        password=None,
        **kwargs
    ):
        self._validate_mongo_url(url)
        if not username or not password:
            raise ValueError("MongoDB username and password are required")

        url = url.format(username=username, password=quote_plus(password))
        if kwargs:
            url += "&" + "&".join(f"{k}={quote_plus(v)}" if isinstance(v, str) else f"{k}={v}" for k, v in kwargs.items() if v is not None)
        logger.info(f"MongoDB connection URL: {url}")
        return url

    async def _connect_with_retry(self, url, max_retries=3, delay=1):
        for attempt in range(max_retries):
            try:
                client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
                await client.admin.command('ping')
                logger.info(f"Successfully connected to MongoDB (attempt {attempt + 1})")
                return client
            except Exception as e:
                logger.warning(f"MongoDB connection attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(delay * (2 ** attempt))  # 指数退避
                else:
                    logger.error(f"Failed to connect to MongoDB after {max_retries} attempts")
                    raise

    @async_property
    async def get_client(self) -> AsyncIOMotorClient:
        if self.client is None:
            args = copy.deepcopy(self.__dict__)
            args.pop('client')
            url = self.get_url(**args)
            self.client = await self._connect_with_retry(url)
        return self.client
