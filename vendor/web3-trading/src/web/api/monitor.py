# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/20 09:56:18
'''

import logging

from fastapi import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from web.config import config
from web.router import BaseRouter
from libs.eureka import eureka


logger = logging.getLogger(__name__)


class MonitorApi(BaseRouter):
    def __init__(self):
        super().__init__(prefix="/actuator")

        @self._router.get("/prometheus")
        async def prometheus():
            return Response(
                content=generate_latest(),
                media_type=CONTENT_TYPE_LATEST
            )

        @self._router.get("/health")
        async def health():
            logger.info(f'{config.server_name} is healthy...')

        @self._router.post("/up")
        async def up():
            await eureka.up()

        @self._router.post("/down")
        async def down():
            await eureka.down()
