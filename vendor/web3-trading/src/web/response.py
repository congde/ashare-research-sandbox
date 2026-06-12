import anyio
import logging
import time
import json
import asyncio
from typing import Optional, Mapping

import psutil
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask
from sse_starlette.sse import EventSourceResponse as _EventSourceResponse, SendTimeoutError, ContentStream
from starlette.background import BackgroundTask
from starlette.types import Send
from sse_starlette.event import ensure_bytes

from web import code_msg


logger = logging.getLogger(__name__)


class EventSourceResponse(_EventSourceResponse):
    def __init__(
        self, 
        content: ContentStream,
        status_code: int = 200,
        headers: Optional[Mapping[str, str]] = None,
        media_type = "text/event-stream",
        **kwargs
    ):
        if headers is None:
            headers = {
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            }
        super().__init__(
            content=content,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            **kwargs
        )
        
    async def _stream_response(self, send: Send) -> None:
        """Send out SSE data to the client as it becomes available in the iterator."""
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )

        try:
            async for data in self.body_iterator:
                chunk = ensure_bytes(data, self.sep)
                with anyio.move_on_after(self.send_timeout) as cancel_scope:
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})

                if cancel_scope and cancel_scope.cancel_called:
                    if hasattr(self.body_iterator, "aclose"):
                        await self.body_iterator.aclose()
                    raise SendTimeoutError()

        except asyncio.exceptions.CancelledError:
            logger.error('Network issue or client actively disconnected')

        except Exception as e:
            logger.exception("SSE Response Error")
            error_chunk = {
                "sessionId": None,
                "qaId": None,
                "type": "SYSTEM",
                "content": None,
                "status": "FAILED",
                "log": str(e)
            }
            completed_chunk = {
                "sessionId": None,
                "qaId": None,
                "type": "SYSTEM",
                "content": None,
                "status": "COMPLETED",
                "log": ""
            }
            try:
                await send({"type": "http.response.body", "body": json.dumps(error_chunk), "more_body": True})
                await send({"type": "http.response.body", "body": json.dumps(completed_chunk), "more_body": True})
            except:
                pass

        finally:
            try:
                async with self._send_lock:
                    self.active = False
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
            except asyncio.exceptions.CancelledError:
                logger.error('Network issue or client actively disconnected')

            from web.middlewares import context
            request = context.get("request_info", {})
            log_msg = {
                "method": request.get("method"),
                "api": request.get("api"),
                "memory_percent": psutil.virtual_memory().percent,
            }
            request_timestamp = context.get("request_timestamp")
            if request_timestamp:
                log_msg["interface_cost"] = f"{int((time.time() - float(request_timestamp)) * 1000)}ms"
            logger.info(f"AfterRequest =====> {log_msg}")


class JsonResponse(JSONResponse):

    def __init__(
        self,
        content=None,
        code=code_msg.CODE_SUCCESS,
        msg: str = None,
        headers=None,
        status_code: int = 200,
        media_type="application/json; charset=utf-8",
        background: BackgroundTask | None = None,
    ):
        if not msg:
            msg = code_msg.get_msg(code)
        content = {
            "code": str(code),
            "msg": msg,
            "data": content,
            "retry": False,
            "success": bool(code >= 200 and code < 400)
        }
        super(JSONResponse, self).__init__(content, status_code, headers, media_type, background)
