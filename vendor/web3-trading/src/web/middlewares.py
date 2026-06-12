# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/20 11:54:12
'''


import os
import time
import uuid
import logging
import traceback

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from web import code_msg
from web.response import JsonResponse
from web.exceptions import HttpException
from web.config import config
from web.context import context
from libs.prometheus import metric_cls_dict
from web.authenticator import check_auth
from web.application import record_response_info, record_request_info
from agent.schema import SourceType


logger = logging.getLogger(__name__)


class RequestMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        context.reset()
        context.set('message_uuid', request.headers.get("message-uuid", uuid.uuid4().hex))
        context.set('request_timestamp', time.time())
        real_ip = request.headers.get("X-Forwarded-For") or request.client.host
        context.set("remote_addr", real_ip)
        user_id = request.headers.get("X-USER-ID")
        content_type = request.headers.get("content-type", "")
        may_have_json_body = request.method in ("POST", "PUT", "PATCH") and "application/json" in content_type.lower()
        if not user_id and may_have_json_body:
            try:
                body = await request.json()
                source = body.get("source")
                valid_sources = [e.value for e in SourceType]
                if source and source in valid_sources:
                    # 模拟 user_id 注入，只用于KC域获取不到用户UserID的情况（暂时）
                    user_id = uuid.uuid4().hex
                    byte_user_id = user_id.encode()
                    request.scope["headers"].append((b"x-user-id", byte_user_id))
                    request.scope["headers"].append((b"X-USER-ID", byte_user_id))
            except Exception:
                pass
        
        context.set("user_id", user_id)
        context.set("request", request)
        context.set("request_info", {"method": request.method, "api": request.url.path})
        context.set("headers", dict(request.headers))
        return await call_next(request)


class CustomMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = None
        code = 200

        await record_request_info(request)
        try:
            await check_auth(request, app_name=os.environ.get("SERVER_NAME", 'ai-web3-tradding-agent'))
            response = await call_next(request)
        except HttpException as e: 
            code = e.code
            msg = e.msg
            if int(code) == 403:
                logger.critical(f"Not Auth Error, code=403, msg={e}\n{traceback.format_exc()}")
            else:
                logger.warning(f"code={code}, msg={msg + ', ' + str(e.extra) if e.extra else msg}")
            
            if e.extra is not None and e.raise_user:
                msg = f"{msg}, {e.extra}"
            
            response = JsonResponse(code=code, msg=msg)
        
        except Exception as e:
            code = code_msg.CODE_SERVER_ERROR
            response = JsonResponse(code=code)
            logger.critical(f"Unkown Error, code={code}, msg={e}\n{traceback.format_exc()}")
        
        finally:
            await self._prometheus_metric(request, code=code)
            await record_response_info(request, response)
        
        return response

    async def _prometheus_metric(self, request, code=200, *args, **kwargs):
        try:
            endpoint = request.url
            method = request.method
            start_time = context.get("request_timestamp", time.time())
            for _, metric_cls in metric_cls_dict.items():
                metric_obj = metric_cls(server_name=config.server_name.upper())
                metric_obj.get_label(method=method, endpoint=endpoint, start_time=start_time, status=code)
        except Exception as e:
            logger.exception(f"Metric processing failed, {e}")
