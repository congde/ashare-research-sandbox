# -*- coding: utf-8 -*-
'''
@Time    :   2025/09/19 14:33:06
'''
import os
import json
import time
import logging
import asyncio
from typing import Optional
from pydantic import BaseModel, Field

from libs.wrapper import usage_time
from libs.llm_shield_sdk.llm_shield_sdk_v2 import (
    ModerateV2Response,
    ModerateV2Request,
    MessageV2,
    ContentTypeV2,
    ClientV2,
    ModerateV2StreamSession,
)
from llm.shield.translate import translate
from web.exceptions import RiskException
from web import code_msg
from llm.shield.async_sdk import AsyncClient
from web.exceptions import HttpException
from agent.schema import StreamStatusType

logger = logging.getLogger(__name__)


# Mock数据 - 风险响应（包含风险）
MOCK_RISK_RESPONSE = {
    "ResponseMetadata": {
        "Error": {
            "Code": "",
            "Message": ""
        },
        "RequestId": "021754648722246000000000000000000000000000000001fb210"
    },
    "Result": {
        "MsgID": "889cab7ac60b4f7b95e365f0441a****",
        "RiskInfo": {
            "Risks": [
                {
                    "Category": "104",
                    "Label": "10400000",
                    "Prob": 0.9997127652168274,
                    "Matches": []
                },
                {
                    "Category": "104",
                    "Label": "10401004",
                    "Prob": 0.9989,
                    "Matches": []
                }
            ]
        },
        "Decision": {
            "DecisionType": 3,  # MARK类型
            "DecisionDetail": {
                "BlockDetail": None,
                "ReplaceDetail": {
                    "Replacement": None
                }
            },
            "DecisionStrategyID": None,
            "HitStrategyIDs": [
                "rule-d1megdqe4cpb9ef3****"
            ]
        },
        "PermitInfo": {
            "Permits": []
        }
    }
}

# Mock数据 - 无风险响应（通过）
MOCK_PASS_RESPONSE = {
    "ResponseMetadata": {
        "Error": {
            "Code": "",
            "Message": ""
        },
        "RequestId": "021754649841466000000000000000000000000000000006baf05"
    },
    "Result": {
        "MsgID": "9f26809920fd4bfd86416914b4663488",
        "RiskInfo": {
            "Risks": []
        },
        "Decision": {
            "DecisionType": 1,  # PASS
            "DecisionDetail": {
                "BlockDetail": None,
                "ReplaceDetail": {
                    "Replacement": None
                }
            },
            "DecisionStrategyID": None,
            "HitStrategyIDs": []
        },
        "PermitInfo": {
            "Permits": []
        },
        "Degraded": False,
        "DegradeReason": ""
    }
}

# Mock数据 - 流式最终响应（包含风险）
MOCK_STREAM_FINAL_RESPONSE = {
    "ResponseMetadata": {
        "Error": {
            "Code": "",
            "Message": ""
        },
        "RequestId": "021754649841466000000000000000000000000000000006baf05"
    },
    "Result": {
        "MsgID": "9f26809920fd4bfd86416914b4663488",
        "RiskInfo": {
            "Risks": [
                {
                    "Category": "104",
                    "Label": "10400000",
                    "Prob": 0.95,
                    "Matches": []
                }
            ]
        },
        "Decision": {
            "DecisionType": 3,  # MARK类型
            "DecisionDetail": {
                "BlockDetail": None,
                "ReplaceDetail": {
                    "Replacement": None
                }
            },
            "DecisionStrategyID": None,
            "HitStrategyIDs": []
        },
        "PermitInfo": {
            "Permits": []
        },
        "Degraded": False,
        "DegradeReason": ""
    }
}


_LABEL_MAP = {
    0: "违规",  # 默认兜底文案

    10107000: "敏感问题", # 涉敏 1 
    10102000: "敏感问题", # 涉敏 2 
    10116000: "敏感问题", # 其他敏感内容 
    10600000: "敏感问题", # 通用话题控制 
    10602017: "敏感问题",  # 竞品比较
    
    10104000: "色情低俗", # 色情低俗 
    10112000: "歧视", # 歧视 
    10109000: "商业违法", # 商业违法 
    10113004: "欺诈",  # 诈骗
    10602014: "欺诈",  # 保险欺诈
    10113003: "赌博", # 赌博 
    10113002: "毒品", # 毒品 
    10103005: "谩骂", # 谩骂 

    10302000: "隐私数据", # 银行卡号 
    10304000: "隐私数据", # 身份证号 
    10310000: "隐私数据", # 电子邮箱 
    10313000: "隐私数据", # 电话号码 
    10322000: "隐私数据", # 其他隐私数据 
    10602012: "隐私数据",  # 个人财务隐私 
    10602009: "隐私数据",  # 非公开信息泄漏或索取

    10400000: "恶意攻击", # 提示词攻击默认标签 
    10401001: "恶意攻击", # 角色扮演 
    10401002: "恶意攻击", # 权限提升 
    10401003: "恶意攻击", # 对抗前后缀 
    10401004: "恶意攻击", # 目标劫持 
    10401005: "恶意攻击", # 混淆和编码 
    10401008: "恶意攻击", # 少量示例攻击 
    10402003: "恶意攻击", # 窃取提示词 
    10701001: "恶意攻击",  # 高频相似样本

    10602001: "非法金融活动",  # 违规荐股
    10602002: "非法金融活动",  # 交易建议
    10602003: "非法金融活动",  # 预测行情与交易判断
    10602004: "非法金融活动",  # 承诺收益与模拟收益
    10602005: "非法金融活动",  # 适当性不匹配绕过
    10602006: "非法金融活动",  # 诱导性与规避合规
    10602007: "非法金融活动",  # 表达或转述不合规观点
    10602008: "非法金融活动",  # 代客理财
    10602010: "非法金融活动",  # 越权调用或疑似假冒客户信息
    10602011: "非法金融活动",  # 非法金融活动
    10602013: "非法金融活动",  # 税务规避
    10602015: "非法金融活动",  # 征信操作
    10602016: "非法金融活动",  # 外汇管制规避
}

category_key_map = {
    "敏感问题": "a89e495ae4f84000a024",
    "色情低俗": "29b9ab587cfb4800a11b",
    "歧视": "ba082776215d4000a181",
    "商业违法": "a11fd66b95204000aecf",
    "诈骗": "3ddc6fda272e4000a1fd",
    "赌博": "d53f88c6bb0c4800ab93",
    "毒品": "d890dbc847024800a49a",
    "谩骂": "cbf7c6663c244800ae15",
    "隐私数据": "cfb5936588d34000a12b",
    "恶意攻击": "80d726ae416f4000afd0",
    "欺诈": "ed0d8e4178894800a531",
    "非法金融活动": "8925247071d74800aa47",
    "违规": "291dfb6720224000a177"
}


local_category_map = {
    "child_exploitation": "敏感问题",  # 儿童剥削
    "drugs": "毒品",                   # 毒品
    "fraud": "欺诈",                   # 欺诈
    "gambling": "赌博",                # 赌博
    "harassment": "恶意攻击",          # 骚扰
    "hate_speech": "歧视",             # 仇恨言论
    "illegal": "商业违法",             # 非法活动
    "misinformation": "敏感问题",      # 虚假信息
    "political": "敏感问题",           # 政治敏感
    "politics": "敏感问题",            # 政治敏感
    "porn": "色情低俗",                # 色情内容
    "pornography": "色情低俗",         # 色情内容
    "privacy": "隐私数据",             # 隐私泄露
    "profanity": "谩骂",               # 谩骂辱骂
    "prostitution": "商业违法",        # 卖淫
    "self_harm": "敏感问题",           # 自伤自杀
    "terrorism": "敏感问题",           # 恐怖主义
    "violence": "敏感问题",            # 暴力内容
    "weapons": "商业违法",             # 武器
    "sensitive": "敏感问题",           # 默认兜底
}


class RiskResult(BaseModel):
    has_risk: bool = False
    risk_category: Optional[str] = None
    fallback_message: Optional[str] = None
    decision_type: Optional[str] = None
    should_terminate: bool = False  # 是否应该立即终止流


class LLMShield(object):
    """
    DecisionType: 1=PASS, 2=BLOCK, 3=MARK, 4=REPLACE, 5=OPTIMIZE
      1: "", # 通过，表示检测内容未命中任何防护策略，直接放行
      2: "", # 拦截，表示检测内容命中了防护策略且被拦截
      3: "", # 观察，表示检测内容命中了防护策略，但被放行
      4: "", # 脱敏，表示检测内容命中了敏感信息防护策略，
      5: "", # 安全代答，表示检测内容命中了防护策略，您可以根据MsgID，调用查询大模型应用防火墙代答内容接口查询代答结果
    """
    _I18N_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "conf/i18n/llm_shield")

    # 敏感词兜底
    _sensitive_word_filter = None

    def __init__(
        self,
        url: str = None,
        api_key: str = None,
        app_id: str = None,
        timeout: Optional[float] = None,
        max_connections: int = 100,
        keepalive_expiry: int = 30,
    ):
        if url is None:
            url = os.environ.get("RISK_URL")
        if api_key is None:
            api_key = os.environ.get("RISK_API_KEY")
        if app_id is None:
            app_id = os.environ.get("RISK_APP_ID")
        if timeout is None:
            timeout = float(os.environ.get("RISK_TIMEOUT", 30))
        _max_connections = os.environ.get("RISK_MAX_CONNECTIONS")
        if _max_connections is not None:
            max_connections = int(_max_connections)
        _keepalive_expiry = os.environ.get("RISK_KEEPALIVE_EXPIRY")
        if _keepalive_expiry is not None:
            keepalive_expiry = int(_keepalive_expiry)

        self._url = url
        self._api_key = api_key
        self._app_id = app_id
        self._chunk_size = 100

        self._client = AsyncClient(
            url,
            api_key,
            timeout,
            max_connections=max_connections,
            keepalive_expiry=keepalive_expiry
        )

        logger.info("LLMShield initialized with AsyncClient")

    async def close(self):
        try:
            await self._client.http_client.aclose()
        except Exception:
            pass

    async def init(self):
        max_keepalive_connections = min(self._client.http_client._transport._pool._max_keepalive_connections, 10)
        for _ in range(max_keepalive_connections):
            result = await self.check("Hello World", "en")
        logger.info(f"LLMShield initialized with result: {result}")

    @classmethod
    def _init_sensitive_word_filter(cls):
        """初始化敏感词过滤器"""
        try:
            from llm.shield.sensitive_word_filter import get_global_filter

            cls._sensitive_word_filter = get_global_filter(logger=logger)
            stats = cls._sensitive_word_filter.get_stats()

            logger.info(
                f"AC Automaton Sensitive Word Filter initialized successfully: "
                f"{stats['total_words']} words, {stats['total_variants']} variants, "
                f"{stats['categories']} categories"
            )
        except Exception as e:
            logger.exception(f"Failed to initialize sensitive word filter: {e}")

    @classmethod
    def _get_primary_category(cls, matched_words: list) -> str:
        if not matched_words:
            return "sensitive"

        # 按严重级别定义优先级
        priority_map = {
            "violence": 1,          # 暴力
            "pornography": 2,       # 性内容
            "drugs": 3,             # 毒品
            "gambling": 4,          # 赌博
            "harassment": 5,        # 谩骂
            "sensitive": 6          # 敏感
        }

        # 从匹配词中提取分类，选择最高优先级的
        categories = [w.category for w in matched_words]
        primary = min(categories, key=lambda c: priority_map.get(c, 999))
        return primary

    @classmethod
    def _local_sensitive_check(cls, content: str, system_lang_code: str, threshold: int = 1) -> RiskResult:
        """
        Local sensitive word detection with threshold control

        Args:
            content: Content to be checked
            system_lang_code: 系统语言代码
            threshold: Severity level threshold (1=critical, 2=high, 3=medium, 4=low)
                      1: Block critical and above
                      2: Block high and above
                      3: Block medium and above
                      4: Block all including low

        Returns:
            RiskResult: Risk check result
        """
        start_time = time.time()

        if not content:
            return RiskResult(
                has_risk=False,
                decision_type="1",
                should_terminate=False
            )

        if cls._sensitive_word_filter is None:
            logger.warning("Sensitive word filter not initialized, skipping local check")
            return RiskResult(
                has_risk=False,
                decision_type="1",
                should_terminate=False
            )

        try:
            filter_result = cls._sensitive_word_filter.check(content)
            check_time = int((time.time() - start_time) * 1000)

            # Define severity level priority map
            severity_score_map = {
                "critical": 1,
                "high": 2,
                "medium": 3,
                "low": 4
            }

            # Check if content should be blocked based on threshold
            should_block = False
            highest_match_severity = None

            if filter_result.matched_words:
                # Find the highest severity matched word
                highest_score = float('inf')
                for match in filter_result.matched_words:
                    score = severity_score_map.get(match.severity, 5)
                    if score < highest_score:
                        highest_score = score
                        highest_match_severity = match.severity

                # Block if highest severity score is less than or equal to threshold
                should_block = highest_score <= threshold

            if filter_result.is_blocked and should_block:
                # Extract matched word information
                matched_words_str = ", ".join([
                    f"{m.word}({m.category},{m.severity})"
                    for m in filter_result.matched_words[:5]
                ])

                logger.warning(
                    f"Local sensitive word detection blocked: "
                    f"words={matched_words_str}, "
                    f"threshold={threshold}, "
                    f"highest_severity={highest_match_severity}, "
                    f"categories={list(filter_result.categories)}, "
                    f"match_count={len(filter_result.matched_words)}, "
                    f"scan_time={check_time}ms, "
                    f"content_preview={content[:50]}"
                )

                primary_category = cls._get_primary_category(filter_result.matched_words)
                cn_category = local_category_map.get(primary_category, "敏感问题")

                msg = translate(system_lang_code, "21109315dbba4000a894", cls._I18N_PATH)
                category = translate(system_lang_code, category_key_map.get(cn_category), cls._I18N_PATH)
                if category == "敏感问题":
                    category = "敏感"
                fallback_message = msg.format(category=category)

                return RiskResult(
                    has_risk=True,
                    risk_category=cn_category,
                    fallback_message=fallback_message,
                    decision_type="2",
                    should_terminate=True
                )

            if filter_result.matched_words and not should_block:
                logger.info(
                    f"Local sensitive word detected but below threshold: "
                    f"highest_severity={highest_match_severity}, "
                    f"threshold={threshold}, "
                    f"match_count={len(filter_result.matched_words)}"
                )

            logger.debug(f"Local check passed, scan_time={check_time}ms")
            return RiskResult(
                has_risk=False,
                decision_type="1",
                should_terminate=False
            )

        except Exception as e:
            logger.exception(f"Local sensitive check error: {e}")
            return RiskResult(
                has_risk=False,
                decision_type="1",
                should_terminate=False
            )

    def _process_response(self, response: ModerateV2Response, is_stream: bool = False, content: str = None, system_lang_code: str = None) -> RiskResult:
        """
        处理响应并返回风险结果

        Args:
            response: LLM Shield的响应对象
            is_stream: 是否为流式检测
            content: 原始检查内容
            system_lang_code: 系统语言代码
        Returns:
            RiskResult: 风险检查结果
        """
        has_risk = False
        risk_reasons = []
        # risk_category = "违规"
        should_terminate = False

        # 检查风险信息
        # if response.result and response.result.risk_info and response.result.risk_info.risks:
            # for risk in response.result.risk_info.risks:
            #     if risk.prob and risk.prob > 0.8:
            #         has_risk = True
            #         risk_category = _LABEL_MAP.get(int(risk.label), "违规")
            #         risk_reasons.append(f"High-risk content detected (Category: {risk.category}, Probability: {risk.prob:.2%}), Risk: {risk}")
            #         # 高风险内容应立即终止
            #         if risk.prob > 0.95:
            #             should_terminate = True
            #         break

        # 检查决策类型
        decision_name = 'UNKNOWN'
        if response.result and response.result.decision:
            decision_type = response.result.decision.decision_type
            decision_map = {
                1: "PASS",
                2: "BLOCK",
                3: "MARK",
                4: "REPLACE",
                5: "OPTIMIZE"
            }

            if decision_type == 2:  # BLOCK应立即终止
                has_risk = True
                should_terminate = True
                risk_reasons.append(f"Content blocked by protection strategy")
            elif decision_type == 3:  # MARK类型
                has_risk = True
                risk_reasons.append(f"Content marked for observation")
                # 根据业务需求决定是否终止
                if is_stream:
                    should_terminate = True

            decision_name = decision_map.get(decision_type, 'UNKNOWN')

        # 记录日志和返回结果
        if has_risk:
            try:
                category = _LABEL_MAP.get(int(response.result.risk_info.risks[0].label), "违规")
            except Exception as e:
                logger.warning(f"Failed to extract risk category from response: {e}, defaulting to 违规")
                category = "违规"

            log_msg = f"LLM Shield: Risk detected, Decision: {decision_name}, Risk reasons: {'; '.join(risk_reasons)}, stream will be terminated, category={category}, response={response.model_dump()}"
            if should_terminate:
                logger.error(log_msg)
            else:
                logger.warning(log_msg)

            if content:
                msg = translate(system_lang_code, "21109315dbba4000a894", self._I18N_PATH)
                translated_category = translate(system_lang_code, category_key_map.get(category), self._I18N_PATH)
                if translated_category == "敏感问题":
                    translated_category = "敏感"
                fallback_message = msg.format(category=translated_category)
            else:
                fallback_message = f"抱歉，您的问题属于{category}问题，我无法回答。我是数字货币领域的智能助理Kia，您可以问我数字货币领域的其他问题。"

            return RiskResult(
                has_risk=True,
                risk_category=str(category),
                fallback_message=fallback_message,
                decision_type=decision_name,
                should_terminate=should_terminate
            )

        return RiskResult(
            has_risk=False,
            decision_type=decision_name,
            should_terminate=False
        )

    async def check(self, content, system_lang_code, **kwargs) -> RiskResult:
        # 构建请求
        request = ModerateV2Request(
            scene=self._app_id,
            message=MessageV2(
                role="user",
                content=content,
                contentType=ContentTypeV2.TEXT
            )
        )

        try:
            response = await self._client.Moderate(request)
            return self._process_response(response, content=content, system_lang_code=system_lang_code)
        except Exception as e:
            local_result = self._local_sensitive_check(content, system_lang_code)
            logger.exception(
                f"Remote API error: {e}, "
                f"fallback to local result (has_risk={local_result.has_risk})"
            )
            return local_result

    @staticmethod
    def _chunk_to_obj(chunk):
        """Normalize chunk to a dict. Agents may yield JSON str or StreamResponse (Pydantic) objects."""
        if isinstance(chunk, dict):
            return chunk
        if isinstance(chunk, str):
            try:
                return json.loads(chunk)
            except (json.JSONDecodeError, TypeError):
                return None
        if hasattr(chunk, "model_dump"):
            return chunk.model_dump()
        if hasattr(chunk, "model_dump_json"):
            try:
                return json.loads(chunk.model_dump_json())
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    async def stream_check(self, content_generator, system_lang_code):
        """
        流式风控检查，处理异步生成器的内容流
        """
        stream_buffer = ""
        pending_chunks = []
        stream_session = ModerateV2StreamSession()

        async for chunk in content_generator:
            pending_chunks.append(chunk)
            chunk_obj = self._chunk_to_obj(chunk)
            if chunk_obj is None:
                for pending_chunk in pending_chunks:
                    yield pending_chunk
                pending_chunks.clear()
                continue
            if chunk_obj.get("status", "") == StreamStatusType.FAILED.value:
                raise HttpException(code=code_msg.CODE_SERVER_ERROR, msg=chunk_obj.get("log", ""))
            elif chunk_obj.get('type', '').startswith("TITLE"):
                # TITLE类型的块需要立即输出，不能阻塞
                for pending_chunk in pending_chunks:
                    yield pending_chunk
                pending_chunks.clear()
                continue
            chunk_content = chunk_obj.get("content")
            if chunk_content is None:
                # 状态事件 (START/END) 无需审核，立即 flush
                for pending_chunk in pending_chunks:
                    yield pending_chunk
                pending_chunks.clear()
                continue
            elif not chunk_obj.get("checkSensitive", True):
                # 标记为不审核的事件（如工具进度），立即 flush
                for pending_chunk in pending_chunks:
                    yield pending_chunk
                pending_chunks.clear()
                continue
            chunk_content = str(chunk_content)
            stream_buffer += chunk_content

            # 当缓冲区达到阈值时进行检测
            while len(stream_buffer) >= self._chunk_size:
                check_content = stream_buffer
                stream_buffer = ""

                check_start_time = time.time()
                try:
                    response = await self._client.ModerateStream(
                        ModerateV2Request(
                            scene=self._app_id,
                            use_stream=2,
                            message=MessageV2(
                                role="assistant",
                                content=check_content,
                                contentType=ContentTypeV2.TEXT
                            )
                        ),
                        stream_session
                    )
                    result = self._process_response(response, is_stream=True, content=check_content, system_lang_code=system_lang_code)
                    if result.has_risk and result.should_terminate:
                        logger.error(f"Stream check: Risk detected during streaming, terminating output")
                        msg = translate(system_lang_code, "21109315dbba4000a894", self._I18N_PATH)
                        category = translate(system_lang_code, category_key_map.get(result.risk_category), self._I18N_PATH)
                        result.risk_category = str(category)
                        result.fallback_message = msg.format(category=category)
                        pending_chunks.clear()
                        raise RiskException(code=code_msg.CODE_RISK_ERROR, msg=result.fallback_message)
                except RiskException:
                    raise
                except Exception as e:
                    interface_cost = int((time.time() - check_start_time) * 1000)
                    logger.exception(f"stream_check(intermediate) error => usage time: {interface_cost}ms, content={check_content}, error={e}")
                    
                    local_result = self._local_sensitive_check(check_content, system_lang_code)
                    if local_result.has_risk:
                        logger.warning(
                            f"Blocked by local AC Automaton fallback (remote API failed): "
                            f"category={local_result.risk_category}"
                        )
                        pending_chunks.clear()
                        raise RiskException(code=code_msg.CODE_RISK_ERROR, msg=local_result.fallback_message)

                for pending_chunk in pending_chunks:
                    yield pending_chunk
                pending_chunks.clear()

        # 处理剩余的缓冲区内容
        if stream_buffer:
            final_check_content = stream_buffer
            stream_buffer = ""
            final_check_start = time.time()
            try:
                # 异步流式最终检测
                response = await self._client.ModerateStream(
                    ModerateV2Request(
                        scene=self._app_id,
                        use_stream=2,
                        message=MessageV2(
                            role="assistant",
                            content=final_check_content,
                            contentType=ContentTypeV2.TEXT
                        )
                    ),
                    stream_session
                )
                result = self._process_response(response, is_stream=True, content=final_check_content)

                if result.has_risk:
                    logger.warning(f"Stream check: Risk detected in final check")
                    msg = translate(system_lang_code, "21109315dbba4000a894", self._I18N_PATH)
                    category = translate(system_lang_code, category_key_map.get(result.risk_category), self._I18N_PATH)
                    result.fallback_message = msg.format(category=category)
                    pending_chunks.clear()
                    raise RiskException(code=code_msg.CODE_RISK_ERROR, msg=result.fallback_message)
            except RiskException:
                raise
            except Exception as e:
                interface_cost = int((time.time() - final_check_start) * 1000)
                logger.exception(f"stream_check(final) error => usage time: {interface_cost}ms, content={final_check_content}, error={e}")
                local_result = self._local_sensitive_check(final_check_content, system_lang_code)
                if local_result.has_risk:
                    logger.warning(
                        f"Blocked by local AC Automaton fallback in final check (remote API failed): "
                        f"category={local_result.risk_category}"
                    )
                    pending_chunks.clear()
                    raise RiskException(code=code_msg.CODE_RISK_ERROR, msg=local_result.fallback_message)

        for pending_chunk in pending_chunks:
            yield pending_chunk
        pending_chunks.clear()

    async def stream_check_fallback(self, content_generator, system_lang_code):
        """
        Stream-based local sensitive word detection - fallback when remote risk control is disabled
        """
        from web.config import config, is_risk_control_enabled

        if not is_risk_control_enabled():
            async for chunk in content_generator:
                yield chunk
            return

        stream_buffer = ""
        pending_chunks = []
        chunk_size = self._chunk_size

        # Get local risk threshold configuration
        local_risk_threshold = getattr(config, 'local_risk_threshold', 1)

        # Initialize sensitive word filter
        self._init_sensitive_word_filter()

        async for chunk in content_generator:
            pending_chunks.append(chunk)
            chunk_obj = self._chunk_to_obj(chunk)
            if chunk_obj is None:
                for pending_chunk in pending_chunks:
                    yield pending_chunk
                pending_chunks.clear()
                continue

            if chunk_obj.get("status", "") == StreamStatusType.FAILED.value:
                raise HttpException(code=code_msg.CODE_SERVER_ERROR, msg=chunk_obj.get("log", ""))
            elif chunk_obj.get('type', '').startswith("TITLE"):
                for pending_chunk in pending_chunks:
                    yield pending_chunk
                pending_chunks.clear()
                continue

            chunk_content = chunk_obj.get("content")
            if chunk_content is None:
                # Status events (START/END) don't need moderation, flush immediately
                for pending_chunk in pending_chunks:
                    yield pending_chunk
                pending_chunks.clear()
                continue
            elif not chunk_obj.get("checkSensitive", True):
                # Events marked as non-sensitive (e.g. tool progress), flush immediately
                for pending_chunk in pending_chunks:
                    yield pending_chunk
                pending_chunks.clear()
                continue

            chunk_content = str(chunk_content)
            stream_buffer += chunk_content

            # Perform check when buffer reaches threshold
            while len(stream_buffer) >= chunk_size:
                check_content = stream_buffer
                stream_buffer = ""

                check_start_time = time.time()
                try:
                    result = self._local_sensitive_check(check_content, system_lang_code, threshold=local_risk_threshold)
                    if result.has_risk and result.should_terminate:
                        logger.error(f"Stream check fallback: Risk detected, terminating output")
                        pending_chunks.clear()
                        raise RiskException(code=code_msg.CODE_RISK_ERROR, msg=result.fallback_message)
                except RiskException:
                    raise
                except Exception as e:
                    interface_cost = int((time.time() - check_start_time) * 1000)
                    logger.exception(f"stream_check_fallback error: cost_time={interface_cost}ms, error={e}")

                for pending_chunk in pending_chunks:
                    yield pending_chunk
                pending_chunks.clear()

        # Handle remaining buffer content
        if stream_buffer:
            final_check_content = stream_buffer
            stream_buffer = ""
            final_check_start = time.time()
            try:
                result = self._local_sensitive_check(final_check_content, system_lang_code, threshold=local_risk_threshold)
                if result.has_risk:
                    logger.warning(f"Stream check fallback final: Risk detected")
                    pending_chunks.clear()
                    raise RiskException(code=code_msg.CODE_RISK_ERROR, msg=result.fallback_message)
            except RiskException:
                raise
            except Exception as e:
                interface_cost = int((time.time() - final_check_start) * 1000)
                logger.exception(f"stream_check_fallback final error: cost_time={interface_cost}ms, error={e}")

        for pending_chunk in pending_chunks:
            yield pending_chunk
        pending_chunks.clear()


llm_shield = LLMShield()
