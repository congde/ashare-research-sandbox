# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/18 19:12:25
'''


from typing import Any

from libs.wrapper import async_property


class BaseClient(object):
    def __getattr__(self, key: str):
        if key in self.__dict__:
            return self.__dict__[key]

    def __setattr__(self, key: str, value: Any):
        self.__dict__[key] = value

    @async_property
    async def get_client(self, *args, **kwargs):
        raise NotImplementedError

    async def close(self):
        raise NotImplementedError

    def get_url(self, params):
        pass
