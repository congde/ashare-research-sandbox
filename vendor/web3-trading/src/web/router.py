# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/31 22:47:56
'''


import importlib
import inspect
import logging
import os

from fastapi import APIRouter, FastAPI

from web.application import APIRoute
from web.response import JsonResponse
from web.context import context
from web import code_msg
from web.exceptions import HttpException

logger = logging.getLogger(__name__)


class BaseRouter:
    @property
    def router(self):
        return self._router
    
    @property
    def X_USER_ID(self):
        user_id = context.get("X-USER-ID")
        if user_id is None:
            raise HttpException(code=code_msg.CODE_NO_AUTH)
        return user_id
    
    @property
    def user_id(self):
        user_id = context.get("user_id")
        if user_id is None:
            raise HttpException(code=code_msg.CODE_NO_AUTH)
        return user_id

    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        instance._router = APIRouter(tags=[cls.__name__])
        instance._router.prefix = "/api"
        instance._router.default_response_class = JsonResponse
        instance._router.route_class = APIRoute
        return instance

    def __init__(
        self,
        router: APIRouter = None,
        cached: dict = None,
        prefix: str = None
    ) -> None:
        if router is not None:
            self._router = router
        if prefix is not None:
            self._router.prefix = prefix
        self._cached = cached or {}


def auto_import(path: str, app: FastAPI) -> None:
    for file in os.listdir(path):
        file_path = os.path.join(path, file)
        if os.path.isdir(file_path):
            auto_import(file_path, app)
        elif file != '__init__.py' and file.endswith('.py'):
            file_mode = '%s.%s' % (path.replace('\\', '.').replace('/', '.').strip("."), os.path.splitext(file)[0])
            mode_obj = importlib.import_module(file_mode)
            classes = inspect.getmembers(mode_obj, inspect.isclass)
            for name, cls in classes:
                if hasattr(cls, 'router') and name != 'BaseRouter':
                    router = cls().router
                    if isinstance(router, APIRouter):
                        app.include_router(cls().router)
