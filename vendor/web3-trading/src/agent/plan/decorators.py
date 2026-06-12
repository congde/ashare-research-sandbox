# -*- coding: utf-8 -*-
"""
Agent decorators and shared exception types.

Extracted from base.py to avoid circular imports when used by mixins.
"""

import time
import asyncio
import logging
import functools

from agent.schema import (
    StepModel,
    StepType,
    StepStatusType,
    StreamResponse,
    StreamStatusType,
)
from web.context import context
from web.exceptions import RiskException

logger = logging.getLogger(__name__)


class ConnectionTerminatedError(Exception):
    pass


class StopError(Exception):
    pass


async def enable_connect():
    request = context.get("request")
    return not (await request.is_disconnected())


def save_step(stream_type: StepType):
    def decorator(async_gen_func):
        @functools.wraps(async_gen_func)
        async def wrapper(self, *args, **kwargs):
            start_time = time.time()
            step = kwargs.get("step") or StepModel(type=stream_type)
            stream = kwargs.get("stream")
            if stream is None:
                stream = StreamResponse(
                    sessionId=self.session.id,
                    qaId=self.qa.id,
                    status=StreamStatusType.START,
                    type=stream_type
                )

            try:
                async for event in async_gen_func(self, *args, **kwargs):
                    if stream.status == StreamStatusType.START:
                        yield stream.model_dump_json(exclude={"save", "deliver"})
                        stream.status = StreamStatusType.PENDING

                    stream.type = event.type
                    if event.status not in [StreamStatusType.START, StreamStatusType.END]:
                        step.status = StepStatusType.PENDING
                        event.status = StreamStatusType.PENDING
                    else:
                        if event.type == StepType.TOOL_EXECUTION:
                            step.step[StepType.TITLE] = None
                        step.status = event.status
                    event.sessionId = self.session.id
                    event.qaId = self.qa.id
                    if event.save:
                        content = event.content
                        tmp = step.step.get(event.type)
                        if isinstance(content, str):
                            if tmp is None:
                                step.step[event.type] = ""
                            step.step[event.type] += content
                        elif isinstance(content, (list, tuple)):
                            if tmp is None:
                                step.step[event.type] = []
                            step.step[event.type] += list(content)
                        elif isinstance(content, dict):
                            if tmp is None:
                                step.step[event.type] = {}
                            step.step[event.type].update(content)

                    if event.deliver:
                        print(event.content, end="", flush=True)
                        yield event.model_dump_json(exclude={"save", "deliver"})

            except (ConnectionTerminatedError, asyncio.CancelledError) as e:
                msg = f"stream_type={stream_type}, {e}"
                logger.error(msg)
                step.status = StepStatusType.FAILED
                step.log = msg
                raise StopError(step.log)

            except RiskException:
                raise

            except Exception:
                logger.exception("Step execution unkown error")
                step.status = StepStatusType.FAILED
                step.log = f"Error occurred while processing request"
                stream.status = StreamStatusType.FAILED
                stream.log = step.log
                yield stream.model_dump_json(exclude={"save", "deliver"})
                raise StopError(step.log)

            else:
                step.status = StepStatusType.SUCCEEDED
                if stream.status != StreamStatusType.START:
                    stream.status = StreamStatusType.END
                    stream.type = stream_type
                    yield stream.model_dump_json(exclude={"save", "deliver"})

            finally:
                elapsed_ms = int((time.time() - start_time) * 1000)
                if stream.status != StreamStatusType.START:
                    step.elapsedMs = elapsed_ms
                    self.qa.answer.append(step)
                    logger.info(f"Saving step [{step.type}]")
                    await self.qa.save()

                self._step_log(elapsed_ms, async_gen_func.__name__, status=step.status.value)

        return wrapper

    return decorator
