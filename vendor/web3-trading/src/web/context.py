# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/18 16:59:05
'''


from contextvars import ContextVar
from typing import Any

from pydantic import BaseModel, ConfigDict


class AttrDict(BaseModel):
    model_config = ConfigDict(extra="allow")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.__dict__.update(kwargs)

    def __getattr__(self, key):
        return self.__dict__.get(key, None)

    def __setattr__(self, key, value):
        self.__dict__[key] = value

    def __delattr__(self, key):
        if key in self.__dict__:
            del self.__dict__[key]
        else:
            raise AttributeError(f"No such attribute: {key}")

    def __getitem__(self, key):
        return self.__getattr__(key)

    def __setitem__(self, key, value):
        self.__setattr__(key, value)

    def set(self, key, val: Any):
        self.__dict__[key] = val

    def get(self, key, default: Any = None):
        return self.__dict__.get(key, default)

    def remove(self, key):
        if key in self.__dict__:
            self.__delattr__(key)


class Context:

    def __init__(self, name='default_context') -> None:
        self._common_ctx_var: ContextVar[dict] = ContextVar(name)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            data = self._common_ctx_var.get()
        except LookupError:
            return default
        return data.get(key, default)

    def set(self, key: str, val: Any) -> None:
        try:
            data = self._common_ctx_var.get()
        except LookupError:
            data = {}
            self._common_ctx_var.set(data)
        data[key] = val

    def remove(self, key: str) -> None:
        try:
            data = self._common_ctx_var.get()
            if key in data:
                data.pop(key)
        except LookupError:
            pass

    def reset(self) -> None:
        self._common_ctx_var.set({})


context = Context()
