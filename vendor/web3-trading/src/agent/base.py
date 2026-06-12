import logging
import asyncio
import time
import json
import traceback
import functools
from typing import Optional
from collections import OrderedDict

from agent.schema import (
    SessionModel,
    QAModel,
    AgentType,
    StepModel,
    StepType,
    StepStatusType,
    StreamResponse,
    StreamStatusType,
    SessionStatusType,
    MemoryModel,
    ResourceReference,
    ReferenceType,
)
from libs.language import get_localized_message, ENGLISH_NAME_TO_CODE_MAP, detect_reply_language
from web.config import config, is_risk_control_enabled
from mcp.mcp_http_client import ToolsInfo
from web.context import context
from memory.base import BaseMemory
from memory.mem0 import Mem0Memory
from web.exceptions import HttpException, RiskException
from web import code_msg
from libs.wrapper import usage_time
from llm.base import create_llm
from llm.shield.url_checker import get_url_checker
from agent.mixins import HistoryMixin, ToolMixin, ResponseMixin, OrchestrationMixin

# Agent orchestration imports
from agent.tools.registry import ToolRegistry
from agent.tools.subagent import SubagentManager

logger = logging.getLogger(__name__)
llm, model_name = create_llm()


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

            except Exception as e:
                logger.exception("Step execution unkown error")
                step.status = StepStatusType.FAILED
                step.log = f"Error occurred while processing request: {str(e)}"
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


class BaseAgent(HistoryMixin, ToolMixin, ResponseMixin, OrchestrationMixin):
    NAME = AgentType.QUICK_REASONING
    DESCRIPTION = ""

    def __init__(
            self,
            query: str,
            extra_body: "ExtraBodyModel", # type: ignore
            user_id: str = None,
            session_id=None,
            qa: QAModel = None,
            memory: BaseMemory = None,
            **kwargs
    ):
        from web.api.chat.chat import ExtraBodyModel
        self.extra_body: ExtraBodyModel = extra_body

        self.query = query
        self.user_id = user_id
        self.session_id = session_id
        self.qa_id = None
        self.qa = qa
        self.session = None
        self.system_lang_code = None
        self.cache = {}
        # 默认LLM（不同的任务可能模型不一样，注意区分）
        self.llm = None
        self.model_name = None
        self.kwargs = kwargs
        self.memory = memory or Mem0Memory(user_id=self.user_id)
        self._pending_tasks = OrderedDict()
        self._tools_info: ToolsInfo = None
        self._tool_call: dict = {}
        from llm.shield.handler import llm_shield
        self._llm_shield = llm_shield
        self._url_checker = get_url_checker()
        self.is_risk = False
        self.init_event = asyncio.Event()
        self.offset = 0

        # --- Agent Orchestration ---
        self._tool_registry: Optional[ToolRegistry] = None
        self._subagent_manager: Optional[SubagentManager] = None
        self._skills: dict = {}
        self._gateway_route_result = None

    # ----------------------------------------------------------
    # Gateway injection interface
    # ----------------------------------------------------------

    def inject_tools(self, registry: ToolRegistry) -> None:
        """Called by Gateway to set the tool registry before execution."""
        self._tool_registry = registry

    def inject_skills(self, skills: dict) -> None:
        """Called by Gateway to set available skills before execution."""
        self._skills = skills or {}

    # ============================================================
    # Agent Orchestration Properties & Methods
    # (inherited from OrchestrationMixin)
    # ============================================================

    @usage_time
    async def on_init(self, *args, **kwargs):
        current_memory_messages = []
        session_title_length = 100
        self.session = SessionModel(userId=self.user_id, id=self.session_id)
        session = await SessionModel.get(self.session_id, is_delete=None)
        if session is None:
            query = self.query.replace(str(self.extra_body.model_dump(exclude_defaults=True, mode="json")), "").rstrip()
            self.qa = self.qa or QAModel(
                query=query,
                userId=self.user_id,
                sessionId=self.session.id,
                agentType=self.NAME,
                source=self.kwargs.get("source")
            )
            self.session.latestQaId = self.qa.id
            self.session.title = query[:session_title_length]
            current_memory_messages.append({"role": "user", "content": query})
            self.qa_id = self.qa.id
        
        elif session.get("isDeleted", False):
            raise HttpException(code=code_msg.CODE_SESSION_DELETED)

        else:
            await self.session.load(session=session)
            if self.session.userId != self.user_id:
                raise HttpException(code=code_msg.CODE_PARAMETER_ERROR)
            if self.session.status != SessionStatusType.COMPLETED:
                raise HttpException(code=code_msg.CODE_CONVERSATION_IN_PROGRESS)

            if self.session.latestQaId:
                lastest_qa = await self._get_latest_qa(self.session.latestQaId)
                self.qa = self.qa or QAModel(
                    parentId=lastest_qa.id,
                    userId=self.user_id,
                    sortIndex=lastest_qa.sortIndex + 1,
                    query=self.query,
                    sessionId=self.session.id,
                    agentType=self.NAME,
                    source=self.kwargs.get("source")
                )
                lastest_answer = self._get_latest_answer(lastest_qa)
                if lastest_answer:
                    current_memory_messages.append({"role": "assistant", "content": lastest_answer})
            else:
                self.qa = self.qa or QAModel(
                    query=self.query,
                    userId=self.user_id,
                    sessionId=self.session.id,
                    agentType=self.NAME,
                    source=self.kwargs.get("source")
                )
                self.session.title = self.query[:session_title_length]
                self.session.latestQaId = self.qa.id

            current_memory_messages.append({"role": "user", "content": self.query})
            self.session.status = SessionStatusType.PENDING
            self.qa_id = self.qa.id
        self.qa.source = self.kwargs.get("source")
        kia_memory = MemoryModel(qaId=self.qa.id)
        context.set("kia_memory", kia_memory)
        await self.qa.save(check_canceled=False)
        await self.session.save()
        self._pending_tasks[self.memory.ADD_FUNC_NAME] = await self.memory.add(current_memory_messages)
        await self.memory.init_search(self.query)
        logger.info(f"init agent, qa={self.qa.model_dump(mode='json')}, session={self.session.model_dump(mode='json')}")
        self.history = None
        self.llm = await self._create_client()

        # Initialize transcript writer (shadow write, non-blocking)
        if self._is_context_enabled():
            try:
                writer = self._get_transcript_writer()
                if writer:
                    await writer.append_user_message(self.query)
            except Exception as e:
                logger.debug(f"Transcript writer init/append failed (non-critical): {e}")

    async def _run(self):
        raise NotImplementedError("The core calling logic must be implemented.")

    async def _save(self, error=False, log=""):
        """优化的保存方法，直接执行保存逻辑确保数据持久化"""
        if context.get("is_cancelled", False):
            return
        # 保存QA数据
        qa_saved = False
        try:
            if self.qa:
                # 计算耗时（容错处理：测试环境可能没有request_timestamp）
                request_timestamp = context.get("request_timestamp")
                if request_timestamp:
                    self.qa.elapsedMs = int((time.time() - request_timestamp) * 1000)
                elif self.qa.elapsedMs == 0:
                    # 如果没有request_timestamp但elapsedMs还是0，使用createTime计算
                    self.qa.elapsedMs = int((time.time() - self.qa.createTime) * 1000)

                # 过滤空步骤
                self.qa.answer = [step for step in self.qa.answer if step is not None]

                # 添加系统步骤，前端会检测该类型为SYSTEM时才停止loading，防止页面假死
                if self.qa.answer:
                    _type = self.qa.answer[-1].type
                    if _type != StepType.SYSTEM:
                        latest_step = StepModel(
                            type=StepType.SYSTEM,
                            status=self.qa.answer[-1].status if not error else StepStatusType.FAILED,
                            log=log or self.qa.answer[-1].log
                        )
                        self.qa.answer.append(latest_step)
                else:
                    logger.warning('The answer is empty')
                    latest_step = StepModel(
                        type=StepType.SYSTEM,
                        status=StepStatusType.FAILED,
                        log=code_msg.get_msg(code_msg.CODE_SERVER_ERROR)
                    )
                    self.qa.answer.append(latest_step)

                # 更新sessin信息
                if self.session:
                    self.session.latestQaId = self.qa.id
                    self.session.status = SessionStatusType.COMPLETED

                # 保存QA
                logger.info(f"Saving qa, qaId={self.qa.id}")
                await self.qa.save()

                qa_saved = True
                logger.info("QA saved successfully")
            else:
                logger.warning("Qa is None")
        except asyncio.CancelledError:
            logger.error(code_msg.get_msg(code_msg.CODE_NETWORK_ERROR))
            try:
                if not qa_saved:
                    await asyncio.shield(self.qa.save(force_failed=True))
            except asyncio.CancelledError:
                pass
        except:
            logger.exception('Save QA error')

        # 保存Session数据
        session_saved = False
        try:
            if self.session:
                logger.info(f"Saving session: {self.session.model_dump(mode='json')}")
                await self.session.save()
                session_saved = True
                logger.info("Session saved successfully")
        except asyncio.CancelledError:
            try:
                if not session_saved:
                    await asyncio.shield(self.session.save())
            except asyncio.CancelledError:
                pass
        except:
            logger.exception('Save session error')

    async def _destroy(self):
        global llm
        global model_name
        llm, model_name = create_llm()
        if self._pending_tasks:
            logger.info(f"Waiting for {len(self._pending_tasks)} tasks to complete")
            results = await asyncio.gather(*self._pending_tasks.values(), return_exceptions=True)
            for task_key, result in zip(self._pending_tasks.keys(), results):
                if isinstance(result, Exception):
                    error_msg = f"Task [{task_key}] failed: {type(result).__name__}: {result}"
                    if hasattr(result, '__traceback__'):
                        error_msg += f"\n{''.join(traceback.format_exception(type(result), result, result.__traceback__))}"
                    logger.error(error_msg)
                elif task_key == self.memory.ADD_FUNC_NAME and result:
                    for mem in result:
                        mem_id = mem.get("id")
                        if not mem_id:
                            continue
                        if context.get("is_risk", False):
                            await self.memory.delete_memory(mem_id)

            logger.info('All tasks completed')
            self._pending_tasks.clear()

        # Cleanup subagent manager
        if self._subagent_manager:
            await self._subagent_manager.cleanup()
            self._subagent_manager = None

        # Clear tool registry
        self._tool_registry = None

    async def check_query(self):
        """query风控检测"""
        start_time = time.time()
        # Detect reply language from the actual query to avoid UI language bias
        try:
            detected_language = detect_reply_language(
                self.query,
                default_lang_code=self.system_lang_code or "en",
            )
            self.cache.update({"reply_language": detected_language})
            logger.info(f"[Language] Detected reply_language: {detected_language}")
        except Exception as e:
            logger.warning(f"[Language] Failed to detect reply_language: {e}")
        try:
            if is_risk_control_enabled():
                if config.risk_enable:
                    risk_result = await self._llm_shield.check(self.query, self.system_lang_code)
                else:
                    risk_result = self._llm_shield._local_sensitive_check(self.query, self.system_lang_code)

                if risk_result.has_risk and risk_result.should_terminate:
                    logger.warning(f"User query blocked by risk control: {risk_result.risk_category}")
                    event = self._create_stream_response(
                        StreamStatusType.BLOCKED_QUERY,
                        log=risk_result.fallback_message,
                        session_id=self.session_id,
                    )
                    self.init_event.set()
                    raise HttpException(code=code_msg.CODE_QUERY_RISK, msg=event)

                if config.url_risk_enable:
                    url_result = await self._url_checker.check_text(self.query)
                    if url_result.has_risk:
                        fallback_msg = self._url_checker.get_fallback_message(self.system_lang_code)
                        logger.warning(
                            f"❌ [Query风控-URL] URL检测不通过\n"
                            f"  风险URL数量: {len(url_result.risky_urls)}\n"
                            f"  风险URL列表: {url_result.risky_urls}\n"
                            f"  URL详情: {json.dumps(url_result.url_details, ensure_ascii=False, indent=2)}\n"
                            f"  兜底消息: {fallback_msg}"
                        )
                        event = self._create_stream_response(
                            StreamStatusType.BLOCKED_QUERY,
                            log=fallback_msg,
                            session_id=self.session_id,
                        )
                        self.init_event.set()
                        raise HttpException(code=code_msg.CODE_QUERY_RISK, msg=event)
                    else:
                        if url_result.risky_urls or len(url_result.url_details) > 0:
                            checked_count = len(url_result.url_details)
                            logger.info(f"✅ [Query风控-URL] 检测通过: {checked_count} 个URL均安全")
                        else:
                            logger.info(f"✅ [Query风控-URL] 未提取到URL")
                    logger.info(f"✅ [Query风控] 全部检测通过，耗时: {int((time.time() - start_time) * 1000)}ms")
            else:
                logger.info("[Risk] risk_control_enabled=false, skipping query risk checks")
        except HttpException as e:
            raise
        except Exception as e:
            interface_cost = int((time.time() - start_time) * 1000)
            logger.exception(f"Risk query check error, interface_cost={interface_cost}ms, query={self.query}, error_msg={e}")

    async def _run_with_tool_step_save(self):
        """包装 _run()：事件发往前端的同时，顺带累积并保存所有 step（QUERY_ANALYSIS、TOOL_EXECUTION、ANSWER_RESPONSE 等），便于刷新后展示。"""
        current_step = None
        current_step_start = None
        async for event in self._run():
            try:
                ev = StreamResponse(**json.loads(event))
                if ev.status == StreamStatusType.START:
                    current_step = StepModel(type=ev.type)
                    current_step_start = time.time()
                    # TOOL_EXECUTION 与 QUERY_ANALYSIS/ANSWER_RESPONSE 一致：保证 step.step 有 TITLE/CONTENT/TITLE_CORRECTION 结构
                    if current_step.step is None:
                        current_step.step = {}
                    if ev.type == StepType.TOOL_EXECUTION:
                        current_step.step[StepType.TITLE] = ""
                        current_step.step[StepType.CONTENT] = ""
                        current_step.step[StepType.TITLE_CORRECTION] = ""
                elif ev.type in (StepType.TITLE, StepType.CONTENT, StepType.TITLE_CORRECTION) and current_step is not None and ev.content is not None:
                    if current_step.step is None:
                        current_step.step = {}
                    tmp = current_step.step.get(ev.type)
                    if isinstance(ev.content, str):
                        current_step.step[ev.type] = (tmp or "") + ev.content
                    elif isinstance(ev.content, (list, tuple)):
                        current_step.step[ev.type] = (tmp or []) + list(ev.content)
                    elif isinstance(ev.content, dict):
                        current_step.step[ev.type] = dict(tmp or {})
                        current_step.step[ev.type].update(ev.content)
                elif ev.status == StreamStatusType.END and current_step is not None and current_step.type == ev.type and ev.type == StepType.TOOL_EXECUTION:
                    current_step.elapsedMs = int((time.time() - current_step_start) * 1000)
                    current_step.status = StepStatusType.SUCCEEDED
                    plan = self.cache.get("plan")
                    if plan:
                        current_step.step[StepType.TOOL_RESULT] = plan.model_dump(mode="json").get("tasks", [])
                    self.qa.answer.append(current_step)
                    logger.info(f"Saving step [{current_step.type}], elapsed={current_step.elapsedMs}ms")
                    await self.qa.save()
                    current_step = None
            except Exception:
                pass
            yield event

    async def run(self):
        """优化后的运行方法，逻辑更简洁清晰"""
        error_occurred = False
        save_flag = True
        error_log = ""

        try:
            # 发送开始信号
            yield self._create_stream_response(StreamStatusType.START)
            self.init_event.set()

            # 执行主逻辑；可选流式风控（risk_control_enabled=false 时直通，不做本地敏感词扫描）
            if is_risk_control_enabled():
                if config.risk_enable:
                    async for event in self._llm_shield.stream_check(self._run_with_tool_step_save(), self.system_lang_code):
                        yield event
                        await asyncio.sleep(0)
                else:
                    async for event in self._llm_shield.stream_check_fallback(self._run_with_tool_step_save(), self.system_lang_code):
                        yield event
                        await asyncio.sleep(0)
            else:
                async for event in self._run_with_tool_step_save():
                    yield event
                    await asyncio.sleep(0)

        except StopError as e:
            error_occurred = True
            logger.error(f"Step error, {str(e)}")

        except asyncio.CancelledError as e:
            error_occurred = True
            logger.error(f"Canceled error, {str(e)}")

        except RiskException as e:
            context.set("is_risk", True)
            logger.error(f"Risk error, {e}")
            error_occurred = True
            save_flag = False
            yield self._create_stream_response(
                StreamStatusType.BLOCKED_ANSWER,
                log=e.msg
            )
            step = StepModel(
                type=StepType.SYSTEM,
                status=StepStatusType.BLOCKED_ANSWER,
                log=e.msg
            )
            self.qa.answer.append(step)
            await self.qa.save(force_failed=True, status=StepStatusType.BLOCKED_ANSWER, log=e.msg)
            self.session.latestQaId = self.qa.id
            self.session.status = SessionStatusType.COMPLETED
            await self.session.save()

        except (HttpException, Exception) as e:
            error_occurred = True
            error_log = f"HttpException error, {e.msg}" if isinstance(e, HttpException) else f"Exception error, {str(e)}"

            logger.critical(
                f'[{self.__class__.__name__}], '
                f'sessionId={self.session.id if self.session else None}, '
                f'qaId={self.qa.id if self.qa else None}, '
                f'{error_log}\n{traceback.format_exc()}'
            )

            # 发送错误响应
            yield self._create_stream_response(
                StreamStatusType.FAILED,
                log=f"Error occurred while processing request: {error_log}"
            )

        finally:
            # 统一的清理逻辑
            if save_flag:
                await self._save(error=error_occurred, log=error_log)
            await self._destroy()

            # 发送最终状态
            if not error_occurred:
                yield self._create_stream_response(StreamStatusType.COMPLETED)
                logger.info("Successfully sent COMPLETED")

    def _step_log(self, cost_time, func, **kwargs):
        step_index = self.cache.get("step_index", 0) + 1
        self.cache["step_index"] = step_index
        log = f"-----> step{step_index}, cost {cost_time}ms, {func}"
        if kwargs:
            log += ", " + str(kwargs)
        logger.info(log)

    def _create_stream_response(self, status: StreamStatusType, session_id=None, qa_id=None, **kwargs) -> str:
        """创建流响应的辅助方法"""
        if session_id is None and self.session:
            session_id = self.session.id
        if qa_id is None and self.qa:
            qa_id = self.qa.id
        return StreamResponse(
            sessionId=session_id,
            qaId=qa_id,
            status=status,
            **kwargs
        ).model_dump_json(exclude={"save", "deliver"})

    @save_step(stream_type=StepType.QUERY_ANALYSIS)
    async def _analyz_query(self):
        async for event in self._yield_thinking_title(step="analyzing_query_start"):
            yield StreamResponse(
                type=StepType.TITLE,
                content=event
            )

        # 修改问句分析标题
        yield StreamResponse(
            sessionId=self.session.id,
            qaId=self.qa.id,
            status=StreamStatusType.PENDING,
            type=StepType.TITLE_CORRECTION,
            content=get_localized_message("analyzing_query_end", self.system_lang_code)
        )

    async def _yield_thinking_title(self, step, **kwargs):
        message = get_localized_message(step, self.system_lang_code, **kwargs)
        yield message

    def _build_coin_screener_data(self, raw_text: str, reply_language: str):
        """
        从 coin_screener 工具返回的 JSON 文本构建 recommend_crypto_table_data，
        写入 self.cache["recommend_crypto_table_data"]。
        skill-first 和 DAG 路径共用。
        """
        try:
            reply_language_code = ENGLISH_NAME_TO_CODE_MAP.get(reply_language, self.system_lang_code or "en")
            tools_data_list = json.loads(raw_text)
            if not isinstance(tools_data_list, list):
                tools_data_list = [tools_data_list]

            web_title_details = get_localized_message("recommend_crypto_table_web_title_details", reply_language_code)
            web_title_trade = get_localized_message("recommend_crypto_table_web_title_trade", reply_language_code)
            addWatchlist = get_localized_message("recommend_crypto_table_action_add_watchlist", reply_language_code)
            for tool_data in tools_data_list:
                tool_data["coinButtonName"] = web_title_details
                tool_data["tradeButtonName"] = web_title_trade
                tool_data["addWatchlist"] = addWatchlist

            self.cache.update({
                "recommend_crypto_table_data": {
                    "webTitle": [
                        get_localized_message("recommend_crypto_table_web_title_name", reply_language_code),
                        get_localized_message("recommend_crypto_table_web_title_price", reply_language_code),
                        get_localized_message("recommend_crypto_table_web_title_24_change", reply_language_code),
                        get_localized_message("recommend_crypto_table_web_title_24_volume", reply_language_code),
                        get_localized_message("recommend_crypto_table_web_title_action", reply_language_code),
                    ],
                    "appTitle": [
                        f"{get_localized_message('recommend_crypto_table_app_title_coin', reply_language_code)} / {get_localized_message('recommend_crypto_table_app_title_vol', reply_language_code)}",
                        get_localized_message("recommend_crypto_table_app_title_price", reply_language_code),
                        get_localized_message("recommend_crypto_table_web_title_24_change", reply_language_code),
                    ],
                    "data": tools_data_list,
                    "quickAddWatchlist":get_localized_message("recommend_crypto_table_action_add_watchlist_one_button", reply_language_code)
                }
            })
            logger.info(f"Built recommend_crypto_table_data with {len(tools_data_list)} items")
        except Exception as e:
            logger.error(f"Failed to build coin_screener table data: {e}")





    async def _build_earn_product_data(self, raw_text: str, reply_language: str):
        """
        从 recommend_financial_product 工具返回的 JSON 文本构建 recommend_earn_table_data，
        写入 self.cache["recommend_earn_table_data"]。
        """
        try:
            reply_language_code = ENGLISH_NAME_TO_CODE_MAP.get(reply_language, self.system_lang_code or "en")
            tools_data_list = json.loads(raw_text)
            if not isinstance(tools_data_list, list):
                tools_data_list = [tools_data_list]

        # 新增：如果返回值包含 markdown 字段，将其转为 json
            try:
                result_obj = tools_data_list[0] if tools_data_list and isinstance(tools_data_list[0], dict) else {}
                markdown_content = result_obj.get('markdown')
                if markdown_content:
                    schema_str = '{"number": int, "productType": string, "currency": string, "termDays": int, "annualReturnRate": string, "riskLevel": string, "investmentPercentage": string, "recommendationReason": string, "h5Url": string, "webUrl": string, "iconUrl": string}'
                    prompt = (
                        f"请将以下 markdown 表格内容转换为结构化 JSON 数据，严格按如下 schema 输出，所有 key 必须与 schema 完全一致（顺序、拼写、大小写），用英文逗号和双引号：\n"
                        f"schema: {schema_str}\n"
                        f"要求如下：\n"
                        f"1. 字段名（key）必须与 schema 完全一致，不允许增删或更改字段名；\n"
                        f"2. 涉及到文字内容的字段（如表格内容、描述、名称等）全部翻译成 {reply_language} 语言；\n"
                        f"3. 只输出 JSON，不要输出多余内容。\n"
                        f"表格内容如下：\n{markdown_content}"
                    )
                    try:
                        from llm.llm import llm
                        response = await llm.ainvoke(messages=[{"role": "user", "content": prompt}])
                        import json as _json
                        markdown_json = _json.loads(response.content)
                        logger.info(f"LLM parsed markdown table to json, items={len(markdown_json)}")
                    except Exception as llm_e:
                        logger.error(f"LLM parse markdown table to json failed: {llm_e}")
            except Exception as e:
                logger.error(f"Failed to parse markdown table to json: {e}")

            web_title_subscribe = get_localized_message("recommend_earn_table_web_title_subscribe", reply_language_code)
            for tool_data in tools_data_list:
                tool_data["subscribeButtonName"] = web_title_subscribe

            self.cache.update({
                "recommend_earn_table_data": {
                    "webTitle": [
                        get_localized_message("recommend_earn_table_web_title_currency", reply_language_code),
                        get_localized_message("recommend_earn_table_web_title_apy", reply_language_code),
                        get_localized_message("recommend_earn_table_web_title_term", reply_language_code),
                        get_localized_message("recommend_earn_table_web_title_redemption", reply_language_code),
                        get_localized_message("recommend_earn_table_web_title_action", reply_language_code),
                    ],
                    "appTitle": [
                        get_localized_message("recommend_earn_table_web_title_currency", reply_language_code),
                        get_localized_message("recommend_earn_table_web_title_apy", reply_language_code),
                        get_localized_message("recommend_earn_table_web_title_term", reply_language_code),
                    ],
                    "data": markdown_json
                }
            })
            logger.info(f"Built recommend_earn_table_data with {len(tools_data_list)} items")
        except Exception as e:
            logger.error(f"Failed to build earn product table data: {e}")

    def _append_card_ref(self, card_refs: list, tool_name: str, tool_call_id: str,
                         ref_type: str, tag_name: str, data: dict):
        """
        构建卡片/表格引用并追加到 card_refs 和 plan.resource_references。
        coin_screener / recharge_and_withdraw / recommend_financial_product 共用。
        """
        item = {
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "ref_type": ref_type,
            "tag_name": tag_name,
            "data": data,
        }
        card_refs.append(item)
        self.cache["plan"].resource_references.append(
            ResourceReference(
                eventId=tool_call_id,
                name=tool_name,
                type=ReferenceType(ref_type),
                style={},
                data=data,
            ).model_dump(mode="json")
        )

    def _build_recharge_withdraw_card_data_from_text(self, raw_text: str) -> dict:
        """
        从 recharge_and_withdraw 工具返回的 JSON 文本解析并返回单张卡片数据（不写 cache）。
        多卡片场景下每个 task 一份 data，供 DAG 按 eventId 绑定。
        接口返回 success:false 或无 paymentMethodList 时返回空 dict，不 mock 卡片数据。
        """
        try:
            tools_data_map = json.loads(raw_text)
            if not isinstance(tools_data_map, dict):
                return {}
            if tools_data_map.get("success") is False:
                return {}
            payment_method_list = tools_data_map.get("paymentMethodList", [])
            if not payment_method_list:
                return {}
            if len(payment_method_list) > 1:
                priority_order = ["FAST_SELL", "WITHDRAW", "OTC_SELL", "CRYPTO_WITHDRAW"]
                selected_method = None
                for priority_code in priority_order:
                    for method in payment_method_list:
                        if method.get("paymentMethodCode") == priority_code:
                            selected_method = method
                            break
                    if selected_method:
                        break
                if selected_method:
                    tools_data_map["paymentMethodList"] = [selected_method]
                else:
                    tools_data_map["paymentMethodList"] = [payment_method_list[0]]
            return tools_data_map
        except Exception as e:
            logger.error(f"Failed to build recharge_withdraw card data from text: {e}")
            return {}

    def _build_recharge_withdraw_data(self, raw_text: str):
        """
        从 recharge_and_withdraw 工具返回的 JSON 文本构建 recharge_withdraw_card_data，
        写入 self.cache["recharge_withdraw_card_data"]。
        skill-first 和单卡片 DAG 路径共用。
        """
        data = self._build_recharge_withdraw_card_data_from_text(raw_text)
        if data:
            self.cache.update({"recharge_withdraw_card_data": data})
            logger.info("Built recharge_withdraw_card_data")

    async def _create_client(self):
        from llm.base import create_llm
        self.llm, self.model_name = create_llm()
        logger.info(
            "[LLM] client ready: model=%s base_url=%s",
            self.model_name,
            getattr(self.llm, "base_url", ""),
        )
        return self.llm