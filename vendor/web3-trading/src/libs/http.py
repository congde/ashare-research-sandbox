# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/20 13:14:30
'''


import time
import json
import logging
import asyncio
import json
from typing import Union

import httpx
# from py_eureka_client.http_client import HttpClient, HttpRequest, URLError, HttpResponse
from dc_api_security.kc_eureka.http_client import HttpClient, HttpRequest, URLError, HttpResponse
from libs.wrapper import usage_http_time

httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)
httpx_logger.disabled = True


logger = logging.getLogger(__name__)


def _effective_retries(url: str, method: str, retries: int) -> int:
    base_retries = max(0, int(retries or 0))
    if method.upper() == "GET" and "kucoin.com" in url and "/market/candles" in url:
        return max(base_retries, 3)
    return base_retries


async def _sleep_before_retry(attempt: int) -> None:
    await asyncio.sleep(min(0.5 * (2 ** max(0, attempt - 1)), 3.0))


class APIError(Exception):
    def __init__(self, **kwargs):
        self.payload = kwargs
        self._error_msg = str(kwargs)
        super().__init__(self._error_msg)
        
    def __repr__(self):
        return f"http fetch error:\n{self._error_msg}"

    def __str__(self):
        return self.__repr__()


class APITimeoutError(APIError):
    pass


class APIConnectionError(APIError):
    pass


def _filter_sensitive_words(kwargs) -> str:
    headers = kwargs.get("headers", {})
    excluded_headers = {
        "x-real-ip", "x-forwarded-for", "host", "x-nginx-proxy", "connection",
        "content-length", "content-type", "user-agent", "accept", "message-uuid",
        "request_timestamp", "accept-encoding", "sec-fetch-site", "sec-fetch-mode",
        "sec-fetch-dest", "referer", "charset", "accept-language", "session",
        "cache-control", "sec-ch-ua", "", "authorization", "token", "cookie", "x-kps-token"
    }
    kwargs["headers"] = dict(filter(lambda item: item[0].lower() not in excluded_headers, headers.items()))
    return kwargs


async def _fetch(url, method='GET', timeout=10, retries=1, resp_json=True, **kwargs):
    method_upper = method.upper()
    effective_retries = _effective_retries(url, method_upper, retries)
    retryable_statuses = {408, 425, 429, 500, 502, 503, 504}
    async with httpx.AsyncClient(verify=False) as client:
        resp = None
        attempt = 0
        while True:
            try:
                resp = await client.request(
                    method=method_upper,
                    url=url,
                    timeout=timeout,
                    **kwargs
                )
                resp.raise_for_status()
                if resp_json:
                    if resp.status_code == 204:
                        return resp.text
                    try:
                        return resp.json()
                    except json.decoder.JSONDecodeError:
                        return resp.text
                return resp
            except httpx.TimeoutException as e:
                if attempt < effective_retries:
                    attempt += 1
                    logger.warning(
                        "fetch timeout, retrying %s/%s, url=%s, error=%s",
                        attempt,
                        effective_retries,
                        url,
                        e,
                    )
                    await _sleep_before_retry(attempt)
                    continue
                logger.warning(
                    "fetch timeout, url=%s, attempts=%s, error=%s",
                    url,
                    effective_retries + 1,
                    e,
                )
                raise APITimeoutError(
                    url=url,
                    method=method,
                    error_msg=str(e),
                    **_filter_sensitive_words(kwargs)
                ) from e
            except httpx.ConnectError as e:
                if attempt < effective_retries:
                    attempt += 1
                    logger.warning(
                        "fetch connection error, retrying %s/%s, url=%s, error=%s",
                        attempt,
                        effective_retries,
                        url,
                        e,
                    )
                    await _sleep_before_retry(attempt)
                    continue
                logger.warning(f'fetch connection refused, url={url}, error={e}')
                kwargs['error_msg'] = str(e)
                raise APIConnectionError(
                    url=url,
                    method=method,
                    **_filter_sensitive_words(kwargs)
                ) from e
            except httpx.HTTPStatusError as e:
                status = e.response.status_code if e.response is not None else None
                if attempt < effective_retries and status in retryable_statuses:
                    attempt += 1
                    logger.warning(
                        "fetch http status error, retrying %s/%s, url=%s, status=%s, error=%s",
                        attempt,
                        effective_retries,
                        url,
                        status,
                        e,
                    )
                    await _sleep_before_retry(attempt)
                    continue
                log_level = logging.INFO if status in {400, 401, 402, 403, 404} else logging.WARNING
                logger.log(
                    log_level,
                    "fetch http status error, url=%s, status=%s, reason=%s",
                    url,
                    status,
                    e.response.reason_phrase if e.response is not None else "",
                )
                kwargs.update({
                    "status": status,
                    "error_msg": e.response.text if e.response is not None else str(e),
                    "reason": e.response.reason_phrase if e.response is not None else "",
                })
                raise APIConnectionError(
                    url=url,
                    method=method,
                    **_filter_sensitive_words(kwargs)
                ) from e
            except asyncio.CancelledError:
                # Preserve task cancellation so Ctrl+C / graceful shutdown can exit promptly.
                raise
            except Exception as e:
                if attempt < effective_retries:
                    attempt += 1
                    logger.warning(
                        "fetch error, retrying %s/%s, url=%s, error=%s",
                        attempt,
                        effective_retries,
                        url,
                        e,
                    )
                    await _sleep_before_retry(attempt)
                    continue
                logger.exception(f'fetch error, url={url}, error={e}')
                if resp is None:
                    kwargs['error_msg'] = str(e)
                else:
                    kwargs.update({
                        "status": resp.status_code,
                        "error_msg": resp.text,
                        "reason": resp.reason_phrase
                    })
                raise APIConnectionError(
                    url=url,
                    method=method,
                    **_filter_sensitive_words(kwargs)
                ) from e


@usage_http_time
async def get(url, *args, **kwargs):
    return await _fetch(url=url, method="GET", *args, **kwargs)


@usage_http_time
async def post(url, *args, **kwargs):
    return await _fetch(url=url, method="POST", *args, **kwargs)


@usage_http_time
async def put(url, *args, **kwargs):
    return await _fetch(url=url, method="PUT", *args, **kwargs)


@usage_http_time
async def delete(url, *args, **kwargs):
    return await _fetch(url=url, method="DELETE", *args, **kwargs)


async def stream(url, method="POST", *args, timeout=6000, **kwargs):
    start_time = time.time()
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(method, url, *args, **kwargs) as response:
            async for chunk in response.aiter_lines():
                if not chunk:
                    continue
                yield chunk
    interface_cost = int((time.time() - start_time) * 1000)
    logger.info(f"stream({url}) => usage time: {interface_cost}ms")


class EurekaHttpResponse(HttpResponse):

    def __init__(self, raw_response=None) -> None:
        self.raw_response = raw_response
        self.__body_read = False
        self.__body_text = ''

    def _read_body(self):
        res = self.raw_response
        if hasattr(res, 'text'):
            return res.text
        return res

    @property
    def body_text(self):
        if not self.__body_read:
            self.__body_text = self._read_body()
            self.__body_read = True
        return self.__body_text

    @body_text.setter
    def body_text(self, val):
        self.__body_text = val
        self.__body_read = True


class EurekaHttpClient(HttpClient):
    async def urlopen(
        self,
        request: Union[str, HttpRequest] = None,
        data: bytes = None,
        timeout: float = None
    ) -> EurekaHttpResponse:
        if isinstance(request, HttpRequest):
            req = request
        elif isinstance(request, str):
            req = HttpRequest(request, headers={'Accept-Encoding': 'gzip'}, method="GET")
        else:
            raise URLError("Invalid URL")
        resp = await _fetch(
            url=req.url,
            method=req.method,
            headers=req.headers,
            data=data,
            timeout=timeout,
            resp_json=False
        )
        return EurekaHttpResponse(resp)
