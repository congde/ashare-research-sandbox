# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/20 11:07:01
'''


import json
import os
import logging
import socket
import asyncio
import random
from typing import Callable, Dict, Union

# from py_eureka_client import http_client
from dc_api_security.kc_eureka import http_client

from libs.http import EurekaHttpClient
http_client.set_http_client(EurekaHttpClient())
from dc_api_security.kc_eureka import (
    eureka_client,
    HA_STRATEGY_OTHER,
    HA_STRATEGY_RANDOM,
    HA_STRATEGY_STICK,
    INSTANCE_STATUS_UP
)

from libs.wrapper import async_retry


__all__ = (
    'EurekaManager',
)

logger = logging.getLogger(__name__)


class EurekaClient(eureka_client.EurekaClient):

    async def walk_nodes(
        self,
        app_name: str = "",
        service: str = "",
        prefer_ip: bool = False,
        prefer_https: bool = False,
        walker: Callable = None,
        retry=3,
        **kwargs
    ) -> Union[str, Dict, http_client.HttpResponse]:
        assert app_name is not None and app_name != "", "application_name should not be null"

        error_nodes = []
        app_name = app_name.upper()
        logger.info(f"walk_nodes app_name={app_name}, service={service}, prefer_ip={prefer_ip}, prefer_https={prefer_https}, retry={retry}, kwargs={kwargs}")
        node = self.__get_available_service(app_name, **kwargs)
        if retry > 0 and not node:
            logger.warning(f"Application_name={app_name} is not found")
            await self.__pull_full_registry()
            return await self.walk_nodes(
                app_name=app_name,
                service=service,
                prefer_ip=prefer_ip,
                retry=retry-1
            )

        while node is not None:
            try:
                url = self.__generate_service_url(
                    node, prefer_ip, prefer_https)
                if service.startswith("/"):
                    url = url + service[1:]
                else:
                    url = url + service
                logger.info("do service with url::" + url)
                obj = walker(url)
                if asyncio.iscoroutine(obj):
                    return await obj
                else:
                    return obj
            except (ConnectionError, TimeoutError, socket.timeout) as e:
                logger.warning(
                    f"do service {service} in node [{node.instanceId}] error, use next node. Error: {e}")
                error_nodes.append(node.instanceId)
                node = self.__get_available_service(app_name, error_nodes, **kwargs)
            except (http_client.HTTPError, http_client.URLError) as e:
                if self.__strict_service_error_policy:
                    logger.warning(
                        f"do service {service} in node [{node.instanceId}] error, use next node. Error: {e}")
                    error_nodes.append(node.instanceId)
                    node = self.__get_available_service(app_name, error_nodes, **kwargs)
                else:
                    raise e

        raise http_client.URLError("Try all up instances in registry, but all fail")

    def get_service_url(self, app_name: str, prefer_ip: bool = False, prefer_https: bool = False, **kwargs) -> str:
        assert app_name is not None and app_name != "", "application_name should not be null"
        
        app_name = app_name.upper()
        node = self.__get_available_service(app_name, **kwargs)
        
        if not node:
            raise eureka_client.DiscoverException(f"Cannot find any available instance for application: {app_name}")
        url = self.__generate_service_url(node, prefer_ip, prefer_https)
        if not url:
            raise eureka_client.DiscoverException(f"Cannot find any available instance for application: {app_name}")
        logger.info(f"Eureka app_name={app_name}, base_url={url}, kwargs={kwargs}")
        return url
    

def get_interface_ip(family: socket.AddressFamily) -> str:
    host = "fd31:f903:5ab5:1::1" if family == socket.AF_INET6 else "10.253.155.219"
    with socket.socket(family, socket.SOCK_DGRAM) as s:
        try:
            s.connect((host, 58162))
        except OSError:
            return "::1" if family == socket.AF_INET6 else "127.0.0.1"

        return s.getsockname()[0]


class EurekaManager:

    def __init__(
        self,
        server_name: str = None,
        server_port: int =None,
        eureka_server: str = None,
        eureka_username: str = None,
        eureka_password: str = None,
    ):
        self.eureka_server = eureka_server or os.environ.get("EUREKA_SERVER")
        self.eureka_username = eureka_username or os.environ.get("EUREKA_USERNAME") or ""
        self.eureka_password = eureka_password or os.environ.get("EUREKA_PASSWORD") or ""
        self.server_name = server_name or os.environ.get("SERVER_NAME")
        # if not self.server_name.lower().endswith("pre") and os.environ.get("serverEnv", "") == "pre":
        #     self.server_name = f"{self.server_name.upper()}-PRE"
        self.server_port = int(server_port or os.environ.get("SERVER_PORT") or 10240)
        self.server_ip = get_interface_ip(socket.AF_INET)
        if os.environ.get('serverEnv', '') != 'local':
            logger.info(f'Eureka Config: eureka_server={self.eureka_server}, eureka_username={self.eureka_username}, eureka_password=***, server_name={self.server_name}, server_port={self.server_port}, server_ip={self.server_ip}')
        self._client = None

    async def init(self):
        if os.environ.get('serverEnv', '') in ('pre', 'prod'):
            logger.info(f"Eureka init pre or prod")
            self._client = EurekaClient(
                eureka_server=self.eureka_server,
                app_name=self.server_name,
                instance_port=self.server_port,
                instance_host=self.server_ip,
                instance_ip=self.server_ip,
                renewal_interval_in_secs=5,
                duration_in_secs=15,
                ha_strategy=HA_STRATEGY_OTHER
            )
        else:
            logger.info(f"Eureka init offline")
            self._client = EurekaClient(
                eureka_server=self.eureka_server,
                eureka_basic_auth_user=self.eureka_username,
                eureka_basic_auth_password=self.eureka_password,
                app_name=self.server_name,
                instance_port=self.server_port,
                instance_host=self.server_ip,
                instance_ip=self.server_ip,
                renewal_interval_in_secs=5,
                duration_in_secs=15,
                ha_strategy=HA_STRATEGY_OTHER
            )
        await self._client.start()
        app = self._client.applications.get_application(self.server_name)
        all_apps = getattr(self._client.applications, "applications", None)
        app_count = len(all_apps) if all_apps is not None else "N/A"
        logger.info(
            f"All applications={app_count}, {self.server_name} info: "
            f"name={app.name}, instances={app.instances}, up_instances={app.up_instances}"
        )

    async def up(self):
        if self._client is None:
            logger.info("Starting registration with Eureka.")
            await self.init()
            logger.info("Successfully completed registration with Eureka.")

    async def down(self):
        if self._client is not None:
            logger.info("Stopping Eureka client...")
            await self._client.stop()
            logger.info("Eureka client stopped successfully.")

    @async_retry(times=3, delay=0.5)
    async def fetch(
        self,
        app_name: str,  # 服务名
        api: str,  # 请求路径
        return_type="json",
        method="POST",
        headers={"Content-Type": "application/json"},
        json: dict = None,
        timeout: int = 5,
    ):
        return await self._client.do_service(
            app_name=app_name,
            service=api,
            return_type=return_type,
            method=method,
            headers=headers,
            data=json,
            timeout=timeout
        )

    def get_service_url(self, app_name, prefer_ip=True, headers: dict = None):
        from web.context import context
        if headers is None:
            headers = context.get('headers', {})
            user_id = headers.get('x-user-id')
            headers = {
                "X-USER-ID": user_id,
                "x-user-id": user_id,
                "x-version": headers.get('x-version'),
                "x-gray": headers.get('x-gray')
            }
        return self._client.get_service_url(app_name, prefer_ip=prefer_ip, headers=headers)


eureka = EurekaManager()
