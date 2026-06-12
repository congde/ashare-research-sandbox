# --*-- conding:utf-8 --*--
import os
import json
import asyncio
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Type,
    Union,
    AsyncGenerator
)
import time

import email.message
import psutil
from contextlib import AsyncExitStack, asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import _StreamingResponse
from fastapi.routing import run_endpoint_function, serialize_response
from fastapi.utils import is_body_allowed_for_status_code
from fastapi.dependencies.utils import solve_dependencies
from fastapi.exceptions import FastAPIError
from fastapi.types import IncEx
from fastapi._compat import (
    ModelField,
    Undefined,
    _normalize_errors,
)
from fastapi import params
from fastapi.datastructures import Default, DefaultPlaceholder
from fastapi.dependencies.models import Dependant
from starlette.requests import Request
from starlette.responses import Response, RedirectResponse
from fastapi import FastAPI, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.routing import APIRoute as _APIRoute
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from web import code_msg
from web.exceptions import HttpException
from web.response import JsonResponse


load_dotenv()
logger = None
PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_headers(request) -> dict:
    headers = dict(request.headers)
    excluded_headers = {
        "x-real-ip", "x-forwarded-for", "host", "x-nginx-proxy", "connection",
        "content-length", "content-type", "user-agent", "accept", "message-uuid",
        "request_timestamp", "accept-encoding", "sec-fetch-site", "sec-fetch-mode",
        "sec-fetch-dest", "referer", "charset", "accept-language", "session",
        "cache-control", "sec-ch-ua", "", "authorization", "token", "cookie", "x-kps-token"
    }
    return dict(filter(lambda item: item[0].lower() not in excluded_headers, headers.items()))


async def record_request_info(request):
    try:
        if request.url.path.startswith("/actuator"):
            return
        query_params = dict(request.query_params)
        path_params = request.path_params
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        form = {}
        files = {}
        if request.headers.get("content-type") == "application/x-www-form-urlencoded":
            form = await request.form()
            form = dict(form)
        elif request.headers.get("content-type") == "multipart/form-data":
            form = await request.form()
            form = dict(form)
            files = {name: {"filename": file.filename, "content_type": file.content_type} for name, file in form.items() if isinstance(file, UploadFile)}
            form = {name: value for name, value in form.items() if not isinstance(value, UploadFile)}

        memory_percent = psutil.virtual_memory().percent
        all_parameters = {
            "request_args": {**path_params, **query_params, **body, **form, **files},
            "headers": get_headers(request),
        }
        all_parameters = {
            "method": request.method,
            "api": request.url.path,
            **all_parameters,
            # "cpu_percent": psutil.cpu_percent(percpu=True),
            "memory_percent": memory_percent
        }
        logger.info(f"BeforeRequest =====> {all_parameters}")
    except Exception as e:
        logger.exception(f"record_request_info error: {e}")


async def record_response_info(request, response):
    try:
        if request.url.path.startswith("/actuator"):
            return
        if isinstance(response, _StreamingResponse) and "text/event-stream" in dict(response.headers).get("content-type", ""):
            return
        suffix = {
            "api": request.url.path,
            "status_code": response.status_code
        }
        if response.media_type and 'application/json' in response.media_type:
            resp = json.loads(response.body.decode())
            suffix["response"] = {
                "code": resp.get("code"),
                "msg": resp.get("msg")
            }
        suffix.update({
            # "cpu_percent": psutil.cpu_percent(percpu=True),
            "memory_percent": psutil.virtual_memory().percent,
        })
        from web.middlewares import context
        request_timestamp = context.get("request_timestamp")
        if request_timestamp:
            suffix["interface_cost"] = f"{int((time.time() - float(request_timestamp)) * 1000)}ms"
        logger.info(f"AfterRequest =====> {suffix}")
    except Exception as e:
        logger.exception(f"record_response_info error, {e}")


class APIRoute(_APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        return self._request_handler(
            dependant=self.dependant,
            body_field=self.body_field,
            status_code=self.status_code,
            response_class=self.response_class,
            response_field=self.secure_cloned_response_field,
            response_model_include=self.response_model_include,
            response_model_exclude=self.response_model_exclude,
            response_model_by_alias=self.response_model_by_alias,
            response_model_exclude_unset=self.response_model_exclude_unset,
            response_model_exclude_defaults=self.response_model_exclude_defaults,
            response_model_exclude_none=self.response_model_exclude_none,
            dependency_overrides_provider=self.dependency_overrides_provider,
            embed_body_fields=self._embed_body_fields,
        )

    def _request_handler(
        self,
        dependant: Dependant,
        body_field: Optional[ModelField] = None,
        status_code: Optional[int] = None,
        response_class: Union[Type[Response], DefaultPlaceholder] = Default(JsonResponse),
        response_field: Optional[ModelField] = None,
        response_model_include: Optional[IncEx] = None,
        response_model_exclude: Optional[IncEx] = None,
        response_model_by_alias: bool = True,
        response_model_exclude_unset: bool = False,
        response_model_exclude_defaults: bool = False,
        response_model_exclude_none: bool = False,
        dependency_overrides_provider: Optional[Any] = None,
        embed_body_fields: bool = False,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        assert dependant.call is not None, "dependant.call must be a function"
        is_coroutine = asyncio.iscoroutinefunction(dependant.call)
        is_body_form = body_field and isinstance(body_field.field_info, params.Form)
        if isinstance(response_class, DefaultPlaceholder):
            actual_response_class: Type[Response] = response_class.value
        else:
            actual_response_class = response_class

        async def app(request: Request) -> Response:
            response: Union[Response, None] = None
            async with AsyncExitStack() as file_stack:
                try:
                    body: Any = None
                    if body_field:
                        if is_body_form:
                            body = await request.form()
                            file_stack.push_async_callback(body.close)
                        else:
                            body_bytes = await request.body()
                            if body_bytes:
                                json_body: Any = Undefined
                                content_type_value = request.headers.get("content-type")
                                if not content_type_value:
                                    json_body = await request.json()
                                else:
                                    message = email.message.Message()
                                    message["content-type"] = content_type_value
                                    if message.get_content_maintype() == "application":
                                        subtype = message.get_content_subtype()
                                        if subtype == "json" or subtype.endswith("+json"):
                                            json_body = await request.json()
                                if json_body != Undefined:
                                    body = json_body
                                else:
                                    body = body_bytes
                except json.JSONDecodeError as e:
                    raise HttpException(code=code_msg.CODE_PARAMETER_ERROR, extra=f"json_invalid, loc: {e.pos}, ctx: {e.msg}, body: {e.doc}") from e
                except Exception as e:
                    raise HttpException(code=code_msg.CODE_SERVER_ERROR, extra=f"reason={e}") from e
                errors: List[Any] = []
                async with AsyncExitStack() as async_exit_stack:
                    solved_result = await solve_dependencies(
                        request=request,
                        dependant=dependant,
                        body=body,
                        dependency_overrides_provider=dependency_overrides_provider,
                        async_exit_stack=async_exit_stack,
                        embed_body_fields=embed_body_fields,
                    )
                    errors = solved_result.errors
                    if not errors:
                        raw_response = await run_endpoint_function(
                            dependant=dependant,
                            values=solved_result.values,
                            is_coroutine=is_coroutine,
                        )
                        if isinstance(raw_response, Response):
                            if raw_response.background is None:
                                raw_response.background = solved_result.background_tasks
                            response = raw_response
                        else:
                            response_args: Dict[str, Any] = {
                                "background": solved_result.background_tasks
                            }
                            # If status_code was set, use it, otherwise use the default from the
                            # response class, in the case of redirect it's 307
                            current_status_code = (
                                status_code
                                if status_code
                                else solved_result.response.status_code
                            )
                            if current_status_code is not None:
                                response_args["status_code"] = current_status_code
                            if solved_result.response.status_code:
                                response_args["status_code"] = (
                                    solved_result.response.status_code
                                )
                            content = await serialize_response(
                                field=response_field,
                                response_content=raw_response,
                                include=response_model_include,
                                exclude=response_model_exclude,
                                by_alias=response_model_by_alias,
                                exclude_unset=response_model_exclude_unset,
                                exclude_defaults=response_model_exclude_defaults,
                                exclude_none=response_model_exclude_none,
                                is_coroutine=is_coroutine,
                            )
                            response = actual_response_class(content, **response_args)
                            if not is_body_allowed_for_status_code(response.status_code):
                                response.body = b""
                            response.headers.raw.extend(solved_result.response.headers.raw)
                if errors:
                    raise HttpException(code=code_msg.CODE_PARAMETER_ERROR, extra=f"reason={_normalize_errors(errors)}, body={body}")
            if response is None:
                raise FastAPIError(
                    "No response object was returned. There's a high chance that the "
                    "application code is raising an exception and a dependency with yield "
                    "has a block with a bare except, or a block with except Exception, "
                    "and is not raising the exception again. Read more about it in the "
                    "docs: https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#dependencies-with-yield-and-except"
                )
            return response

        return app 


def source_env(server_env: str):
    global logger

    # 先加载 .env，确保环境变量在 init_config/_update_config_from_env 读取前已就位
    # 否则 default.yaml 的默认值（如 litellm base_url）会被缓存进 config 对象，
    # 后续 load_dotenv 只更新 os.environ 而不刷新 config，导致 LLM 使用错误地址
    load_dotenv(override=True)

    from dao.context_store_bootstrap import init_context_store
    init_context_store()

    from dao.redis_bootstrap import init_redis
    init_redis()

    from web.logger import get_logger
    logger = get_logger(__name__)

    from web.config import init_config, init_workflow_config
    init_config(os.path.join(PROJECT_PATH, f"conf/default.yaml"))
    init_workflow_config(os.path.join(PROJECT_PATH, f"conf/workflow"))

    logger.info(f"... server_name={os.environ.get('SERVER_NAME', '')}, serverEnv={os.environ.get('serverEnv', '')}...")
    logger.info(f"Loading the {server_env} environment configuration.")


def create_app(name='ai-web3-tradding-agent'):
    server_env = os.environ.get('serverEnv', 'default')
    source_env(server_env)

    app = FastAPI(name=name, default_response_class=JsonResponse, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("ALLOW_ORIGIN", "*").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    from web.middlewares import RequestMiddleware, CustomMiddleware
    app.add_middleware(CustomMiddleware)
    app.add_middleware(RequestMiddleware)

    static_dir = os.path.join(PROJECT_PATH, "src", "web", "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    shared_dir = os.path.join(PROJECT_PATH, "shared")
    if os.path.isdir(shared_dir):
        app.mount("/shared", StaticFiles(directory=shared_dir), name="shared")

    # 禁用静态文件缓存，确保重启后浏览器加载最新版本
    @app.middleware("http")
    async def no_cache_static(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/") or request.url.path.startswith("/shared/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response

    # Register root and dashboard pages at app level (router with prefix="/" is invalid in FastAPI)
    templates = Jinja2Templates(directory=os.path.join(PROJECT_PATH, "src", "web", "templates"))

    @app.get("/")
    async def index():
        return RedirectResponse(url="/dashboard", status_code=302)

    @app.get("/chat")
    async def chat_page(request: Request):
        return templates.TemplateResponse("index.html", {"request": request})

    @app.get("/dashboard")
    async def dashboard(request: Request):
        return templates.TemplateResponse("dashboard.html", {"request": request})

    @app.get("/strategy")
    async def strategy(request: Request):
        return templates.TemplateResponse("strategy.html", {"request": request})

    @app.get("/analysis")
    async def analysis(request: Request):
        return templates.TemplateResponse("analysis.html", {"request": request})

    @app.get("/backtest")
    async def backtest(request: Request):
        return templates.TemplateResponse("backtest.html", {"request": request})

    @app.get("/data-sources")
    async def data_sources_page(request: Request):
        return templates.TemplateResponse("data_sources.html", {"request": request})

    @app.get("/trading-agent")
    async def trading_agent_redirect():
        return RedirectResponse(url="/data-sources", status_code=302)

    @app.get("/live-trading")
    async def live_trading_page(request: Request):
        return templates.TemplateResponse("live_trading.html", {"request": request})

    @app.get("/dashboard/live-trading")
    async def live_trading_dashboard_alias():
        return RedirectResponse(url="/live-trading", status_code=302)

    return app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    from web.router import auto_import
    auto_import("src/web/api", app)
    from libs.eureka import eureka
    mcp_client = None
    eureka_enabled = os.environ.get("EUREKA_ENABLED", "true").lower() in {"1", "true", "yes", "y", "on"}
    if eureka_enabled:
        await eureka.up()
    else:
        logger.info("Eureka client disabled by EUREKA_ENABLED=false")
    mcp_enabled_raw = os.environ.get("MCP_CLIENT_ENABLED")
    if mcp_enabled_raw is None:
        from web.config import config as web_config
        mcp_securekey = getattr(web_config, "mcp_client_securekey", "") if web_config else ""
        mcp_enabled = not (os.environ.get("serverEnv") == "local" and not mcp_securekey)
    else:
        mcp_enabled = mcp_enabled_raw.lower() in ("1", "true", "yes", "y")
    if mcp_enabled:
        from mcp.mcp_http_client import mcp_client
        await mcp_client.initialize()
    else:
        logger.info("MCP client disabled for local startup without SECUREKEY")

    from web.config import is_risk_control_enabled

    if is_risk_control_enabled():
        from llm.shield.handler import llm_shield
        await llm_shield.init()
    else:
        logger.info("risk_control_enabled=false: skipping llm_shield.init")

    from quant.scheduler import start_quant_scheduler
    start_quant_scheduler()

    try:
        from web.api.valuescan_sse_worker import start_valuescan_sse_worker

        await start_valuescan_sse_worker()
    except Exception as exc:
        logger.warning("ValueScan SSE worker start failed: %s", exc)

    yield

    try:
        from web.api.valuescan_sse_worker import stop_valuescan_sse_worker

        await stop_valuescan_sse_worker()
    except Exception as exc:
        logger.warning("ValueScan SSE worker stop failed: %s", exc)

    from quant.scheduler import stop_quant_scheduler
    await stop_quant_scheduler()

    if is_risk_control_enabled():
        from llm.shield.handler import llm_shield
        await llm_shield.close()
    if mcp_client is not None:
        await mcp_client.shutdown()
    from libs.sub_task import sub_task
    await sub_task.shutdown()
    await eureka.down()
    
    logger.info("System has been shut down.")
