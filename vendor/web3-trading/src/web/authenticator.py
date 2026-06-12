# -*- coding: utf-8 -*-
'''
@Time    :   2025/09/16 10:40:00
'''

import os
import logging
import traceback
import uuid

from starlette.requests import Request
from dc_api_security.server import ServiceAuthorize
from dc_api_security.client import SecureAccessClient

from libs.eureka import eureka
from libs import http
from web import code_msg
from web.exceptions import AuthException

logger = logging.getLogger(__name__)


def get_client(app_name: str = None, sk: str = None, ak: str = None, name='py-service'):
    if sk is None:
        sk = os.environ.get("SECUREKEY")
    if ak is None:
        ak='_GLOBAL_'
    return SecureAccessClient(
        name=name,
        app_name=app_name,
        eureka_client=eureka._client,
        ak=ak,
        sk=sk
    )


async def check_auth(request: Request, app_name: str, sk: str = None):
    # 监控
    if request.url.path.startswith('/actuator') or request.url.hostname in ('localhost', '127.0.0.1'):
        return
    # 白名单
    white_list = os.environ.get("WHITE_LIST")
    if white_list:
        if request.headers.get("x-user-id", "") in white_list.strip().split(","):
            return
    # API鉴权
    if sk is None:
        sk = os.environ.get("SECUREKEY")
    try:
        authorize = ServiceAuthorize(service_id=app_name, sk=sk)
        await authorize._validate_permission(request, sk=sk)
    except Exception as e:
        if not str(os.environ.get("ENABLE_AUTH", "False")).lower() == 'true':  # 观察者模式：即使不开启API鉴权也要放行，且记录鉴权失败日志
            logger.critical(f"Not Auth Error, code=403, msg={e}\n{traceback.format_exc()}")
            return
        code=code_msg.CODE_NO_AUTH
        logger.critical(f"Not Auth Error, code={code}, msg={e}\n{traceback.format_exc()}")
        raise AuthException(code=code, extra=str(e))

def split_securekey(securekey: str):
    if not securekey:
        return "_GLOBAL_", ""
    parts = securekey.split("|", 1)
    if len(parts) == 2:
        ak, sk = parts
    else:
        ak = "_GLOBAL_"
        sk = parts[0]
    return ak, sk


def get_headers(
    app_name: str,
    method,
    url,
    params=None,
    headers=None,
    ak: str = None,
    sk: str = None,
    name="py-service",
    **kwargs
):
    """
    Prepare headers for the request.
    :param app_name: Application name
    :param method: HTTP method
    :param url: Request URL
    :param params: Request parameters
    :param headers: Existing headers
    :param ak: Access Key，作为客户端调用方需要设置ak值，一般为客户端应用名称大写
    :param sk: Secret Key，作为服务端被调用方需要设置sk值，一般为一串随机字符串
    :param name: Client name，客户端应用名称
    :return: Prepared headers dictionary
    """
    if headers is None:
        headers = {}
    _ak, sk = split_securekey(sk)
    if ak is None:
        ak = _ak
    client = get_client(app_name, sk=sk, ak=ak, name=name)
    headers = {
        "x-kps-token": headers.get("x-kps-token"),
        "x-user-id": headers.get("x-user-id"),
        "x-version": headers.get("x-version"),
        "x-gray": headers.get("x-gray")
    }
    headers = client._prepare_headers(method, url, params, headers=headers)
    return {k: v for k, v in headers.items() if v is not None}


def _get_auth_info(app_name: str, api: str, method="POST", params: dict = None, securekey: str = None):
    from web.context import context
    if app_name.startswith("http"):
        host = app_name
    else:
        host = eureka.get_service_url(app_name=app_name)
    url = f"{host.strip('/')}{api}"
    ak, sk = os.getenv("SERVER_NAME").upper(), None
    if securekey is not None:
        ak, sk = split_securekey(securekey)
    headers = get_headers(
        app_name=app_name,
        method=method,
        url=url,
        params=params,
        headers=context.get('headers', {}),
        sk=sk,
        ak=ak,
        name=ak
    )
    headers["message-uuid"] = context.get("message_uuid", uuid.uuid4().hex)
    return url, headers


async def get(
    app_name: str,
    api: str,
    timeout: int = 5,
    params: dict = None,
    securekey: str = None,
    **kwargs
):
    url, headers = _get_auth_info(app_name, api, method="GET", params=params, securekey=securekey)
    return await http.get(
        url,
        params=params,
        timeout=timeout,
        headers=headers,
        **kwargs
    )


async def post(
    app_name: str,
    api: str,
    timeout: int = 8,
    json: dict = None,
    securekey: str = None,
    **kwargs
):
    """
    app_name: 请求的目标应用名
    api: 请求的接口
    """
    url, headers = _get_auth_info(app_name, api, method="POST", securekey=securekey)
    return await http.post(
        url,
        json=json,
        timeout=timeout,
        headers=headers,
        **kwargs
    )


async def stream(
    app_name: str,
    api: str,
    method: str = "POST",
    timeout: int = 30 * 60,
    json: dict = None,
    **kwargs
):
    url, headers = _get_auth_info(app_name, api, method="POST")
    async for chunk in http.stream(
        url,
        method=method,
        json=json,
        headers=headers,
        timeout=timeout,
        **kwargs
    ):
        yield chunk


async def delete(
    app_name: str,
    api: str,
    timeout: int = 5,
    json: dict = None,
    **kwargs
):
    url, headers = _get_auth_info(app_name, api, method="DELETE")
    return await http.delete(
        url,
        json=json,
        timeout=timeout,
        headers=headers,
        **kwargs
    )
