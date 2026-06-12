# -*- coding: utf-8 -*-
'''
@Time    :   2026/03/11 17:29:01
'''
import logging
import importlib
import time

logger = logging.getLogger(__name__)


def get_func(func_path: str):
    callback_list = func_path.split('.')
    package = importlib.import_module(".".join(callback_list[:-1]))
    callback_func = getattr(package, callback_list[-1])
    return callback_func


async def execute_callback(callback, *args, **kwargs):
    """
    执行回调函数

    Args:
        callback: 回调函数路径，格式为 "module.submodule.function"
        *args: 位置参数
        **kwargs: 关键字参数

    Returns:
        None

    Note:
        - 回调失败不会中断主流程，仅记录警告日志
        - 记录回调执行时间用于性能监控，仅当执行时间超过100ms或调试模式开启时记录
    """
    try:
        # 使用perf_counter获取更高精度的时间
        start_time = time.perf_counter()
        callback_func = get_func(callback)

        await callback_func(*args, **kwargs)
        cost_time = int((time.perf_counter() - start_time) * 1000)
        logger.info("Callback %s completed in %dms", callback, cost_time)

    except Exception as e:
        logger.warning("[%s] Callback execution failed with error: %s", callback, str(e))