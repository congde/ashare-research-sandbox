import json
import uuid
import time
import logging
from enum import StrEnum
from typing import Optional, Any, List, Dict, Union
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store
from web.exceptions import HttpException
from web import code_msg
from libs.wrapper import usage_time
from web.context import context
from libs.language import get_localized_message
logger = logging.getLogger(__name__)


def _coll(name: str):
    return get_context_store().get_collection(name)


def get_uuid():
    return uuid.uuid4().hex


def get_timestamp():
    return int(time.time())


class AgentType(StrEnum):
    AUTO = "AUTO"                        # 动态编排（自动路由）
    QUICK_REASONING = "QUICK_REASONING"  # 快速推理
    DEEP_THINK = "DEEP_THINK"            # 深度思考
    DEEP_RESEARCH = "DEEP_RESEARCH"      # 深度研究
    EVENT_DELIVERY = "EVENT_DELIVERY"    # 事件触达
    CUSTOMER_SERVICE = "CUSTOMER_SERVICE"  # 客服

    currency_insights = "currency_insights"  # 币种洞察


class FileType(StrEnum):
    IMAGE = "IMAGE"
    DOCUMENT = "DOCUMENT"
    PDF = "PDF"
    EXCEL = "EXCEL"
    VIDEO = "VIDEO"
    OTHER = "OTHER"
 

class UploadedFile(BaseModel):
    url: str = Field(description="文件访问URL")
    fileType: FileType = Field(FileType.OTHER, description="文件类型")
    fileName: Optional[str] = Field(None, description="原始文件名")
    fileSize: Optional[int] = Field(None, description="文件大小(字节)")


class FeedbackType(StrEnum):
    NONE = ""
    GOOD = "GOOD"   # 点赞
    BAD = "BAD"     # 点踩


class Feedback(BaseModel):
    type: FeedbackType = Field(FeedbackType.NONE, description="反馈类型")
    tagId: Optional[List[str]] = Field(None, description="点踩标签（需后端静态翻译）")
    description: str = Field("", description="点踩原因")


class ReferenceType(StrEnum):
    URL = "URL"
    CUSTOM_TABLE = "CUSTOM_TABLE"
    MARKDOWN_TABLE = "MARKDOWN_TABLE"
    CUSTOM_CARD = "CUSTOM_CARD"


class ResourceReference(BaseModel):
    eventId: str = Field(..., description="资源ID")
    name: str = Field(..., description="资源名称，默认为工具名称")
    type: ReferenceType = Field(..., description="资源类型")
    style: dict = Field({}, description="资源渲染样式，具体信息由前端提供")
    data: Any = Field(..., description="资源数据，任意数据类型")
    description: str = Field("", description="资源描述")


class StepType(StrEnum):
    # 一级step，对应mongo的answer.type
    SYSTEM = "SYSTEM"                                             # 系统
    QUERY_ANALYSIS = "QUERY_ANALYSIS"                             # 问句分析
    TOOL_EXECUTION = "TOOL_EXECUTION"                             # 工具调用
    DEEP_THINK = "DEEP_THINK"                                     # 深度思考
    RESOURCE_REFERENCE = "RESOURCE_REFERENCE"                     # 资源引用
    ANSWER_RESPONSE = "ANSWER_RESPONSE"                           # 回复答案
    CITATIONS = "CITATIONS"                                       # 引用
    CURRENCY_FOLLOWUP_SUGGESTIONS = "CURRENCY_FOLLOWUP_SUGGESTIONS"# 币种推荐
    QUERY_FOLLOWUP_SUGGESTIONS = "QUERY_FOLLOWUP_SUGGESTIONS"     # 问句推荐
    QUERY_CLARIFY = "QUERY_CLARIFY"                               # 问句澄清
    RESEARCH_DECOMPOSITION = "RESEARCH_DECOMPOSITION"             # 深度研究子课题拆解
    PROGRESS = "PROGRESS"                                         # 深度研究的一级子课题
    REPORT = "REPORT"                                             # 深度研究的报告
    CUSTOMER_SERVICE_RESPONSE = "CUSTOMER_SERVICE_RESPONSE"       # 客服消息回复

    # 二级step，对应mongo的answer.step
    TITLE = "TITLE"                                 # 标题
    CONTENT = "CONTENT"                             # 内容
    TITLE_CORRECTION = "TITLE_CORRECTION"           # 标题修正
    CONTENT_CORRECTION = "CONTENT_CORRECTION"       # 内容修正
    TOOL_RESULT = "TOOL_RESULT"                     # 工具调用结果

    @classmethod
    def from_string(cls, name: str):
        """通过字符串名称获取枚举值"""
        try:
            return getattr(cls, name)
        except AttributeError:
            raise ValueError(f"'{name}' is not a valid {cls.__name__}")

    @classmethod
    def from_value(cls, value: str):
        """通过字符串值获取枚举值"""
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"'{value}' is not a valid {cls.__name__} value")


class StepStatusType(StrEnum):
    """该状态表示数据的保存状态"""
    PENDING = "PENDING"         # 执行中
    CANCELED = "CANCELED"       # 任务取消（客户端主动取消/网络中断）
    SUCCEEDED = "SUCCEEDED"     # 执行成功
    FAILED = "FAILED"           # 执行失败
    BLOCKED_QUERY = "BLOCKED_QUERY"         # query已被风控
    BLOCKED_ANSWER = "BLOCKED_ANSWER"       # answer已被风控


class SessionStatusType(StrEnum):
    PENDING = "PENDING"         # 对话中
    COMPLETED = "COMPLETED"     # 已完成


class SourceType(StrEnum):
    RECOMMEND_BEFORE_QUESTION = "RECOMMEND_BEFORE_QUESTION"     # 推荐前问句
    RECOMMEND_AFTER_QUESTION = "RECOMMEND_AFTER_QUESTION"       # 推荐后问句
    STRESS_TEST = "STRESS_TEST"                                 # 压测
    PRE_RELEASE_ACCEPTANCE = "PRE_RELEASE_ACCEPTANCE"           # 预发验收
    EFFECT_EVALUATION = "EFFECT_EVALUATION"                     # 效果评估
    OTHER = "OTHER"                                             # 其它，如：接口连通性观测

    # 第三方业务身份来源
    SEARCH_SOPT_ANALYZE = "SEARCH_SOPT_ANALYZE"                 # 搜索
    ASSERT_PNL_ANALYZE = "ASSERT_PNL_ANALYZE"                   # 资产
    NEWS_DETAIL_ANALYZE = "NEWS_DETAIL_ANALYZE"                 # 新闻总结
    KLINE_FLUCTUATION_ANALYZE = "KLINE_FLUCTUATION_ANALYZE"     # K线异动
    TRENDS_ABNORMAL_ANALYZE = "TRENDS_ABNORMAL_ANALYZE"         # 行情异动
    MARKET_FUTURE_ANALYZE = "MARKET_FUTURE_ANALYZE"             # 合约行情
    INSIGHT_FUTURE_ANALYZE = "INSIGHT_FUTURE_ANALYZE"           # 币种洞察-合约
    INSIGHT_SOPT_ANALYZE = "INSIGHT_SOPT_ANALYZE"               # 币种洞察-现货
    CURRENCY_SELECTION_RECOMMEND = "CURRENCY_SELECTION_RECOMMEND"   # 首页-币种自选

class StepModel(BaseModel):
    type: StepType = Field(StepType.QUERY_ANALYSIS, description="类型")
    step: Optional[Dict[StepType, Any]] = Field(default_factory=dict, description="step详细内容")
    elapsedMs: int = Field(0, description="该阶段耗时（单位：毫秒）")
    status: StepStatusType = Field(StepStatusType.PENDING, description="该阶段状态")
    log: str = Field("", description="该阶段相关的日志记录")
    extraInfo: dict = Field({}, description="其它信息，如：LLM的Token消耗等")


class HistoryStepType(StrEnum):
    """短期记忆里存储的Step类型"""
    TOOL_DECIDE = "TOOL_DECIDE"                                   # 工具决策
    ANSWER_RESPONSE = "ANSWER_RESPONSE"                           # 回复答案
    QUERY_FOLLOWUP_SUGGESTIONS = "QUERY_FOLLOWUP_SUGGESTIONS"     # 问句推荐
    QUERY_CLARIFY = "QUERY_CLARIFY"                               # 问句澄清


class MemoryModel(BaseModel):
    """
    记忆表：kia_memory
    """
    id: str = Field(default_factory=get_uuid, min_length=32, max_length=32, description="ID")
    qaId: str = Field(min_length=32, max_length=32, description="问答ID")
    memory: str = Field("", description="长期记忆")
    history: Dict[HistoryStepType, List[dict]] = Field({}, description="短期记忆")
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="创建时间（TTL， 默认30天）")

    async def save(self):
        try:
            data = self.model_dump(mode="json")
            data["createdAt"] = self.createdAt
            await _coll("kia_memory").add_or_update_one(
                matcher={"id": self.id},
                data=data
            )
        except Exception as e:
            logger.exception(f"Save memory error: {e}")


class QAModel(BaseModel):
    """
    QA问答表：kia_qa

    索引：
        userId_1、sessionId_1、createTime_-1
    """
    id: str = Field(default_factory=get_uuid, min_length=32, max_length=32, description="ID")
    parentId: Optional[str] = Field(None, min_length=32, max_length=32, description="父级ID")
    userId: str = Field(description="用户ID")
    sessionId: str = Field(default_factory=get_uuid, min_length=32, max_length=32, description="会话ID")
    sortIndex: int = Field(1, description="Session里的QA对顺序")
    agentType: AgentType = Field(AgentType.QUICK_REASONING, description="Agent模式")
    query: str = Field(description="问句")
    answer: List[StepModel] = Field([], description="不同阶段的答案（前端遍历该List按顺序渲染，根据type识别身份）")
    uploadedFile: List[UploadedFile] = Field([], description="上传文件信息")
    feedback: Feedback = Field(default_factory=Feedback, description="反馈信息")
    elapsedMs: int = Field(0, description="该QA所产生的总耗时（毫秒）")
    isHistory: bool = Field(True, description="对话断开前端兜底策略")
    isDeleted: bool = Field(False, description="是否删除")
    createTime: int = Field(default_factory=get_timestamp, description="创建时间")
    updateTime: int = Field(default_factory=get_timestamp, description="更新时间（删除、添加反馈）")
    offset: int = Field(0, description="断点续传偏移量（为了获取history接口数据时从该偏移量位置开始读取Redis队列里的数据）")
    source: Optional[SourceType] = Field(None, description="路径来源")
    resourceReference: List[ResourceReference] = Field([], description="资源引用")

    async def cancel(self):
        """处理用户主动取消逻辑"""
        cancel_log = "The user voluntarily cancelled the conversation."
        try:
            qa = await self.get(self.id)
        except Exception as e:
            logging.exception(f"get qa error: {e}")
            return
        if not qa.answer:
            qa.answer.append(StepModel(type=StepType.SYSTEM, status=StepStatusType.CANCELED, log=cancel_log))
            qa.updateTime = get_timestamp()
            await _coll("kia_qa").add_or_update_one(
                matcher={"id": self.id},
                data=qa.model_dump(mode="json")
            )
            return
        if qa.answer[-1].type == StepType.SYSTEM:
            qa.answer[-1].status = StepStatusType.CANCELED
            qa.answer[-1].log = cancel_log
        else:
            qa.answer.append(StepModel(type=StepType.SYSTEM, status=StepStatusType.CANCELED, log=cancel_log))

        qa.updateTime = get_timestamp()
        await _coll("kia_qa").add_or_update_one(
            matcher={"id": self.id},
            data=qa.model_dump(mode="json")
        )

    async def save(self, check_canceled=True, force_failed=False, status: StepStatusType = None, log: str = None):
        """优化后的保存方法，逻辑更简洁清晰"""
        if context.get("is_cancelled", False):
            return
        
        # 保存记忆
        kia_memory = context.get("kia_memory")
        if kia_memory and isinstance(kia_memory, MemoryModel):
            await kia_memory.save()

        # 分离SYSTEM和非SYSTEM步骤，确保SYSTEM类型在最后
        valid_steps = [step for step in self.answer if step is not None]
        non_system_steps = [step for step in valid_steps if step.type != StepType.SYSTEM]
        system_steps = [step for step in valid_steps if step.type == StepType.SYSTEM]

        # 重组answer，保持SYSTEM在最后
        self.answer = non_system_steps
        if system_steps:
            self.answer.append(system_steps[-1])

        if len(self.answer) >= 2:
            # 检查倒数第二个元素状态，如果为PENDING则修改SYSTEM状态为FAILED
            if self.answer[-2].status == StepStatusType.PENDING and self.answer[-1].type == StepType.SYSTEM and self.answer[-1].status != StepStatusType.BLOCKED_ANSWER:
                logger.warning('The status of the second-to-last element in the current answer is pending')
                self.answer[-1].status = StepStatusType.FAILED
                self.answer[-1].log = code_msg.get_msg(code_msg.CODE_NETWORK_ERROR)

        if force_failed and self.answer and self.answer[-1].status != StepStatusType.BLOCKED_ANSWER:
            logger.warning('force_failed=True')
            self.answer[-1].status = status or StepStatusType.FAILED
            self.answer[-1].log = log or code_msg.get_msg(code_msg.CODE_NETWORK_ERROR)

        # 处理取消状态
        if check_canceled:
            try:
                qa = await self.get(self.id)
                if qa and qa.answer and qa.answer[-1].status == StepStatusType.CANCELED:
                    if self.answer and self.answer[-1].type == StepType.SYSTEM:
                        self.answer[-1].status = StepStatusType.CANCELED
                        if len(self.answer) > 1:
                            self.answer[-2].status = StepStatusType.CANCELED
            except Exception:
                logger.debug("Failed to check cancel status during QA save", exc_info=True)

        self.offset = context.get("offset", 0)
        self.updateTime = get_timestamp()
        await _coll("kia_qa").add_or_update_one(
            matcher={"id": self.id},
            data=self.model_dump(mode="json")
        )

    @staticmethod
    async def get(id):
        doc = await _coll("kia_qa").get(
            matcher={"id": id},
            hidden_names=["_id"],
        )
        if not doc:
            raise HttpException(code=code_msg.CODE_QA_ID_NOT_FOUND)
        return QAModel(**doc)

    @staticmethod
    async def get_latest(id: str):
        doc = await _coll("kia_qa").get(
            matcher={"id": id},
            hidden_names=["_id"],
        )
        if not doc:
            raise ValueError(f"QA not found, id={id}")
        return QAModel(**doc)

    @usage_time
    @staticmethod
    async def get_history(session_id: str, user_id: str, top_k=20) -> list:
        docs = await _coll("kia_qa").query(
            matcher={"sessionId": session_id, "userId": user_id},
            sort=[("createTime", -1)],
            page=1,
            page_size=top_k,
            hidden_names=["_id"],
        )
        if not docs:
            return []
        blocked = StepStatusType.BLOCKED_ANSWER.value
        docs = [
            doc for doc in docs
            if not any(
                step.get("status") == blocked
                for step in (doc.get("answer") or [])
                if isinstance(step, dict)
            )
        ]
        return [QAModel(**doc) for doc in docs]


class SessionModel(BaseModel):
    """
    Session会话表：kia_sessions
    """
    id: Optional[str] = Field(None, min_length=32, max_length=32, description="ID")
    parentId: Optional[str] = Field(None, min_length=32, max_length=32, description="父级ID")
    userId: Optional[str] = Field(None, description="用户ID")
    latestQaId: Optional[str] = Field(None, description="最新对话ID")
    title: Optional[str] = Field(None, description="侧边栏会话标题（首次QA需更新title）")
    summary: str = Field("", description="当前session摘要")
    status: SessionStatusType = Field(SessionStatusType.PENDING, description="多轮对话状态")
    isDeleted: bool = Field(False, description="是否删除")
    createTime: int = Field(default_factory=get_timestamp, description="创建时间")
    updateTime: int = Field(default_factory=get_timestamp, description="更新时间（删除、对title重命名）")

    # --- Context management (compaction state) ---
    compactionCursor: Optional[str] = Field(None, description="Transcript event ID up to which compaction has run")
    turnCount: int = Field(0, description="Total conversation turns in this session")
    contextTokensEstimate: int = Field(0, description="Estimated tokens in current context window")
    lastSummaryId: Optional[str] = Field(None, description="ID of the latest compaction summary event")
    branchIds: List[str] = Field(default_factory=list, description="Active branch IDs for fork/merge tracking")

    async def create(self):
        if self.id is None:
            self.id = get_uuid()
            return await self.save()
        return await self.load()

    async def save(self):
        self.updateTime = get_timestamp()
        session = self.model_dump(mode="json")
        return await _coll("kia_sessions").add_or_update_one(
            matcher={"id": self.id},
            data=session,
        )

    async def load(self, session=None):
        if session is None:
            session = await SessionModel.get(session_id=self.id)
        if session is None:
            raise HttpException(code=code_msg.CODE_SESSION_ID_NOT_FOUND)
        latest_qa_id = session.get("latestQaId")
        if not latest_qa_id:
            docs = await SessionModel.query(session_id=self.id)
            if docs:
                session["latestQaId"] = docs[0].get("id")
                await _coll("kia_sessions").add_or_update_one_by_id(data=session)

        for k, v in session.items():
            if not hasattr(self, k):
                continue
            setattr(self, k, v)
        return self

    @classmethod
    async def get(cls, session_id: str, is_delete: Optional[bool] = False, user_id: str = None):
        matcher = {"id": session_id}
        if is_delete is not None:
            matcher["isDeleted"] = is_delete
        if user_id is not None:
            matcher["userId"] = user_id

        return await _coll("kia_sessions").get(
            matcher=matcher,
            hidden_names=["_id"]
        )
    
    @classmethod
    async def exists(cls, session_id: str) -> bool:
        return bool(await SessionModel.get(session_id))
    
    @classmethod
    async def query(cls, session_id: str, sort=[("createTime", -1)]):
        return await _coll("kia_qa").query(
            matcher={"sessionId": session_id},
            hidden_names=["_id"],
            sort=sort
        )

    async def cancel(self):
        session = await SessionModel.get(session_id=self.id)
        if not session:
            return
        session.update({
            "status": SessionStatusType.COMPLETED.value,
            "updateTime": get_timestamp()
        })
        await _coll("kia_sessions").add_or_update_one_by_id(data=session)


class UserConfigModel(BaseModel):

    @staticmethod
    async def get_user_config(user_id: str) -> dict:
        return await _coll("user_config").get(matcher={"user_id": user_id}) or {}


class StreamStatusType(StrEnum):
    """该状态只给会话的流式输出使用，注意和StepStatusType的区分，不是同一回事"""
    PENDING = "PENDING"         # 执行中
    FAILED = "FAILED"           # 执行失败
    START = "START"             # step开始
    END = "END"                 # step结束
    COMPLETED = "COMPLETED"     # 任务完成，表示当前对话结束
    BLOCKED_QUERY = "BLOCKED_QUERY"         # query已被风控
    BLOCKED_ANSWER = "BLOCKED_ANSWER"       # answer已被风控


class StreamResponse(BaseModel):
    sessionId: Optional[str] = Field(None, min_length=32, max_length=32, description="会话ID")
    qaId: Optional[str] = Field(None, min_length=32, max_length=32, description="对话ID")
    type: StepType = Field(StepType.SYSTEM, description="类型（前端页面渲染解析该字段）")
    content: Any = Field(None, description="流式返回的内容")
    status: StreamStatusType = Field(StreamStatusType.PENDING, description="状态")
    log: str = Field("", description="该阶段相关的日志记录")
    save: bool = Field(True, description="是否保存到DB")
    deliver: bool = Field(True, description="是否发送给客户端用户")
    offset: int = Field(0, description="偏移量")
    checkSensitive: bool = Field(True, description="是否检查敏感词")


class OutputSchema(BaseModel):
    event_object: StreamResponse
    event_str: str


def output_schema(event: Union[str, StreamResponse]):
    if isinstance(event, str):
        event = StreamResponse(**json.loads(event))
    offset = context.get("offset", 0)
    event.offset = offset
    event_str  = event.model_dump_json(exclude={"save", "deliver", "checkSensitive"})
    return OutputSchema(event_object=event, event_str=event_str)


async def response_event(
    type: StepType,
    content: str,
    session_id: str,
    qa_id: str,
    system_lang_code: str,
    qa: QAModel,
):
    title = get_localized_message("generating_answer_start", system_lang_code)
    title_correction = get_localized_message("generating_answer_end", system_lang_code)
    yield StreamResponse(
        sessionId=session_id, qaId=qa_id,
        status=StreamStatusType.START, type=type
    ).model_dump_json(exclude={"save", "deliver"})
    yield StreamResponse(
        sessionId=session_id, qaId=qa_id, status=StreamStatusType.PENDING,
        type=StepType.TITLE, content=title
    ).model_dump_json(
        exclude={"save", "deliver"})

    yield StreamResponse(
        sessionId=session_id, qaId=qa_id, status=StreamStatusType.PENDING,
        type=StepType.CONTENT, content=content, checkSensitive=False
    ).model_dump_json(exclude={"save", "deliver"})

    yield StreamResponse(
        sessionId=session_id, qaId=qa_id, status=StreamStatusType.PENDING,
        type=StepType.TITLE_CORRECTION, content=title_correction
    ).model_dump_json(exclude={"save", "deliver"})
    yield StreamResponse(
        sessionId=session_id, qaId=qa_id,
        status=StreamStatusType.END, type=type
    ).model_dump_json(exclude={"save", "deliver"})

    qa.answer.append(
        StepModel(
            type=type,
            step={
                StepType.TITLE: title,
                StepType.CONTENT: content,
                StepType.TITLE_CORRECTION: title_correction
            },
            status=StepStatusType.SUCCEEDED,
        )
    )
    await qa.save()


if __name__ == "__main__":
    from pprint import pprint
    from collections import OrderedDict
    session_id = get_uuid()
    print(session_id)
    session = SessionModel(id=session_id, userId="123")
    print(session.id)

    model = QAModel(query="你好，如何实现月入100w", sessionId=session.id, userId=session.userId)
    step = StepModel(type=StepType.QUERY_ANALYSIS, step=OrderedDict())
    model.answer.append(StepModel(type=StepType.QUERY_ANALYSIS, step=OrderedDict([(StepType.TITLE, "正在分析问句中..."), (StepType.CONTENT, "xxxx")])))
    model.answer.append(StepModel(type=StepType.TOOL_EXECUTION, step=OrderedDict([(StepType.TITLE, "正在调用`联网搜索`工具..."), (StepType.CONTENT, "xxxx")])))
    print()
    # pprint(session.model_dump(mode="json"))
    print()
    pprint(model.model_dump(mode="json"))
    pprint(session.model_dump(mode="json"))
    print()
