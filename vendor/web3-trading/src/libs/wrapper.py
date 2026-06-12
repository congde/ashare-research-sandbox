# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/18 19:09:56
'''

import asyncio
import time
import logging
import functools
import asyncio
import inspect
from typing import ParamSpec, TypeVar


logger = logging.getLogger(__name__)


class async_property:
    def __init__(self, func):
        self.func = func
        self.name = func.__name__

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.__dict__.get(self.name) or asyncio.ensure_future(self.func(instance))


R = TypeVar('R')
P = ParamSpec('P')


def usage_time(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        func_name = func.__name__
        class_name = args[0].__class__.__name__ if args and hasattr(args[0], "__class__") else None
        full_name = f"{class_name}.{func_name}" if class_name else func_name
        rtn = func(*args, **kwargs)
        
        if inspect.iscoroutinefunction(func):
            async def async_wrapped():
                try:
                    resp = await rtn
                except Exception as e:
                    logger.error(f"Async task failed: {e}")
                    raise e
                finally:
                    interface_cost = int((time.time() - start_time) * 1000)
                    logger.info(f"{full_name}() => usage time: {interface_cost}ms")
                return resp
            return async_wrapped()

        interface_cost = int((time.time() - start_time) * 1000)
        logger.info(f"{full_name}() => usage time: {interface_cost}ms")
        return rtn
    return wrapper


def usage_http_time(func):
    @functools.wraps(func)
    def wrapper(url, *args, **kwargs):
        start_time = time.time()
        func_name = func.__name__
        class_name = args[0].__class__.__name__ if args and hasattr(args[0], "__class__") else None
        full_name = f"{class_name}.{func_name}" if class_name else func_name
        rtn = func(url, *args, **kwargs)
        
        if inspect.iscoroutinefunction(func):
            async def async_wrapped():
                resp = await rtn
                interface_cost = int((time.time() - start_time) * 1000)
                logger.info(f"{full_name}({url}) => usage time: {interface_cost}ms")
                return resp
            return async_wrapped()

        interface_cost = int((time.time() - start_time) * 1000)
        logger.info(f"{full_name}({url}) => usage time: {interface_cost}ms")
        return rtn
    return wrapper


def async_retry(times=2, exc_types=(Exception, ), exclude_types=(asyncio.CancelledError, ), delay=None):
    def wrapper(func):
        @functools.wraps(func)
        async def _exec(*args, **kwargs):
            i = 0
            while True:
                try:
                    return await func(*args, **kwargs)
                except exclude_types:
                    raise
                except exc_types as e:
                    import traceback
                    traceback.print_exc()
                    if i >= times:
                        raise
                    if delay is not None:
                        await asyncio.sleep(delay)
                    i += 1
        return _exec
    return wrapper


if __name__ == "__main__":
    @usage_time
    def test1():
        time.sleep(3)

    @usage_time
    async def test2():
        await asyncio.sleep(2)

    class Test:
        @usage_time
        def test3(self):
            print('3333')
            raise ValueError('xixixi')
            time.sleep(4)

        @async_retry(times=2)
        @usage_time
        async def test4(self):
            print('444444')
            await asyncio.sleep(5)
            raise ValueError('hahahah')

    async def main():
        test1()
        await test2()
        # test = Test()
        # test.test3()
        # await test.test4()


    asyncio.run(main())
