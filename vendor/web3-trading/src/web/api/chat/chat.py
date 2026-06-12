# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/18 20:52:11
'''

import asyncio
import os
import time
import random
import json
import logging
from typing import Optional, List, Dict, Any, Union

from fastapi import Request, Body
from openai import AsyncOpenAI
from httpx import AsyncClient
from pydantic import BaseModel, Field

from web.router import BaseRouter
from web.response import EventSourceResponse, JsonResponse
from sse_starlette.sse import ServerSentEvent
from agent.base import BaseAgent
from agent.schema import AgentType, output_schema
from memory.mem0 import Mem0Memory
from web.config import config, is_risk_control_enabled
from web.exceptions import HttpException
from web import code_msg
from web.context import context
from agent.schema import SessionModel, SessionStatusType
from libs.language import format_system_language, LANGUAGE_CODE_TO_NAME_MAP
from libs.wrapper import usage_time
from agent.schema import StreamStatusType, QAModel, SourceType
from .cache import RedisCache, SessionStatus
from .items import ExtraBodyModel
from libs import http

_gateway = None


def _get_gateway():
    """Lazy-initialised Gateway singleton."""
    global _gateway
    if _gateway is None:
        from agent.plan import Gateway
        _gateway = Gateway()
    return _gateway

logger = logging.getLogger(__name__)


def welcome_prompt_memory_long(memory: List[Dict[str, Any]], language: str = "English") -> str:
    memory_items = []
    for i, mem in enumerate(memory, 1):
        content = mem.get('memory', '')
        memory_items.append(f"{i}. \"{content}\"")

    memory_str = os.linesep.join(memory_items)

    return f"""## ⚠️ MANDATORY: RESPOND ONLY IN {language.upper()} ⚠️
## ⚠️ MANDATORY: OUTPUT MUST BE VALID JSON ⚠️

You are an expert user intention analyzer and personalized question generator. Your task is to deeply understand what users truly care about from their memory data, then create 3 logically progressive questions that feel natural and genuine - as if the user themselves would ask them.

## 🚨 CRITICAL REQUIREMENTS - FAILURE TO FOLLOW WILL RESULT IN ERROR:
1. **ALL text must be written in {language} - NO EXCEPTIONS**
2. **You MUST provide ALL required JSON fields: primary_interest, logical_progression, welcome_messages**
3. **Output MUST be valid JSON - start with {{ and end with }}**
4. **NO additional text before or after the JSON**
5. **Use double quotes for all strings**

## Content Excellence Standards
**Focus on creating high-quality, appropriate, and valuable content:**

### Safety and Appropriateness
- **Content Focus**: Generate questions that are safe, constructive, and appropriate for all users
- **Positive Engagement**: Create content that promotes healthy curiosity and learning
- **Original Insights**: Develop fresh, original questions based on user memory analysis

### Professional Excellence
- **Respectful Communication**: Use warm, professional tone that respects user intelligence and autonomy
- **Accurate and Helpful**: When addressing factual topics, focus on education and understanding
- **User Empowerment**: Create questions that help users learn and grow independently

### Privacy and Respect
- **Personal Boundaries**: Maintain appropriate boundaries while being genuinely helpful
- **Privacy Protection**: Focus on interests and knowledge rather than sensitive personal details
- **Supportive Approach**: Generate questions that feel encouraging and supportive

### Financial Content Guidelines
**For finance-related topics, focus on education and understanding:**

- **Learning-Oriented Questions**: Frame questions around understanding concepts, technology, and market dynamics
  - "How do different blockchain protocols compare in terms of technology?"
  - "What factors typically influence cryptocurrency market trends?"
  - "How do DeFi protocols work from a technical perspective?"

- **Professional Guidance**: When appropriate, acknowledge the value of professional consultation for personal financial decisions

**Approach**: When encountering any challenging content areas, naturally redirect toward the educational and learning aspects that align with the user's genuine interests.

## User Memory Analysis
**User Memory Data:**
{memory_str}
**Please use {language} to generate all welcome messages**

## Core Task: Deep Memory Analysis + Progressive Question Generation

### Step 1: Intent Analysis
First, analyze the user's memory to identify:
- **Primary Interest Domain**: What is the user's main area of focus? (e.g., cryptocurrency, technology, health, finance, learning)
- **Specific Focus Points**: What particular aspects do they care most about?
- **Underlying Motivations**: What are they trying to achieve or understand?
- **Information Gaps**: What knowledge do they seem to be seeking?

### Step 2: Progressive Logic Framework
For the three welcome messages, create a logical progression:
1. **Foundation Question** → Understanding current status/situation
2. **Development Question** → Exploring recent events/applications  
3. **Advanced Question** → Seeking deeper insights/optimization

### Step 3: Question Generation Principles
Generate all questions following these principles:
- **Direct Questions**: Start with "What", "How", "Which", "Where" - avoid "Are you", "Have you", "Do you"
- **Help-Seeking Tone**: Generate questions as if the user is asking for help or information
- **Objective Focus**: Ask about topics/concepts rather than personal preferences or current situations
- **Simple Language**: Use conversational, direct language without formal or survey-style phrasing
- **Memory-Based**: Reference specific concepts from their memory data
- **Educational**: Seek understanding and knowledge, not investment advice

### Step 4: Quality Standards
- **Length**: 12-25 words per question
- **Tone**: Curious, direct, and authentic - avoid AI-assistant language
- **Specificity**: Use actual terms/concepts from their memory, not generalities
- **Natural Flow**: Questions should feel like a real person seeking help or information

Based on the above standards and principles, generate:
1. **One caring AI assistant greeting** addressing their main interest (for primary_interest field)
2. **Three questions the USER would naturally ask** that build logically on each other (for welcome_messages)

## Output Format
```json
{{
  "primary_interest": "A caring greeting from AI assistant about their main interest",
  "logical_progression": "Explanation of the logic connecting the three user questions",
  "welcome_messages": [
    "First question the USER would ask about current status/understanding",
    "Second question the USER would ask about recent events/applications",
    "Third question the USER would ask seeking deeper insights/optimization"
  ]
}}
```

## Examples of Good Progressive Logic

**Example 1 - Cryptocurrency Learning:**
Memory: ["Learning about LTC technology", "Understanding DeFi protocols", "Following market trends"]
```json
{{
  "primary_interest": "I see you're really interested in understanding cryptocurrency technology - how can I help you learn more about blockchain and DeFi?",
  "logical_progression": "Technology understanding → Protocol mechanics → Market dynamics",
  "welcome_messages": [
    "What's the key difference between LTC and other blockchain technologies?",
    "How do different DeFi protocols actually generate yield?",
    "What market trends should I watch for crypto opportunities?"
  ]
}}
```

## ⚠️ FINAL REMINDER: OUTPUT ONLY JSON IN {language.upper()} ⚠️

Now analyze the user's memory deeply and generate 3 questions the USER would naturally ask that capture their genuine interests and information needs.

**EXAMPLE OUTPUT FORMAT** (in {language}):
{{
  "primary_interest": "Your greeting text in {language}",
  "logical_progression": "Your explanation in {language}",
  "welcome_messages": [
    "First question in {language}",
    "Second question in {language}",
    "Third question in {language}"
  ]
}}

**RESPOND ONLY WITH THE JSON ABOVE - NO OTHER TEXT**"""


def welcome_prompt_memory(memory: List[Dict[str, Any]], language: str = "English") -> str:
    memory_items = []
    for i, mem in enumerate(memory, 1):
        content = mem.get('memory', '')
        memory_items.append(f"{i}. \"{content}\"")

    memory_str = os.linesep.join(memory_items)

    return f"""## ⚠️ MANDATORY: RESPOND ONLY IN {language.upper()} ⚠️
## ⚠️ MANDATORY: OUTPUT MUST BE VALID JSON ⚠️

You are an expert user intention analyzer and personalized question generator. Your task is to deeply understand what users truly care about from their memory data, then create 3 logically progressive questions that feel natural and genuine - as if the user themselves would ask them.

## 🚨 CRITICAL REQUIREMENTS - FAILURE TO FOLLOW WILL RESULT IN ERROR:
1. **ALL text must be written in {language} - NO EXCEPTIONS**
2. **You MUST provide ALL required JSON fields: primary_interest, logical_progression, welcome_messages**
3. **Output MUST be valid JSON - start with {{ and end with }}**
4. **NO additional text before or after the JSON**
5. **Use double quotes for all strings**

## Content Guidelines
- Create safe, educational, supportive questions that respect user intelligence
- Focus on learning and understanding rather than specific advice
- For finance topics: emphasize concepts and technology, not investment decisions
- Redirect challenging areas toward educational aspects of user interests

## User Memory Analysis
**User Memory Data:**
{memory_str}

## Core Task: Deep Memory Analysis + Progressive Question Generation

### Process
1. **Analyze**: Identify user's main interests, motivations, and knowledge gaps
2. **Structure**: Create logical progression: Current understanding → Recent developments → Deeper insights

### Requirements
- **Direct Questions**: Start with "What", "How", "Which", "Where" - avoid "Are you", "Have you", "Do you"
- **Help-Seeking Tone**: Generate questions as if the user is asking for help or information
- **Objective Focus**: Ask about topics/concepts rather than personal preferences or current situations
- **Simple Language**: Use conversational, direct language without formal or survey-style phrasing
- **Memory-Based**: Reference specific concepts from their memory data
- **Educational**: Seek understanding and knowledge, not investment advice

Based on the above standards and principles, generate:
1. **One caring AI assistant greeting** addressing their main interest (for primary_interest field)
2. **Three questions the USER would naturally ask** that build logically on each other (for welcome_messages)

## Output Format
```json
{{
  "primary_interest": "A caring greeting from AI assistant about their main interest",
  "logical_progression": "Explanation of the logic connecting the three user questions",
  "welcome_messages": [
    "First question the USER would ask about current status/understanding",
    "Second question the USER would ask about recent events/applications",
    "Third question the USER would ask seeking deeper insights/optimization"
  ]
}}
```

## Examples of Good Progressive Logic

**Example 1 - Cryptocurrency Learning:**
Memory: ["Learning about LTC technology", "Understanding DeFi protocols", "Following market trends"]
```json
{{
  "primary_interest": "I see you're really interested in understanding cryptocurrency technology - how can I help you learn more about blockchain and DeFi?",
  "logical_progression": "Technology understanding → Protocol mechanics → Market dynamics",
  "welcome_messages": [
    "What's the key difference between LTC and other blockchain technologies?",
    "How do different DeFi protocols actually generate yield?",
    "What market trends should I watch for crypto opportunities?"
  ]
}}
```

## ⚠️ FINAL REMINDER: OUTPUT ONLY JSON IN {language.upper()} ⚠️

Now analyze the user's memory deeply and generate 3 questions the USER would naturally ask that capture their genuine interests and information needs.

**EXAMPLE OUTPUT FORMAT** (in {language}):
{{
  "primary_interest": "Your greeting text in {language}",
  "logical_progression": "Your explanation in {language}",
  "welcome_messages": [
    "First question in {language}",
    "Second question in {language}",
    "Third question in {language}"
  ]
}}

**RESPOND ONLY WITH THE JSON ABOVE - NO OTHER TEXT**"""


def welcome_prompt_memory_optimized(memory: List[Dict[str, Any]], language: str = "English") -> str:
    """优化后的精简prompt版本：保留所有要求，精简长度"""
    memory_items = []
    for i, mem in enumerate(memory, 1):
        content = mem.get('memory', '')
        memory_items.append(f"{i}. \"{content}\"")

    memory_str = os.linesep.join(memory_items)

    # 根据语言设置长度限制
    if "Chinese" in language or "中文" in language:
        length_constraint = "Each question MUST NOT exceed 20 Chinese characters"
    else:
        length_constraint = "Each question MUST NOT exceed 15 words"

    return f"""## ⚠️ MANDATORY: RESPOND ONLY IN {language.upper()} ⚠️
## ⚠️ MANDATORY: OUTPUT MUST BE VALID JSON ⚠️

Analyze user memory and generate 3 progressive questions users would naturally ask.

## 🚨 CRITICAL REQUIREMENTS:
1. ALL text in {language}
2. Required fields: primary_interest, logical_progression, welcome_messages
3. Valid JSON only ({{ ... }})
4. NO text before/after JSON
5. Use double quotes
6. {length_constraint}

## User Memory:
{memory_str}

## Task:
Analyze user interests → Generate questions: Current understanding → Recent developments → Deeper insights

## Requirements:
- Start with What/How/Which/Where (not Are/Have/Do)
- User voice seeking help
- Topic-focused, educational, conversational
- Reference memory concepts
- Safe content; finance = concepts not advice

Generate:
1. AI greeting about main interest (primary_interest)
2. Three progressive user questions (welcome_messages)

## Output Format

**Examples of Good Progressive Logic - Cryptocurrency Learning:**
Memory: ["Learning about LTC technology", "Understanding DeFi protocols", "Following market trends"]
```json
{{
  "primary_interest": "I see you're really interested in understanding cryptocurrency technology - how can I help you learn more about blockchain and DeFi?",
  "logical_progression": "Technology understanding → Protocol mechanics → Market dynamics",
  "welcome_messages": [
    "What's the key difference between LTC and other blockchain technologies?",
    "How do different DeFi protocols actually generate yield?",
    "What market trends should I watch for crypto opportunities?"
  ]
}}
```

## ⚠️ FINAL REMINDER ⚠️
- Output ONLY valid JSON in {language.upper()}
- Remember: {length_constraint}
- NO additional text before or after the JSON

Now generate your response:"""


def welcome_prompt_memory_v2(memory: List[Dict[str, Any]], language: str = "English") -> str:
    """多语言优化版本：支持24种语言，精简输出，移除logical_progression"""
    memory_items = []
    for i, mem in enumerate(memory, 1):
        content = mem.get('memory', '')
        memory_items.append(f"{i}. \"{content}\"")

    memory_str = os.linesep.join(memory_items)

    # 根据语言特点设置长度限制 - 与Test_LANGUAGES列表完全对应
    if "Chinese" in language:
        # 中文（简体）、中文（繁体）- 表意文字，信息密度高
        question_constraint = "Each question: max 20 characters"
        interest_constraint = "Primary interest: max 50 characters"
    elif "Japanese" in language:
        # 日语（日本）- 汉字+假名混合，信息密度较高
        question_constraint = "Each question: max 25 characters"
        interest_constraint = "Primary interest: max 60 characters"
    elif "Korean" in language:
        # 韩语（韩国）- 表音文字，但词汇较紧凑
        question_constraint = "Each question: max 25 characters"
        interest_constraint = "Primary interest: max 60 characters"
    elif "Arabic" in language:
        # 阿拉伯语（埃及）- 词根系统，词汇较长，需要更多空间
        question_constraint = "Each question: max 20 words"
        interest_constraint = "Primary interest: max 50 words"
    elif any(lang in language for lang in ["Thai", "Hindi", "Bengali", "Urdu"]):
        # 泰语（泰国）、印地语（印度）、孟加拉语（孟加拉国）、乌尔都语（巴基斯坦）
        # 这些语言词汇较长，需要更多词数
        question_constraint = "Each question: max 25 words"
        interest_constraint = "Primary interest: max 60 words"
    elif any(lang in language for lang in ["German", "Dutch"]):
        # 德语（德国）、荷兰语（荷兰）- 复合词较多，单词长但表达紧凑
        question_constraint = "Each question: max 18 words"
        interest_constraint = "Primary interest: max 45 words"
    elif any(lang in language for lang in ["Vietnamese", "Indonesian", "Malay", "Filipino"]):
        # 越南语（越南）、印度尼西亚语（印度尼西亚）、马来语（马来西亚）、菲律宾语（菲律宾）
        # 表音文字，词汇较多
        question_constraint = "Each question: max 20 words"
        interest_constraint = "Primary interest: max 50 words"
    else:
        # 其他欧洲语言：English, Spanish (Spain), French (France), Italian (Italy),
        # Portuguese (Brazil), Polish (Poland), Russian (Russia), Ukrainian (Ukraine), Turkish (Turkey)
        question_constraint = "Each question: max 15 words"
        interest_constraint = "Primary interest: max 40 words"

    return f"""## ⚠️ MANDATORY: RESPOND ONLY IN {language.upper()} ⚠️
## ⚠️ MANDATORY: OUTPUT MUST BE VALID JSON ⚠️

Analyze user memory and generate 3 progressive questions users would naturally ask.

## 🚨 CRITICAL REQUIREMENTS:
1. ALL text in {language}
2. Required fields: primary_interest, welcome_messages
3. Valid JSON only ({{ ... }})
4. NO text before/after JSON
5. Use double quotes
6. {question_constraint}
7. {interest_constraint}

## User Memory:
{memory_str}

## Task:
Analyze user interests → Generate 3 progressive questions: Current understanding → Recent developments → Deeper insights

## Logical Progression Requirements:
The 3 questions MUST follow a clear logical progression that builds naturally:
- Question 1: Foundation - Current understanding, basic concepts, key differences
- Question 2: Application - Recent developments, practical mechanisms, how things work
- Question 3: Advanced - Deeper insights, optimization, trends, future implications

Each question should naturally lead to the next, creating a learning pathway from basics to advanced understanding.

## Requirements:
- Start with What/How/Which/Where (not Are/Have/Do)
- User voice seeking help
- Topic-focused, educational, conversational
- Reference memory concepts
- Safe content; finance = concepts not advice
- Ensure clear logical flow between questions

Generate:
1. AI greeting about main interest (primary_interest)
2. Three progressive user questions (welcome_messages)

## Output Format Example:

```json
{{
  "primary_interest": "I see you're really interested in understanding cryptocurrency technology - how can I help you learn more about blockchain and DeFi?",
  "welcome_messages": [
    "What's the key difference between LTC and Bitcoin?",
    "How do DeFi protocols generate yield?",
    "What market trends matter most for crypto?"
  ]
}}
```

## ⚠️ FINAL REMINDER ⚠️
- Output ONLY valid JSON in {language.upper()}
- {question_constraint}
- {interest_constraint}
- NO additional text before or after the JSON

Now generate your response:"""


class KiaAgentApi(BaseRouter):
    def log_welcome(self, event: str, user_id: str, language: str, **kwargs):
        """统一的welcome日志格式"""
        # 计算耗时（毫秒）
        if 'memory_start_time' in kwargs and 'memory_end_time' in kwargs:
            kwargs['memory_cost_ms'] = int((kwargs['memory_end_time'] - kwargs['memory_start_time']) * 1000)
        if 'llm_start_time' in kwargs and 'llm_end_time' in kwargs:
            kwargs['llm_cost_ms'] = int((kwargs['llm_end_time'] - kwargs['llm_start_time']) * 1000)

        base = f"event: {event}, user_id: {user_id}, language: {language}"
        extra = ", ".join(f"{k}: {v}" for k, v in kwargs.items())
        return f"{base}, {extra}" if extra else base

    async def _get_welcome_from_memory(
        self,
        user_id: str,
        language_name: str,
        memory_limit: int,
        debug_log: bool = False,
    ):
        """根据用户记忆生成欢迎语和推荐问句，成功返回 JsonResponse，失败抛出 HttpException"""
        memory = Mem0Memory(user_id)
        memory_start_time = None
        memory_end_time = None
        try:
            memory_start_time = time.time()
            memories = await memory.get_recent_memories(limit=30)
            memory_end_time = time.time()
            if debug_log:
                logger.info(f"Get recent filtered memories result: {memories}")

            if not memories:
                logger.warning(self.log_welcome("no_memories/new_user", user_id, language_name,
                                                memory_start_time=memory_start_time,
                                                memory_end_time=memory_end_time))
                raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

            if len(memories) > memory_limit:
                memories = random.sample(memories, memory_limit)

            llm_start_time = time.time()
            try:
                llm_result = await self._call_llm_for_welcome(
                    memories, language_name, user_id, memory_start_time, memory_end_time
                )
                llm_end_time = time.time()

                if (llm_result
                        and 'primary_interest' in llm_result
                        and 'welcome_messages' in llm_result
                        and llm_result.get('primary_interest')
                        and isinstance(llm_result.get('welcome_messages'), list)
                        and len(llm_result['welcome_messages']) == 3):
                    logger.info(self.log_welcome("welcome_success", user_id, language_name,
                                                memory_start_time=memory_start_time,
                                                memory_end_time=memory_end_time,
                                                llm_start_time=llm_start_time,
                                                llm_end_time=llm_end_time))
                    recommended_questions = [
                        {"lightIcon": "", "darkIcon": "", "query": item}
                        for item in llm_result['welcome_messages']
                    ]
                    return JsonResponse(content={
                        "welcome_message": llm_result['primary_interest'],
                        "recommended_questions": recommended_questions,
                        "language": language_name,
                    })

                logger.warning(self.log_welcome("llm_incomplete", user_id, language_name,
                                               memory_start_time=memory_start_time,
                                               memory_end_time=memory_end_time,
                                               llm_start_time=llm_start_time,
                                               llm_end_time=llm_end_time, result=str(llm_result)))
                raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)
            except HttpException:
                raise
            except Exception as llm_error:
                logger.warning(self.log_welcome("llm_failed", user_id, language_name,
                                                memory_start_time=memory_start_time,
                                                memory_end_time=memory_end_time,
                                                llm_start_time=llm_start_time,
                                                llm_end_time=time.time(), error=llm_error))
                raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)
        except Exception as e:
            raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

    async def _get_welcome_from_external_api(
        self,
        user_id: str,
        language_code: str,
        language_name: str,
    ):
        """调用外部推荐 API 获取欢迎语和推荐问句，成功返回 JsonResponse，失败抛出 HttpException"""
        import datetime
        from Crypto.PublicKey import RSA
        from Crypto.Cipher import PKCS1_v1_5
        import base64

        external_start_time = time.time()
        recommend_url = getattr(config, "welcome_recommend_api_url", None)
        logger.info(f"Calling external recommend API at {recommend_url} for welcomeV2, user_id: {user_id}, language: {language_name}")

        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ms_token_methods = []
        def convert_to_pem(key_string):
            key_string = key_string.replace("-----BEGIN PUBLIC KEY-----", "")
            key_string = key_string.replace("-----END PUBLIC KEY-----", "")
            key_string = key_string.strip()
            pem_key = "-----BEGIN PUBLIC KEY-----\n"
            for i in range(0, len(key_string), 64):
                pem_key += key_string[i:i + 64] + "\n"
            pem_key += "-----END PUBLIC KEY-----"
            return pem_key

        try:
            logger.info("[MS-Token] 尝试通过RSA加密生成MS-Token ")
            content = {
                "app_id": "big-data",
                "trace_id": user_id,
                "timestamp": now_str
            }
            content_str = json.dumps(content, separators=(',', ':'))
            public_key = getattr(config, "ms_token_public_key", None)
      
            if public_key:
                pem_key = convert_to_pem(public_key)
                rsakey = RSA.import_key(pem_key)
                cipher = PKCS1_v1_5.new(rsakey)
                encrypted_bytes = cipher.encrypt(content_str.encode('utf-8'))
                ms_token_methods.append(base64.b64encode(encrypted_bytes).decode('utf-8'))
                logger.info("[MS-Token] 通过RSA+PKCS1_v1_5加密生成成功")
            else:
                logger.warning("[MS-Token] 未配置public_key，无法通过RSA生成")
        except Exception as e:
            logger.warning(f"[MS-Token] RSA生成流程异常: {e}")


        # 只保留RSA加密生成的ms_token
        resp = None
        if ms_token_methods:
            ms_token = ms_token_methods[0]
            logger.info(f"[MS-Token] 仅使用RSA加密方式调用get请求: {ms_token}")
            try:
                resp = await http.get(
                    recommend_url,
                    headers={"X-USER-ID": user_id, "MS-Token": ms_token}
                )
                logger.info(f"[MS-Token] 返回: {resp}")
            except Exception as e:
                logger.warning(f"[MS-Token] 调用失败: {e}")

        external_end_time = time.time()
        logger.info(f"Received response from external recommend API for welcomeV2, user_id: {user_id}, language: {language_name}, response: {resp}")

        if not resp or not resp.get("success") or str(resp.get("code")) != "200":
            logger.warning(self.log_welcome(
                "welcome_v2_remote_failed",
                user_id,
                language_name,
                external_start_time=external_start_time,
                external_end_time=external_end_time,
                remote_code=resp.get("code") if resp else None,
                remote_msg=resp.get("msg") if resp else None,
            ))
            raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

        data = resp.get("data") or {}
        recommended_questions = data.get("recommendedQuestions") or []
        if not isinstance(recommended_questions, list) or not recommended_questions:
            logger.warning(self.log_welcome(
                "welcome_v2_empty_questions",
                user_id,
                language_name,
                external_start_time=external_start_time,
                external_end_time=external_end_time,
            ))
            raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

        # checkQuery可以抽成一个公共函数（risk_control_enabled=false 时跳过）
        try:
            if is_risk_control_enabled():
                if config.risk_enable:
                    questions_text = "\n".join([q.get("query", "") for q in recommended_questions if isinstance(q, dict)])
                    risk_result = await self._llm_shield.check(questions_text, language_code)
                else:
                    questions_text = "\n".join([q.get("query", "") for q in recommended_questions if isinstance(q, dict)])
                    risk_result = self._llm_shield._local_sensitive_check(questions_text, language_code)

                if risk_result.has_risk and risk_result.should_terminate:
                    logger.warning(self.log_welcome(
                        "welcome_v2_risk_detected",
                        user_id,
                        language_name,
                        external_start_time=external_start_time,
                        external_end_time=external_end_time,
                        risk=risk_result.risk_category
                    ))
                    raise HttpException(code=code_msg.CODE_PARAMETER_ERROR, msg=risk_result.fallback_message)
                logger.info("✅ [Welcome风控] 全部检测通过")
        except HttpException:
            raise
        except Exception as e:
            logger.exception(self.log_welcome(
                "welcome_v2_risk_error",
                user_id,
                language_name,
                external_start_time=external_start_time,
                external_end_time=external_end_time,
                error=e
            ))
            raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

        llm_start_time = time.time()
        welcome_message = "您好！我是您的加密貨幣AI助手。請問有什麼問題嗎？"
        try:
            llm_result = await self._generate_welcome_message_by_queries(
                queries=[q.get("query", "") for q in recommended_questions if isinstance(q, dict) and q.get("query")],
                language=language_name,
                language_code=language_code,
                user_id=user_id,
                external_start_time=external_start_time,
                external_end_time=external_end_time,
            )
            llm_end_time = time.time()

            if (llm_result and isinstance(llm_result, dict)
                    and 'welcome_message' in llm_result
                    and 'translated_queries' in llm_result
                    and isinstance(llm_result['translated_queries'], list)
                    and len(llm_result['translated_queries']) == len(recommended_questions)):
                welcome_message = llm_result['welcome_message']
                for idx, question_obj in enumerate(recommended_questions):
                    if isinstance(question_obj, dict):
                        question_obj['query'] = llm_result['translated_queries'][idx]
            else:
                logger.warning("LLM did not return valid result, using default welcome message")
                if language_code in ("zh_hk", "zh_cn"):
                    _fallback_zh = (
                        ["如何選擇適合新手的加密貨幣組合？", "如何分析市場趨勢優化投資決策？", "分散加密資產的最佳策略有哪些？"]
                        if language_code == "zh_hk" else
                        ["如何选择适合新手的加密货币组合？", "如何分析市场趋势优化投资决策？", "分散加密资产的最佳策略有哪些？"]
                    )
                    for idx, q_obj in enumerate(recommended_questions):
                        if isinstance(q_obj, dict) and idx < len(_fallback_zh):
                            q_obj["query"] = _fallback_zh[idx]
        except Exception as llm_error:
            llm_end_time = time.time()
            logger.warning(self.log_welcome(
                "llm_failed",
                user_id,
                language_name,
                external_start_time=external_start_time,
                external_end_time=external_end_time,
                llm_start_time=llm_start_time,
                llm_end_time=llm_end_time,
                error=llm_error
            ))

        logger.info(self.log_welcome(
            "welcome_v2_success",
            user_id,
            language_name,
            external_start_time=external_start_time,
            external_end_time=external_end_time,
            llm_start_time=llm_start_time,
            llm_end_time=llm_end_time,
            question_count=len(recommended_questions)
        ))

        return JsonResponse(content={
            "welcome_message": welcome_message,
            "recommended_questions": recommended_questions,
            "language": language_code,
        })

    def _check_body(self, extraBody):
        extra_body_obj = ExtraBodyModel()
        if extraBody:
            try:
                if isinstance(extraBody, str):
                    extra_body_dict = json.loads(extraBody)
                    extra_body_obj = ExtraBodyModel(**extra_body_dict)
                elif isinstance(extraBody, dict):
                    extra_body_obj = ExtraBodyModel(**extraBody)
            except Exception as e:
                logger.error(f"Failed to parse extraBody: {e}")
                raise HttpException(code=code_msg.CODE_PARAMETER_ERROR)
        return extra_body_obj

    async def _run_chat_query(
        self,
        query: str,
        agentType: AgentType,
        sessionId: str,
        extraBody: Optional[Union[str, dict]],
        language: str,
        source: Optional[SourceType],
    ) -> Dict[str, Any]:
        """Shared implementation for /chat/query and /chat/local_query (avoids loopback HTTP to a fixed port)."""
        start_time = time.time()
        extra_body_obj = self._check_body(extraBody)

        gateway = _get_gateway()

        filter_result = await gateway.pre_filter(query, sessionId, self.user_id)
        if filter_result.action == "duplicate":
            raise HttpException(code=code_msg.CODE_ALREADY_EXIST, msg="duplicate_query")
        if filter_result.action == "reject":
            raise HttpException(code=code_msg.CODE_PARAMETER_ERROR, msg=filter_result.reason)

        if extra_body_obj.model_dump():
            filter_result.query += f"\n\n{extraBody}"
        agent = await gateway.dispatch(
            query=filter_result.query,
            user_id=self.user_id,
            session_id=sessionId,
            extra_body=extra_body_obj,
            agent_type_hint=agentType.value,
            source=source,
        )
        agent.system_lang_code = format_system_language(language)
        await agent.check_query()
        await agent.on_init()

        @usage_time
        async def push():
            cache = None
            try:
                async for event in agent.run():
                    event_schema = output_schema(event)
                    if cache is None:
                        cache = RedisCache(agent.session_id, agent.qa_id)
                        await cache.session_meta.create_session(
                            query=query,
                            agent_type=agentType,
                            extra_body=extra_body_obj,
                            ttl=config.resume_config.redis_session.ttl
                        )
                        first_cost_time = int((time.time() - start_time) * 1000)
                        await cache.session_queue.append_token(event_schema.event_str, ttl=config.resume_config.ttl)
                        logger.info(f"first_cost_time: {first_cost_time}ms")
                        await cache.listen_cancel()
                    elif cache.is_canceled:
                        await cache.cancel(agent.qa, agent.session)
                        return
                    else:
                        await cache.session_queue.append_token(event_schema.event_str, ttl=config.resume_config.ttl)

                    agent.offset += 1
                    context.set("offset", agent.offset)

                event_object = event_schema.event_object
                if event_object.status == StreamStatusType.FAILED:
                    await cache.session_meta.update_session_status(event_object.status.value, event_object.log, ttl=config.resume_config.ttl)
                else:
                    await cache.session_meta.update_session_status(StreamStatusType.COMPLETED.value, ttl=config.resume_config.ttl)

            except asyncio.CancelledError:
                logger.error("Task cancelled - client disconnected")
                if cache and cache._cancel_id:
                    cache.cancel_listener()
                return
            except Exception as e:
                logger.exception(f"Unkown push error, error: {e}")
            finally:
                if cache and cache._cancel_id:
                    cache.cancel_listener()
                if agent._pending_tasks:
                    await agent._destroy()

        asyncio.create_task(push())
        await agent.init_event.wait()
        return {
            "sessionId": agent.session_id,
            "qaId": agent.qa_id,
        }

    def __init__(self):
        from llm.shield.handler import llm_shield
        self._llm_shield = llm_shield

        @self._router.post("/chat/cancel")
        async def cancel_session(
            sessionId: str = Body(min_length=32, max_length=32, description="会话ID"),
            qaId: str = Body(min_length=32, max_length=32, description="对话ID"),
        ):
            """用户主动发起取消"""
            session = await SessionModel.get(sessionId, user_id=context.get("user_id"))
            if session is None:
                raise HttpException(code=code_msg.CODE_PARAMETER_ERROR)

            cache = RedisCache(sessionId, qaId)
            # if session.get("status", "") == SessionStatusType.COMPLETED.value:
            qa: QAModel = await QAModel.get(id=qaId)
            await qa.cancel()

            session = SessionModel(**session)
            await session.cancel()
            
            await cache.session_meta.update_session_status(SessionStatus.CANCELED.value)
            await cache.session_channel.publish_cancel()

        @self._router.post("/chat/local_query")
        async def chat(
            query: str = Body(..., min_length=1, max_length=20 * 1000, description="问句"),
            agentType: AgentType = Body(AgentType.QUICK_REASONING, description="类型"),
            sessionId: str = Body(min_length=32, max_length=32, description="会话ID"),
            extraBody: Optional[Union[str, dict]] = Body(None, description="额外参数"),
            language: str = Body("", min_length=0, max_length=32, description="主站语言"),
            offset: int = Body(0, description="偏移量"),
            source: Optional[SourceType] = Body(None, description="来源"),
        ):
            """LLM对话"""
            data = await self._run_chat_query(
                query=query,
                agentType=agentType,
                sessionId=sessionId,
                extraBody=extraBody,
                language=language,
                source=source,
            )
            qa_id = data['qaId']
            cache = RedisCache(session_id=data['sessionId'], qa_id=qa_id)

            # 1. 验证会话存在
            session_meta = await cache.session_meta.get_session_meta()
            if not session_meta:
                raise HttpException(code=code_msg.CODE_PARAMETER_ERROR)

            async def stream():
                current_offset = offset
                last_activity_time = time.time()
                last_keepalive_time = time.time()
                MAX_INACTIVE_TIME = 120  # 120秒无活动超时（复杂 query 需要更长时间）
                KEEPALIVE_INTERVAL = 15  # 每 15 秒发送 SSE keepalive comment

                # 2. 发送已有token
                await cache.listen_cancel()
                
                # 3. 轮询新token和状态
                try:
                    while True:
                        if time.time() - last_activity_time > MAX_INACTIVE_TIME:
                            yield f'{{"sessionId":"{sessionId}","qaId":{qa_id},"type":"SYSTEM","content":null,"status":"FAILED","log":"Connection timeout."}}'
                            break
                        total_tokens = await cache.session_queue.get_token_count()
                        if current_offset <= total_tokens:
                            new_tokens = await cache.session_queue.get_tokens(start=current_offset)
                            for idx, token in enumerate(new_tokens):
                                if cache.is_canceled:
                                    logger.warning("This conversation has been canceled.")
                                    break
                                yield token.decode()
                                last_activity_time = time.time()
                                last_keepalive_time = time.time()
                                current_offset += 1
                        else:
                            # 无新数据时，定期发送 SSE comment 保活（防止代理/LB 超时断连）
                            now = time.time()
                            if now - last_keepalive_time > KEEPALIVE_INTERVAL:
                                yield ServerSentEvent(comment="keepalive")
                                last_keepalive_time = now

                        session_meta = await cache.session_meta.get_session_meta()
                        if session_meta:
                            if cache.is_canceled or session_meta.get(b"status", "") == b"CANCELED":
                                logger.warning("This conversation has been canceled.")
                                break
                            elif session_meta.get(b"status", "") == b"COMPLETED":
                                total_tokens = await cache.session_queue.get_token_count()
                                if current_offset <= total_tokens:
                                    final_tokens = await cache.session_queue.get_tokens(start=current_offset)
                                    for idx, token in enumerate(final_tokens):
                                        yield token.decode()
                                        last_activity_time = time.time()
                                        current_offset += 1
                                break
                        
                        await asyncio.sleep(0.001)
                except Exception as e:
                    logger.exception(f"Error in stream_chat, error: {e}")
                    raise
                finally:
                    await cache.cancel_listener()

            return EventSourceResponse(stream(), media_type="text/event-stream")

        @self._router.post("/chat/query")
        async def chat(
            query: str = Body(..., min_length=1, max_length=30000, description="问句"),
            agentType: AgentType = Body(AgentType.QUICK_REASONING, description="类型"),
            sessionId: str = Body(min_length=32, max_length=32, description="会话ID"),
            extraBody: Optional[Union[str, dict]] = Body(None, description="额外参数"),
            language: str = Body("", min_length=0, max_length=32, description="主站语言"),
            source: Optional[SourceType] = Body(None, description="来源"),
        ):
            """LLM对话"""
            return await self._run_chat_query(
                query=query,
                agentType=agentType,
                sessionId=sessionId,
                extraBody=extraBody,
                language=language,
                source=source,
            )


        @self._router.get("/chat/getFixedMessageBySource")
        def get_fixed_message_by_source(source: str, language: str = "zh_cn", content: str = "") -> str:
            """
            根据 source/language/content 返回固定问句。
            - source: "assert_pnl_analyze" 返回盈亏分析问句
            - source: "news_detail_analyze" 返回新闻分析问句（拼接 content）
            - language 支持多语种，取不到用 en_US 兜底
            """
            msg = ""
            if source in ("assert_pnl_analyze", "news_detail_analyze"):
                # 直接用 source 作为 key 查找
                from libs.language import get_localized_message
                msg = get_localized_message(source, language)
                if source == "news_detail_analyze" and msg:
                    msg = msg.replace("{content}", content or "")
            return msg or ""

        # @self._router.get("/chat/welcome/v2")
        async def welcomeV2(language: str = "en_US", memory_limit: int = 10, greyRelease: str = "A"):
            language_code = language.lower()
            if language_code not in ['zh_cn', 'zh_hk']:
                language_code = language_code.split('_')[0]
            if language_code not in LANGUAGE_CODE_TO_NAME_MAP:
                language_code = 'en'

            language_name, _ = LANGUAGE_CODE_TO_NAME_MAP.get(language_code, ("English", "英语"))

            logger.info(f"Received welcomev2 request, language: {language}, memory_limit: {memory_limit}, greyRelease: {greyRelease}")    

            user_id = None
            try:
                logger.info("Attempting to get user_id from X_USER_ID for welcomeV2 fallback")
                user_id = self.X_USER_ID
                logger.info(f"Got user_id from X_USER_ID: {user_id}")
            except Exception:
                try:
                    logger.info("Attempting to get user_id from self.user_id for welcomeV2 fallback")
                    user_id = self.user_id
                    logger.info(f"Got user_id from self.user_id: {user_id}")
                except Exception:
                    raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

            try:
                if greyRelease == "A":
                    return await self._get_welcome_from_memory(
                        user_id=self.user_id,
                        language_name=language_name,
                        memory_limit=memory_limit,
                    )
                else:
                    return await self._get_welcome_from_external_api(
                        user_id=user_id,
                        language_code=language_code,
                        language_name=language_name,
                    )
            except Exception as e:
                logger.warning(self.log_welcome("welcome_v2_failed", user_id, language_name, error=e))
                raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)
    
                  
        # @self._router.get("/chat/welcome")
        async def welcome(language: str = "en_US", memory_limit: int = 10):
            logger.info(f"Received welcome request, language: {language}, memory_limit: {memory_limit}")    
            language_code = language.lower()
            if language_code not in ['zh_cn', 'zh_hk']:
                language_code = language_code.split('_')[0]
            if language_code not in LANGUAGE_CODE_TO_NAME_MAP:
                language_code = 'en'

            language_name, _ = LANGUAGE_CODE_TO_NAME_MAP.get(language_code, ("English", "英语"))
            memory = Mem0Memory(self.user_id)
            memory_start_time = None
            memory_end_time = None

            try:
                memory_start_time = time.time()
                memories = await memory.get_recent_memories(limit=30)

                memory_end_time = time.time()
                logger.info(f"Get recent filtered memories result: {memories}")

                if memories:
                    if len(memories) > memory_limit:
                        memories = random.sample(memories, memory_limit)
                    llm_start_time = time.time()
                    try:
                        llm_result = await self._call_llm_for_welcome(memories, language_name, self.user_id, memory_start_time,
                                                                      memory_end_time)
                        llm_end_time = time.time()

                        # 检查LLM结果的完整性和有效性
                        if (llm_result and
                                'primary_interest' in llm_result and
                                'welcome_messages' in llm_result and
                                llm_result.get('primary_interest') and
                                isinstance(llm_result.get('welcome_messages'), list) and
                                len(llm_result['welcome_messages']) == 3):

                            logger.info(self.log_welcome("welcome_success", self.user_id, language_name,
                                                         memory_start_time=memory_start_time,
                                                         memory_end_time=memory_end_time, llm_start_time=llm_start_time,
                                                         llm_end_time=llm_end_time))

                            return JsonResponse(content={
                                "welcome_message": llm_result['primary_interest'],
                                "recommended_questions": llm_result['welcome_messages'],
                                "language": language_name,
                            })
                        else:
                            logger.warning(self.log_welcome("llm_incomplete", self.user_id, language_name,
                                                            memory_start_time=memory_start_time,
                                                            memory_end_time=memory_end_time,
                                                            llm_start_time=llm_start_time,
                                                            llm_end_time=llm_end_time, result=str(llm_result)))

                            raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)
                    except Exception as llm_error:
                        llm_end_time = time.time()
                        logger.warning(self.log_welcome("llm_failed", self.user_id, language_name,
                                                        memory_start_time=memory_start_time,
                                                        memory_end_time=memory_end_time,
                                                        llm_start_time=llm_start_time, llm_end_time=llm_end_time,
                                                        error=llm_error))

                        raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)
                else:
                    logger.warning(self.log_welcome("no_memories/new_user", self.user_id, language_name,
                                                    memory_start_time=memory_start_time,
                                                    memory_end_time=memory_end_time))

                    raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)
            except Exception as e:
                # 确保时间变量存在
                log_params = {"error": e}
                if memory_start_time is not None:
                    log_params["memory_start_time"] = memory_start_time
                if memory_end_time is not None:
                    log_params["memory_end_time"] = memory_end_time

                logger.warning(self.log_welcome("memory_failed", self.user_id, language_name, **log_params))
                raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

    @usage_time
    async def _generate_welcome_message_by_queries(
        self,
        queries: List[str],
        language: str,
        user_id: str,
        external_start_time: float,
        external_end_time: float,
        language_code: str = "en",
    ) -> Optional[Dict[str, Any]]:
        """根据推荐问题生成目标语言欢迎语并翻译所有问句
        
        Returns:
            {
                "welcome_message": str,  # 总结性欢迎语
                "translated_queries": List[str]  # 翻译后的问句列表
            }
        """
        # zh_hk/zh_cn 时强调必须用中文输出，避免 LLM 返回英文
        lang_instruction = ""
        if language_code == "zh_hk":
            lang_instruction = (
                "\n\n⚠️ CRITICAL: Target language is 繁體中文 (Traditional Chinese). "
                "You MUST output welcome_message and ALL translated_queries in 繁體中文 only. Do NOT use English.\n"
            )
        elif language_code == "zh_cn":
            lang_instruction = (
                "\n\n⚠️ CRITICAL: Target language is 简体中文 (Simplified Chinese). "
                "You MUST output welcome_message and ALL translated_queries in 简体中文 only. Do NOT use English.\n"
            )

        try:
            api_key = os.environ.get("OPENAI_API_KEY")
            base_url = os.environ.get("OPENAI_API_BASE")
            llm = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=30.0,
                http_client=AsyncClient(verify=False)
            )

            query_text = "\n".join([f"{idx + 1}. {q}" for idx, q in enumerate(queries)])
            prompt = (
                f"You are a crypto assistant. Based on these recommended questions, you need to:\n"
                f"1. Generate ONE short, natural welcome sentence in {language} that summarizes the user's interests\n"
                f"2. Translate each question into {language}\n"
                f"{lang_instruction}"
                f"Recommended questions (in English):\n{query_text}\n\n"
                f"Output MUST be valid JSON with this exact format:\n"
                f'{{"welcome_message": "your welcome sentence in target language", '
                f'"translated_queries": ["translated question 1", "translated question 2", "translated question 3"]}}\n\n'
                f"Output ONLY the JSON, no markdown, no code blocks."
            )

            response = await llm.chat.completions.create(
                model=config.llm_model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.5,
                timeout=getattr(config, 'llm_followup_timeout', 30.0),
                extra_body=None if getattr(config, 'use_azure_openai', False) else {
                    "chat_template_kwargs": {"enable_thinking": False}
                }
            )

            content = (response.choices[0].message.content or "").strip()
            
            # 尝试解析JSON
            try:
                # 移除可能的markdown代码块标记
                if content.startswith('```'):
                    lines = content.split('\n')
                    content = '\n'.join(lines[1:-1]) if len(lines) > 2 else content
                    content = content.replace('```json', '').replace('```', '').strip()
                
                result = json.loads(content)
                
                # 验证返回格式
                if (isinstance(result, dict) and 
                    'welcome_message' in result and 
                    'translated_queries' in result and
                    isinstance(result['translated_queries'], list)):
                    return result
                else:
                    logger.warning(f"LLM returned invalid format: {result}")
                    return None
            except json.JSONDecodeError as je:
                logger.warning(f"Failed to parse LLM JSON response: {content}, error: {je}")
                return None
        except Exception as e:
            logger.warning(self.log_welcome(
                "welcome_v2_llm_internal_failed",
                user_id,
                language,
                external_start_time=external_start_time,
                external_end_time=external_end_time,
                error=e,
            ))
            return None

    @usage_time
    async def _call_llm_for_welcome(self, memories: List[Dict[str, Any]], language: str, user_id: str,
                                    memory_start_time: float, memory_end_time: float) -> Optional[Dict[str, Any]]:
        """调用LLM生成个性化欢迎消息"""
        try:
            # 创建LLM客户端 - 参照base.py中的_create_client方法
            api_key = os.environ.get("OPENAI_API_KEY")
            base_url = os.environ.get("OPENAI_API_BASE")
            llm = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=60.0,
                http_client=AsyncClient(verify=False)
            )

            # 生成prompt
            prompt = welcome_prompt_memory_v2(memories, language)
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "请根据我的记忆生成欢迎语和问题。"}
            ]

            # 调用LLM
            extra_body = None if getattr(config, 'use_azure_openai', False) else {
                "chat_template_kwargs": {"enable_thinking": False},
            }
            response = await llm.chat.completions.create(
                model=config.llm_model_name,
                messages=messages,
                max_tokens=800,
                temperature=0.6,
                timeout=getattr(config, 'llm_followup_timeout', 30.0),
                extra_body=extra_body
            )

            # 解析响应
            content = response.choices[0].message.content.strip()

            # 尝试解析JSON
            json_start = content.find('```json')
            json_end = content.find('```', json_start + 7)

            if json_start != -1 and json_end != -1:
                json_content = content[json_start + 7:json_end].strip()
                return json.loads(json_content)
            else:
                # 如果没有找到JSON代码块，尝试直接解析整个内容
                return json.loads(content)

        except Exception as e:
            logger.warning(self.log_welcome("llm_internal_failed", user_id, language,
                                            memory_start_time=memory_start_time,
                                            memory_end_time=memory_end_time, error=e))
            return None

