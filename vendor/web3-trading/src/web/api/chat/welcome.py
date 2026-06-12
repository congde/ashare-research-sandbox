# -*- coding: utf-8 -*-
import json
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from httpx import AsyncClient
from openai import AsyncOpenAI

from libs import http
from libs.language import LANGUAGE_CODE_TO_NAME_MAP
from libs.wrapper import usage_time
from memory.mem0 import Mem0Memory
from web import code_msg
from web.config import config, is_risk_control_enabled
from web.exceptions import HttpException
from web.response import JsonResponse
from web.router import BaseRouter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FALLBACK_QUESTIONS: Dict[str, List[str]] = {
    "zh_hk": [
        "如何選擇適合新手的加密貨幣組合？",
        "如何分析市場趨勢優化投資決策？",
        "分散加密資產的最佳策略有哪些？",
    ],
    "zh_cn": [
        "如何选择适合新手的加密货币组合？",
        "如何分析市场趋势优化投资决策？",
        "分散加密资产的最佳策略有哪些？",
    ],
}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _normalize_language(language: str) -> Tuple[str, str]:
    """Normalise a locale tag to ``(language_code, language_name)``."""
    code = language.lower()
    if code not in ("zh_cn", "zh_hk"):
        code = code.split("_")[0]
    if code not in LANGUAGE_CODE_TO_NAME_MAP:
        code = "en"
    name, _ = LANGUAGE_CODE_TO_NAME_MAP.get(code, ("English", "英语"))
    return code, name


def _strip_markdown_json(content: str) -> str:
    """Remove markdown code-fence wrappers from an LLM JSON response."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        inner = lines[1:-1] if len(lines) > 2 else lines
        content = "\n".join(inner).replace("```json", "").replace("```", "").strip()
    return content


def _is_valid_welcome_result(result: Any) -> bool:
    """Return ``True`` if *result* is a well-formed welcome LLM payload."""
    return (
        isinstance(result, dict)
        and bool(result.get("primary_interest"))
        and isinstance(result.get("welcome_messages"), list)
        and len(result["welcome_messages"]) == 3
    )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_welcome_prompt(memory: List[Dict[str, Any]], language: str = "English") -> str:
    """Build the LLM system prompt for memory-based personalised welcome generation."""
    memory_str = os.linesep.join(
        f'{i}. "{mem.get("memory", "")}"' for i, mem in enumerate(memory, 1)
    )

    if "Chinese" in language:
        question_constraint = "Each question: max 20 characters"
        interest_constraint = "Primary interest: max 50 characters"
    elif "Japanese" in language:
        question_constraint = "Each question: max 25 characters"
        interest_constraint = "Primary interest: max 60 characters"
    elif "Korean" in language:
        question_constraint = "Each question: max 25 characters"
        interest_constraint = "Primary interest: max 60 characters"
    elif "Arabic" in language:
        question_constraint = "Each question: max 20 words"
        interest_constraint = "Primary interest: max 50 words"
    elif any(lang in language for lang in ("Thai", "Hindi", "Bengali", "Urdu")):
        question_constraint = "Each question: max 25 words"
        interest_constraint = "Primary interest: max 60 words"
    elif any(lang in language for lang in ("German", "Dutch")):
        question_constraint = "Each question: max 18 words"
        interest_constraint = "Primary interest: max 45 words"
    elif any(lang in language for lang in ("Vietnamese", "Indonesian", "Malay", "Filipino")):
        question_constraint = "Each question: max 20 words"
        interest_constraint = "Primary interest: max 50 words"
    else:
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


# ---------------------------------------------------------------------------
# WelcomeApi
# ---------------------------------------------------------------------------

class WelcomeApi(BaseRouter):
    """Handles /api/chat/welcome and /api/chat/welcome/v2 endpoints."""

    def __init__(self):
        super().__init__()
        from llm.shield.handler import llm_shield
        self._llm_shield = llm_shield

        @self._router.get("/chat/welcome")
        async def welcome(language: str = "en_US", memory_limit: int = 10):
            """V1: memory-based welcome; recommended_questions is a plain list of strings."""
            _, language_name = _normalize_language(language)
            logger.info(f"welcome request: language={language}, memory_limit={memory_limit}")
            try:
                data = await self._fetch_welcome_data(self.user_id, language_name, memory_limit)
                return JsonResponse(content={
                    "welcome_message": data["primary_interest"],
                    "recommended_questions": data["welcome_messages"],
                    "language": language_name,
                })
            except HttpException:
                raise
            except Exception as e:
                logger.warning(self._log("memory_failed", self.user_id, language_name, error=e))
                raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)


        @self._router.get("/chat/welcome/v2")
        async def welcome_v2(language: str = "en_US", memory_limit: int = 10, greyRelease: str = "A", source: Optional[str] = None):
            """V2: greyRelease A uses memory pipeline, B uses external recommendation API. If source==CURRENCY_SELECTION_RECOMMEND, return fixed recommend questions and welcome."""
            from libs.language import get_localized_message
            language_code, language_name = _normalize_language(language)
            logger.info(
                f"welcome/v2 request: language={language}, memory_limit={memory_limit}, greyRelease={greyRelease}, source={source}"
            )

            # 新增：币种推荐特殊处理
            if source == "CURRENCY_SELECTION_RECOMMEND":
                return self._get_currency_selection_recommend(language_code)

            # X_USER_ID is required for the external API path; fall back to user_id
            try:
                user_id = self.X_USER_ID
            except Exception:
                try:
                    user_id = self.user_id
                except Exception:
                    raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

            try:
                if greyRelease == "A":
                    return await self._get_welcome_from_memory(
                        self.user_id, language_name, memory_limit
                    )
                return await self._get_welcome_from_external_api(
                    user_id, language_code, language_name
                )
            except HttpException:
                raise
            except Exception as e:
                logger.warning(self._log("welcome_v2_failed", user_id, language_name, error=e))
                raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _log(self, event: str, user_id: str, language: str, **kwargs) -> str:
        """Format a structured log line; computes *_cost_ms from paired timestamps."""
        if "memory_start_time" in kwargs and "memory_end_time" in kwargs:
            kwargs["memory_cost_ms"] = int(
                (kwargs["memory_end_time"] - kwargs["memory_start_time"]) * 1000
            )
        if "llm_start_time" in kwargs and "llm_end_time" in kwargs:
            kwargs["llm_cost_ms"] = int(
                (kwargs["llm_end_time"] - kwargs["llm_start_time"]) * 1000
            )
        base = f"event: {event}, user_id: {user_id}, language: {language}"
        extra = ", ".join(f"{k}: {v}" for k, v in kwargs.items())
        return f"{base}, {extra}" if extra else base

    @staticmethod
    def _create_llm_client(timeout: float = 60.0) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_API_BASE"),
            timeout=timeout,
            http_client=AsyncClient(verify=False),
        )

    @staticmethod
    def _llm_extra_body() -> Optional[Dict[str, Any]]:
        if getattr(config, "use_azure_openai", False):
            return None
        return {"chat_template_kwargs": {"enable_thinking": False}}

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    @usage_time
    async def _call_llm_for_welcome(
        self,
        memories: List[Dict[str, Any]],
        language: str,
        user_id: str,
        memory_start_time: float,
        memory_end_time: float,
    ) -> Optional[Dict[str, Any]]:
        """Call LLM to generate a personalised welcome message from user memories."""
        try:
            response = await self._create_llm_client(timeout=60.0).chat.completions.create(
                model=config.llm_model_name,
                messages=[
                    {"role": "system", "content": _build_welcome_prompt(memories, language)},
                    {"role": "user", "content": "请根据我的记忆生成欢迎语和问题。"},
                ],
                max_tokens=800,
                temperature=0.6,
                timeout=getattr(config, "llm_followup_timeout", 30.0),
                extra_body=self._llm_extra_body(),
            )
            content = _strip_markdown_json(response.choices[0].message.content or "")
            return json.loads(content)
        except Exception as e:
            logger.warning(
                self._log(
                    "llm_internal_failed", user_id, language,
                    memory_start_time=memory_start_time,
                    memory_end_time=memory_end_time,
                    error=e,
                )
            )
            return None

    @usage_time
    async def _generate_welcome_message_by_queries(
        self,
        queries: List[str],
        language: str,
        language_code: str,
        user_id: str,
        external_start_time: float,
        external_end_time: float,
    ) -> Optional[Dict[str, Any]]:
        """Translate recommended questions and generate a welcome sentence in the target language."""
        lang_instruction = {
            "zh_hk": (
                "\n\n⚠️ CRITICAL: Target language is 繁體中文 (Traditional Chinese). "
                "You MUST output welcome_message and ALL translated_queries in 繁體中文 only. Do NOT use English.\n"
            ),
            "zh_cn": (
                "\n\n⚠️ CRITICAL: Target language is 简体中文 (Simplified Chinese). "
                "You MUST output welcome_message and ALL translated_queries in 简体中文 only. Do NOT use English.\n"
            ),
        }.get(language_code, "")

        query_text = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(queries))
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
        try:
            response = await self._create_llm_client(timeout=30.0).chat.completions.create(
                model=config.llm_model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.5,
                timeout=getattr(config, "llm_followup_timeout", 30.0),
                extra_body=self._llm_extra_body(),
            )
            content = _strip_markdown_json(response.choices[0].message.content or "")
            result = json.loads(content)
            if isinstance(result, dict) and isinstance(result.get("translated_queries"), list):
                return result
            logger.warning(f"LLM returned invalid format: {result}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM JSON response: {e}")
            return None
        except Exception as e:
            logger.warning(
                self._log(
                    "welcome_v2_llm_internal_failed", user_id, language,
                    external_start_time=external_start_time,
                    external_end_time=external_end_time,
                    error=e,
                )
            )
            return None

    # ------------------------------------------------------------------
    # Welcome pipelines
    # ------------------------------------------------------------------

    async def _fetch_welcome_data(
        self,
        user_id: str,
        language_name: str,
        memory_limit: int,
    ) -> Dict[str, Any]:
        """Fetch memories → call LLM; returns raw payload or raises HttpException."""
        memory_start = time.time()
        memories = await Mem0Memory(user_id).get_recent_memories(limit=30)
        memory_end = time.time()

        if not memories:
            logger.warning(
                self._log("no_memories/new_user", user_id, language_name,
                          memory_start_time=memory_start, memory_end_time=memory_end)
            )
            raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

        if len(memories) > memory_limit:
            memories = random.sample(memories, memory_limit)

        llm_start = time.time()
        llm_result = await self._call_llm_for_welcome(
            memories, language_name, user_id, memory_start, memory_end
        )
        llm_end = time.time()

        if _is_valid_welcome_result(llm_result):
            logger.info(
                self._log("welcome_success", user_id, language_name,
                          memory_start_time=memory_start, memory_end_time=memory_end,
                          llm_start_time=llm_start, llm_end_time=llm_end)
            )
            return llm_result

        logger.warning(
            self._log("llm_incomplete", user_id, language_name,
                      memory_start_time=memory_start, memory_end_time=memory_end,
                      llm_start_time=llm_start, llm_end_time=llm_end,
                      result=str(llm_result))
        )
        raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

    def _get_currency_selection_recommend(self, language_code: str) -> JsonResponse:
            from libs.language import get_localized_message
            welcome_text = get_localized_message("currency_selection_recommend_welcome", language_code)
            questions_str = get_localized_message("currency_selection_recommend_questions", language_code)
            # 如果当前语言取不到，自动用en_US兜底
            if not welcome_text:
                welcome_text = get_localized_message("currency_selection_recommend_welcome", "en_us")
            if not questions_str:
                questions_str = get_localized_message("currency_selection_recommend_questions", "en_us")
            questions = [q.strip() for q in questions_str.split("|") if q.strip()]
            import random
            questions = random.sample(questions, 3) if len(questions) > 3 else questions
            return JsonResponse(content={
                "welcome_message": welcome_text,
                "recommended_questions": [
                    {"lightIcon": "", "darkIcon": "", "query": q} for q in questions
                ],
                "language": language_code,
            })
    
    async def _get_welcome_from_memory(
        self,
        user_id: str,
        language_name: str,
        memory_limit: int,
    ) -> JsonResponse:
        """V2 format: recommended_questions as list of {lightIcon, darkIcon, query} dicts."""
        data = await self._fetch_welcome_data(user_id, language_name, memory_limit)
        return JsonResponse(content={
            "welcome_message": data["primary_interest"],
            "recommended_questions": [
                {"lightIcon": "", "darkIcon": "", "query": q}
                for q in data["welcome_messages"]
            ],
            "language": language_name,
        })

    async def _get_welcome_from_external_api(
        self,
        user_id: str,
        language_code: str,
        language_name: str,
    ) -> JsonResponse:
        """Call external recommendation API and build a welcome response."""
        import base64
        import datetime
        from Crypto.Cipher import PKCS1_v1_5
        from Crypto.PublicKey import RSA

        recommend_url = getattr(config, "welcome_recommend_api_url", None)
        logger.info(
            f"Calling external recommend API: url={recommend_url}, "
            f"user_id={user_id}, language={language_name}"
        )

        # Collect MS-Token candidates: RSA-encrypted > config static > hardcoded fallback
        ms_tokens: List[str] = []
        public_key = getattr(config, "ms_token_public_key", None)
        if public_key:
            try:
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                payload = f'{{"app_id":"big-data","trace_id":"{user_id}","timestamp":"{now}"}}'
                cipher = PKCS1_v1_5.new(RSA.importKey(public_key))
                ms_tokens.append(base64.b64encode(cipher.encrypt(payload.encode())).decode())
            except Exception as e:
                logger.warning(f"[MS-Token] RSA generation failed: {e}")
        else:
            logger.warning("[MS-Token] public_key not configured, skipping RSA token")

        if config_token := getattr(config, "ms_token", None):
            ms_tokens.append(config_token)

        # TODO: remove this hardcoded fallback once gateway team confirms
        ms_tokens.append(
            "K+Eky7Ob9sFMZ6NMTqIRhirTpnB6VW1VPr46E+rH+YwZ8q0HzYwnX54bipp"
            "/A2IJsHIN3cGN4cqPgjG4ApV8ACwk0bwZu66N+BD/wZnS/oKAKIjmGOWyIiGI"
            "BUZ2rPAXisRHd9hrjlL6TduiLwj6gYYAs6yEokd0n3H2F4J9L2I="
        )

        external_start = time.time()
        resp = None
        for idx, token in enumerate(ms_tokens):
            try:
                resp = await http.get(
                    recommend_url,
                    headers={"X-USER-ID": user_id, "MS-Token": token},
                )
                if resp and resp.get("success") and str(resp.get("code")) == "200":
                    break
            except Exception as e:
                logger.warning(f"[MS-Token] attempt {idx + 1} failed: {e}")
        external_end = time.time()

        if not (resp and resp.get("success") and str(resp.get("code")) == "200"):
            logger.warning(
                self._log("welcome_v2_remote_failed", user_id, language_name,
                          external_start_time=external_start, external_end_time=external_end,
                          remote_code=resp.get("code") if resp else None,
                          remote_msg=resp.get("msg") if resp else None)
            )
            raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

        recommended_questions: List[Dict] = (
            (resp.get("data") or {}).get("recommendedQuestions") or []
        )
        if not recommended_questions:
            logger.warning(
                self._log("welcome_v2_empty_questions", user_id, language_name,
                          external_start_time=external_start, external_end_time=external_end)
            )
            raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

        # Risk-check the recommended questions（risk_control_enabled=false 时跳过）
        questions_text = "\n".join(
            q.get("query", "") for q in recommended_questions if isinstance(q, dict)
        )
        try:
            if is_risk_control_enabled():
                risk_result = (
                    await self._llm_shield.check(questions_text, language_code)
                    if config.risk_enable
                    else self._llm_shield._local_sensitive_check(questions_text, language_code)
                )
                if risk_result.has_risk and risk_result.should_terminate:
                    logger.warning(
                        self._log("welcome_v2_risk_detected", user_id, language_name,
                                  external_start_time=external_start, external_end_time=external_end,
                                  risk=risk_result.risk_category)
                    )
                    raise HttpException(
                        code=code_msg.CODE_PARAMETER_ERROR,
                        msg=risk_result.fallback_message,
                    )
        except HttpException:
            raise
        except Exception as e:
            logger.exception(
                self._log("welcome_v2_risk_error", user_id, language_name,
                          external_start_time=external_start, external_end_time=external_end,
                          error=e)
            )
            raise HttpException(code=code_msg.CODE_WELCOME_MESSAGE_NOT_FOUND)

        # Generate welcome sentence and translate questions to target language
        welcome_message = "您好！我是您的加密貨幣AI助手。請問有什麼問題嗎？"
        llm_start = llm_end = time.time()
        try:
            llm_result = await self._generate_welcome_message_by_queries(
                queries=[
                    q["query"] for q in recommended_questions
                    if isinstance(q, dict) and q.get("query")
                ],
                language=language_name,
                language_code=language_code,
                user_id=user_id,
                external_start_time=external_start,
                external_end_time=external_end,
            )
            llm_end = time.time()

            if (
                llm_result
                and isinstance(llm_result.get("translated_queries"), list)
                and len(llm_result["translated_queries"]) == len(recommended_questions)
            ):
                welcome_message = llm_result["welcome_message"]
                for idx, q_obj in enumerate(recommended_questions):
                    if isinstance(q_obj, dict):
                        q_obj["query"] = llm_result["translated_queries"][idx]
            else:
                logger.warning("LLM returned invalid result; using fallback questions")
                fallback = _FALLBACK_QUESTIONS.get(language_code, [])
                for idx, q_obj in enumerate(recommended_questions):
                    if isinstance(q_obj, dict) and idx < len(fallback):
                        q_obj["query"] = fallback[idx]
        except Exception as e:
            llm_end = time.time()
            logger.warning(
                self._log("llm_failed", user_id, language_name,
                          external_start_time=external_start, external_end_time=external_end,
                          llm_start_time=llm_start, llm_end_time=llm_end, error=e)
            )

        logger.info(
            self._log("welcome_v2_success", user_id, language_name,
                      external_start_time=external_start, external_end_time=external_end,
                      llm_start_time=llm_start, llm_end_time=llm_end,
                      question_count=len(recommended_questions))
        )
        return JsonResponse(content={
            "welcome_message": welcome_message,
            "recommended_questions": recommended_questions,
            "language": language_code,
        })
