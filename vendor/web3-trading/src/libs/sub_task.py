# -*- coding: utf-8 -*-
'''
@Time    :   2025/11/11 15:58:24
'''

import asyncio
import logging
from uuid import uuid4
from collections import OrderedDict
from typing import List, Optional, Callable, Any, Coroutine
from contextlib import asynccontextmanager


logger = logging.getLogger(__name__)


class SubTaskManager(object):
    def __init__(self, name: str = "SubTaskManager"):
        self.name = name
        self._tasks: OrderedDict[str, asyncio.Task] = OrderedDict()
        self._shutting_down = False
        self._lock = asyncio.Lock()

    async def create_task(
        self,
        coro: Coroutine,
        task_name: str = None,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None
    ) -> asyncio.Task:
        if self._shutting_down:
            raise RuntimeError(f"{self.name} is shutting down, cannot create new tasks")

        async with self._lock:
            if task_name in self._tasks:
                raise RuntimeError(f"Task '{task_name}' already exists")

            if task_name is None:
                task_name = uuid4().hex

            task = asyncio.create_task(self._wrap_task(coro, task_name, on_complete, on_error))
            self._tasks[task_name] = task

            logger.info(f"Created task '{task_name}' in {self.name}")
            return task_name

    async def _wrap_task(
        self,
        coro: Coroutine,
        task_name: str,
        on_complete: Optional[Callable],
        on_error: Optional[Callable]
    ) -> Any:
        try:
            result = await coro

            # Call completion callback
            if on_complete:
                try:
                    if asyncio.iscoroutinefunction(on_complete):
                        await on_complete(result)
                    else:
                        on_complete(result)
                except Exception as e:
                    logger.error(f"Error in on_complete callback for task '{task_name}': {e}")

            return result

        except asyncio.CancelledError:
            logger.debug(f"Task '{task_name}' was cancelled")
            # Don't call error callback for cancellation
            raise

        except Exception as e:
            logger.error(f"Task '{task_name}' failed: {e}", exc_info=True)

            # Call error callback
            if on_error:
                try:
                    if asyncio.iscoroutinefunction(on_error):
                        await on_error(e)
                    else:
                        on_error(e)
                except Exception as callback_error:
                    logger.error(f"Error in on_error callback for task '{task_name}': {callback_error}")

            raise

        # finally:
        #     # Remove task from tracking
        #     async with self._lock:
        #         if task_name in self._tasks:
        #             del self._tasks[task_name]
        #             logger.info(f"Cleaned up task '{task_name}' from {self.name}")

    def get_task(self, task_name: str) -> Optional[asyncio.Task]:
        return self._tasks.get(task_name)

    def list_tasks(self) -> List[str]:
        return list(self._tasks.keys())

    def has_task(self, task_name: str) -> bool:
        return task_name in self._tasks

    async def cancel_task(self, task_name: str, timeout: float = 5.0) -> bool:
        task = self.get_task(task_name)
        if not task:
            logger.warning(f"Task '{task_name}' not found for cancellation")
            return False

        if task.done():
            logger.debug(f"Task '{task_name}' is already done")
            return True

        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
            logger.info(f"Successfully cancelled task '{task_name}'")
            return True
        except asyncio.CancelledError:
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Task '{task_name}' did not cancel within {timeout}s timeout")
            return False

    async def shutdown(self, timeout: float = 10.0) -> None:
        if self._shutting_down:
            return

        self._shutting_down = True
        logger.info(f"Shutting down {self.name} with {len(self._tasks)} tasks")

        if not self._tasks:
            return

        # Cancel all tasks
        tasks_to_cancel = list(self._tasks.values())
        for task in tasks_to_cancel:
            task.cancel()

        # Wait for tasks to complete with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks_to_cancel, return_exceptions=True),
                timeout=timeout
            )
            logger.info(f"All tasks in {self.name} completed successfully")
        except asyncio.TimeoutError:
            logger.warning(f"Some tasks in {self.name} did not complete within {timeout}s timeout")

        # Clear remaining tasks
        self._tasks.clear()

    @asynccontextmanager
    async def task_context(
        self,
        coro: Coroutine,
        task_name: str,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None
    ):
        """
        Context manager for creating and automatically cleaning up tasks.

        Usage:
            async with manager.task_context(coro, "my_task") as task:
                # Task is running
                await some_other_operation()
        """
        task = await self.create_task(coro, task_name, on_complete, on_error)
        try:
            yield task
        finally:
            # If task is still running, cancel it
            if self.has_task(task_name) and not task.done():
                await self.cancel_task(task_name)

    def __len__(self) -> int:
        return len(self._tasks)

    def __contains__(self, task_name: str) -> bool:
        return task_name in self._tasks

    def __repr__(self) -> str:
        return f"SubTaskManager(name='{self.name}', tasks={len(self._tasks)})"


sub_task = SubTaskManager()


if __name__ == "__main__":
    async def main():
        task_name = await sub_task.create_task(asyncio.sleep(10))
        await sub_task.cancel_task(task_name)
        print(task_name)

    asyncio.run(main())
