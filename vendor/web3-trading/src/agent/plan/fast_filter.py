# -*- coding: utf-8 -*-
"""
FastFilter — zero-LLM pre-dispatch query filter.

Runs in the Gateway *before* any Agent is created.
All checks are backed by Redis or pure regex — no LLM calls.

Checks (in order):
1. Normalise (trim, collapse whitespace, strip emoji)
2. Empty / whitespace-only → reject
3. Greeting detection (sets informational flag; does NOT block)
4. Duplicate detection (same session + same query hash within N seconds)
5. Session-level rate limiting
"""

import hashlib
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Matches emoji in the Supplementary Multilingual Plane (U+1Fxxx) plus
# ZWJ / variation-selector glue characters.  Intentionally excludes the
# BMP (U+0000–U+FFFF) to avoid stripping CJK, Hiragana, Katakana,
# currency symbols, or other meaningful text characters.
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons (😀-🙏)
    "\U0001F300-\U0001F5FF"  # misc symbols & pictographs (🌀-🗿)
    "\U0001F680-\U0001F6FF"  # transport & map (🚀-🛿)
    "\U0001F700-\U0001F77F"  # alchemical symbols
    "\U0001F780-\U0001F7FF"  # geometric shapes extended
    "\U0001F800-\U0001F8FF"  # supplemental arrows-C
    "\U0001F900-\U0001F9FF"  # supplemental symbols & pictographs (🤀-🧿)
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols & pictographs extended-A (🩰-🫿)
    "\U0000FE00-\U0000FE0F"  # variation selectors (emoji presentation)
    "\U0000200D"              # zero-width joiner (used in 👨‍💻 sequences)
    "]+",
    flags=re.UNICODE,
)

_GREETING_RE = re.compile(
    r"^("
    r"h(i|ello|ey|owdy)|"
    r"good\s*(morning|afternoon|evening|day)|"
    r"what'?s?\s*up|yo\b|sup\b|"
    r"你好|您好|嗨|哈喽|早上好|下午好|晚上好|早安|晚安|"
    r"こんにちは|こんばんは|おはよう|"
    r"안녕하세요|안녕|"
    r"hola|buenos?\s*(días|tardes|noches)|"
    r"bonjour|bonsoir|salut|"
    r"привет|здравствуйте|"
    r"مرحبا|السلام عليكم|"
    r"gm\b|gn\b"
    r")[\s!！。.?？~～]*$",
    re.IGNORECASE | re.UNICODE,
)

_REDIS_PREFIX = "kia:fast_filter"


@dataclass
class FilterResult:
    """Result of the pre-dispatch filter."""
    action: str          # "proceed" | "reject" | "duplicate"
    query: str           # normalised query text
    reason: str = ""
    is_greeting: bool = False


class FastFilter:
    """Zero-cost pre-dispatch filter.  All checks use Redis or pure regex."""

    def __init__(
        self,
        dedup_window_sec: int = 10,
        rate_limit_max: int = 30,
        rate_limit_window_sec: int = 60,
    ):
        self._dedup_window = dedup_window_sec
        self._rate_max = rate_limit_max
        self._rate_window = rate_limit_window_sec

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check(
        self,
        query: str,
        session_id: str,
        user_id: str,
    ) -> FilterResult:
        normalized = self._normalize(query)

        if not normalized:
            return FilterResult(action="reject", query="", reason="empty_query")

        is_greeting = bool(_GREETING_RE.match(normalized))

        if await self._is_duplicate_atomic(normalized, session_id):
            return FilterResult(
                action="duplicate", query=normalized,
                reason="duplicate_query", is_greeting=is_greeting,
            )

        if await self._is_rate_limited(session_id):
            return FilterResult(
                action="reject", query=normalized,
                reason="rate_limited", is_greeting=is_greeting,
            )

        return FilterResult(
            action="proceed", query=normalized, is_greeting=is_greeting,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(query: str) -> str:
        if not query:
            return ""
        query = _EMOJI_RE.sub("", query)
        return re.sub(r"\s+", " ", query.strip())

    @staticmethod
    def _dedup_key(query: str, session_id: str) -> str:
        h = hashlib.md5(f"{session_id}:{query.lower()}".encode()).hexdigest()
        return f"{_REDIS_PREFIX}:dedup:{h}"

    @staticmethod
    def _rate_key(session_id: str) -> str:
        return f"{_REDIS_PREFIX}:rate:{session_id}"

    @staticmethod
    def _get_redis():
        from dao.redis_bootstrap import get_redis_client
        return get_redis_client()

    async def _is_duplicate_atomic(self, query: str, session_id: str) -> bool:
        """Atomic check-and-mark: returns True if this query was already seen."""
        try:
            redis = self._get_redis()
            key = self._dedup_key(query, session_id)
            was_set = await redis.set(key, "1", ex=self._dedup_window, nx=True)
            return was_set is None  # None means key already existed → duplicate
        except Exception:
            logger.warning("Redis dedup check failed, falling back to non-duplicate", exc_info=True)
            return False

    async def _is_rate_limited(self, session_id: str) -> bool:
        try:
            redis = self._get_redis()
            key = self._rate_key(session_id)
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, self._rate_window)
            return count > self._rate_max
        except Exception:
            logger.warning("Redis rate-limit check failed, falling back to non-limited", exc_info=True)
            return False


__all__ = ["FastFilter", "FilterResult"]
