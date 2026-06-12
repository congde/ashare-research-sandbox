"""
Session-level Token Quota Manager (§7.2 P5)

Three-level token quota hierarchy:
  1. User quota    — per-user daily/monthly soft limits
  2. Workspace quota — per-workspace daily limits (shared across users)
  3. Session quota — per-session turn-scoped limits (hard cap)

Quota enforcement is advisory (soft limit = warn, hard limit = stop).
The manager tracks cumulative token usage per scope and checks quota
before each LLM call. On quota breach:
  - Soft limit: inject budget_warning into context, allow call
  - Hard limit: yield quota_exceeded, stop the agent loop

Persistence:
  - Redis for real-time counters (fast check, TTL = 25h for daily reset)
  - MongoDB for audit trail (daily usage snapshots)

Integration:
  - Called from ConversationRuntime.wrap_agent_stream() before each LLM call
  - Gate: ModuleToggles.token_quota (default: enabled)
  - Config: runtime.budget.token_quota in conf/default.yaml
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class QuotaLevel(str, Enum):
    """Quota enforcement level."""
    OK = "ok"               # within soft limit
    SOFT_LIMIT = "soft"     # between soft and hard limit (warn)
    HARD_LIMIT = "hard"     # at or above hard limit (block)


@dataclass
class QuotaConfig:
    """Configuration for the 3-level token quota system."""
    # User-level quotas (per user per day)
    user_daily_soft: int = 500_000       # 500K tokens
    user_daily_hard: int = 1_000_000     # 1M tokens
    user_monthly_soft: int = 10_000_000  # 10M tokens
    user_monthly_hard: int = 20_000_000  # 20M tokens

    # Workspace-level quotas (per workspace per day)
    workspace_daily_soft: int = 2_000_000   # 2M tokens
    workspace_daily_hard: int = 5_000_000   # 5M tokens

    # Session-level quotas (per session per turn)
    session_turn_soft: int = 50_000     # 50K tokens per turn
    session_turn_hard: int = 100_000    # 100K tokens per turn
    session_total_soft: int = 500_000   # 500K tokens per session
    session_total_hard: int = 1_000_000 # 1M tokens per session

    # Redis TTL for daily counters (seconds) — 25h to cover timezone drift
    daily_counter_ttl: int = 90_000

    # Whether to enforce hard limits (block calls) or just warn
    enforce_hard_limit: bool = True

    @classmethod
    def from_config(cls, cfg: Optional[Dict[str, Any]] = None) -> "QuotaConfig":
        """Build from conf/default.yaml runtime.budget.token_quota dict."""
        if not cfg:
            return cls()
        return cls(
            user_daily_soft=cfg.get("user_daily_soft", cls.user_daily_soft),
            user_daily_hard=cfg.get("user_daily_hard", cls.user_daily_hard),
            user_monthly_soft=cfg.get("user_monthly_soft", cls.user_monthly_soft),
            user_monthly_hard=cfg.get("user_monthly_hard", cls.user_monthly_hard),
            workspace_daily_soft=cfg.get("workspace_daily_soft", cls.workspace_daily_soft),
            workspace_daily_hard=cfg.get("workspace_daily_hard", cls.workspace_daily_hard),
            session_turn_soft=cfg.get("session_turn_soft", cls.session_turn_soft),
            session_turn_hard=cfg.get("session_turn_hard", cls.session_turn_hard),
            session_total_soft=cfg.get("session_total_soft", cls.session_total_soft),
            session_total_hard=cfg.get("session_total_hard", cls.session_total_hard),
            daily_counter_ttl=cfg.get("daily_counter_ttl", cls.daily_counter_ttl),
            enforce_hard_limit=cfg.get("enforce_hard_limit", cls.enforce_hard_limit),
        )


@dataclass
class QuotaCheckResult:
    """Result of a quota check operation."""
    level: QuotaLevel = QuotaLevel.OK
    scope: str = ""                    # "user_daily", "workspace_daily", "session_turn", etc.
    used: int = 0                      # current usage
    limit: int = 0                     # the limit that was checked
    message: str = ""                  # human-readable message

    @property
    def is_ok(self) -> bool:
        return self.level == QuotaLevel.OK

    @property
    def is_hard_limit(self) -> bool:
        return self.level == QuotaLevel.HARD_LIMIT

    @property
    def usage_ratio(self) -> float:
        return round(self.used / max(self.limit, 1), 4)


class TokenQuotaManager:
    """
    Three-level token quota manager.

    Tracks cumulative token usage at user, workspace, and session scopes.
    Uses Redis for real-time counters with auto-expiring daily keys.
    Falls back to in-memory counters if Redis is unavailable.
    """

    def __init__(
        self,
        config: Optional[QuotaConfig] = None,
        redis_client=None,
    ):
        self._config = config or QuotaConfig()
        self._redis = redis_client

        # In-memory fallback counters when Redis is unavailable
        # Key format: "scope:entity_id:period" → int
        self._memory_counters: Dict[str, int] = {}
        # Session-scoped counters (always in-memory, short-lived)
        self._session_counters: Dict[str, int] = {}
        # Session turn counters (reset each turn)
        self._session_turn_counters: Dict[str, int] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    async def check_quota(
        self,
        user_id: str,
        workspace_id: str,
        session_id: str,
        estimated_tokens: int = 0,
    ) -> QuotaCheckResult:
        """
        Check all 3 quota levels for the given scope.

        Returns the *most restrictive* result (hard > soft > ok).
        If estimated_tokens > 0, also checks whether adding that many
        tokens would exceed any limit.
        """
        results = []

        # 1. User daily quota
        r = await self._check_user_daily(user_id, estimated_tokens)
        results.append(r)
        if r.is_hard_limit:
            return r  # short-circuit

        # 2. User monthly quota
        r = await self._check_user_monthly(user_id, estimated_tokens)
        results.append(r)
        if r.is_hard_limit:
            return r

        # 3. Workspace daily quota
        r = await self._check_workspace_daily(workspace_id, estimated_tokens)
        results.append(r)
        if r.is_hard_limit:
            return r

        # 4. Session total quota (in-memory counters — sync helpers)
        r = self._check_session_total(session_id, estimated_tokens)
        results.append(r)
        if r.is_hard_limit:
            return r

        # 5. Session turn quota
        r = self._check_session_turn(session_id, estimated_tokens)
        results.append(r)
        if r.is_hard_limit:
            return r

        # Return the most restrictive (first non-OK in priority order)
        for r in results:
            if not r.is_ok:
                return r
        return results[0] if results else QuotaCheckResult(level=QuotaLevel.OK)

    async def record_usage(
        self,
        user_id: str,
        workspace_id: str,
        session_id: str,
        tokens: int,
    ) -> None:
        """
        Record actual token usage after an LLM call completes.

        Updates counters at all 3 levels (user, workspace, session).
        Fire-and-forget — errors are logged but never block the agent.
        """
        if tokens <= 0:
            return
        try:
            # User daily
            await self._increment_counter(
                f"user:daily:{user_id}:{self._today_key()}",
                tokens,
                ttl=self._config.daily_counter_ttl,
            )
            # User monthly
            await self._increment_counter(
                f"user:monthly:{user_id}:{self._month_key()}",
                tokens,
                ttl=self._config.daily_counter_ttl * 31,  # ~31 days
            )
            # Workspace daily
            await self._increment_counter(
                f"ws:daily:{workspace_id}:{self._today_key()}",
                tokens,
                ttl=self._config.daily_counter_ttl,
            )
            # Session total (in-memory, no TTL)
            self._session_counters[session_id] = (
                self._session_counters.get(session_id, 0) + tokens
            )
            # Session turn (in-memory, reset per turn)
            self._session_turn_counters[session_id] = (
                self._session_turn_counters.get(session_id, 0) + tokens
            )
        except Exception as e:
            logger.warning("TokenQuotaManager: record_usage failed: %s", e)

    def reset_turn(self, session_id: str) -> None:
        """Reset per-turn counter at the start of a new turn."""
        self._session_turn_counters.pop(session_id, None)

    def reset_session(self, session_id: str) -> None:
        """Reset all session counters (on session end)."""
        self._session_counters.pop(session_id, None)
        self._session_turn_counters.pop(session_id, None)

    def get_session_usage(self, session_id: str) -> Dict[str, int]:
        """Return current session usage for dashboard display."""
        return {
            "total": self._session_counters.get(session_id, 0),
            "turn": self._session_turn_counters.get(session_id, 0),
        }

    # ── Scope-specific checks ──────────────────────────────────────────────

    async def _check_user_daily(self, user_id: str, estimated: int) -> QuotaCheckResult:
        used = await self._get_counter(f"user:daily:{user_id}:{self._today_key()}")
        projected = used + estimated
        if projected >= self._config.user_daily_hard:
            return QuotaCheckResult(
                level=QuotaLevel.HARD_LIMIT,
                scope="user_daily",
                used=projected,
                limit=self._config.user_daily_hard,
                message=f"User daily token quota exceeded ({projected:,}/{self._config.user_daily_hard:,})",
            )
        if projected >= self._config.user_daily_soft:
            return QuotaCheckResult(
                level=QuotaLevel.SOFT_LIMIT,
                scope="user_daily",
                used=projected,
                limit=self._config.user_daily_soft,
                message=f"User daily token quota warning ({projected:,}/{self._config.user_daily_soft:,})",
            )
        return QuotaCheckResult(level=QuotaLevel.OK, scope="user_daily", used=projected, limit=self._config.user_daily_hard)

    async def _check_user_monthly(self, user_id: str, estimated: int) -> QuotaCheckResult:
        used = await self._get_counter(f"user:monthly:{user_id}:{self._month_key()}")
        projected = used + estimated
        if projected >= self._config.user_monthly_hard:
            return QuotaCheckResult(
                level=QuotaLevel.HARD_LIMIT,
                scope="user_monthly",
                used=projected,
                limit=self._config.user_monthly_hard,
                message=f"User monthly token quota exceeded ({projected:,}/{self._config.user_monthly_hard:,})",
            )
        if projected >= self._config.user_monthly_soft:
            return QuotaCheckResult(
                level=QuotaLevel.SOFT_LIMIT,
                scope="user_monthly",
                used=projected,
                limit=self._config.user_monthly_soft,
                message=f"User monthly token quota warning ({projected:,}/{self._config.user_monthly_soft:,})",
            )
        return QuotaCheckResult(level=QuotaLevel.OK, scope="user_monthly", used=projected, limit=self._config.user_monthly_hard)

    async def _check_workspace_daily(self, workspace_id: str, estimated: int) -> QuotaCheckResult:
        used = await self._get_counter(f"ws:daily:{workspace_id}:{self._today_key()}")
        projected = used + estimated
        if projected >= self._config.workspace_daily_hard:
            return QuotaCheckResult(
                level=QuotaLevel.HARD_LIMIT,
                scope="workspace_daily",
                used=projected,
                limit=self._config.workspace_daily_hard,
                message=f"Workspace daily token quota exceeded ({projected:,}/{self._config.workspace_daily_hard:,})",
            )
        if projected >= self._config.workspace_daily_soft:
            return QuotaCheckResult(
                level=QuotaLevel.SOFT_LIMIT,
                scope="workspace_daily",
                used=projected,
                limit=self._config.workspace_daily_soft,
                message=f"Workspace daily token quota warning ({projected:,}/{self._config.workspace_daily_soft:,})",
            )
        return QuotaCheckResult(level=QuotaLevel.OK, scope="workspace_daily", used=projected, limit=self._config.workspace_daily_hard)

    def _check_session_total(self, session_id: str, estimated: int) -> QuotaCheckResult:
        used = self._session_counters.get(session_id, 0)
        projected = used + estimated
        if projected >= self._config.session_total_hard:
            return QuotaCheckResult(
                level=QuotaLevel.HARD_LIMIT,
                scope="session_total",
                used=projected,
                limit=self._config.session_total_hard,
                message=f"Session token quota exceeded ({projected:,}/{self._config.session_total_hard:,})",
            )
        if projected >= self._config.session_total_soft:
            return QuotaCheckResult(
                level=QuotaLevel.SOFT_LIMIT,
                scope="session_total",
                used=projected,
                limit=self._config.session_total_soft,
                message=f"Session token quota warning ({projected:,}/{self._config.session_total_soft:,})",
            )
        return QuotaCheckResult(level=QuotaLevel.OK, scope="session_total", used=projected, limit=self._config.session_total_hard)

    def _check_session_turn(self, session_id: str, estimated: int) -> QuotaCheckResult:
        used = self._session_turn_counters.get(session_id, 0)
        projected = used + estimated
        if projected >= self._config.session_turn_hard:
            return QuotaCheckResult(
                level=QuotaLevel.HARD_LIMIT,
                scope="session_turn",
                used=projected,
                limit=self._config.session_turn_hard,
                message=f"Turn token quota exceeded ({projected:,}/{self._config.session_turn_hard:,})",
            )
        if projected >= self._config.session_turn_soft:
            return QuotaCheckResult(
                level=QuotaLevel.SOFT_LIMIT,
                scope="session_turn",
                used=projected,
                limit=self._config.session_turn_soft,
                message=f"Turn token quota warning ({projected:,}/{self._config.session_turn_soft:,})",
            )
        return QuotaCheckResult(level=QuotaLevel.OK, scope="session_turn", used=projected, limit=self._config.session_turn_hard)

    # ── Redis helpers ──────────────────────────────────────────────────────

    async def _get_counter(self, key: str) -> int:
        """Get counter value from Redis (or in-memory fallback)."""
        if self._redis:
            try:
                val = await self._redis.get(key)
                return int(val) if val else 0
            except Exception as e:
                logger.debug("TokenQuotaManager: Redis GET failed for %s: %s", key, e)
        return self._memory_counters.get(key, 0)

    async def _increment_counter(self, key: str, amount: int, ttl: int = 0) -> None:
        """Increment counter in Redis (or in-memory fallback) with optional TTL."""
        if self._redis:
            try:
                pipe = self._redis.pipeline()
                pipe.incrby(key, amount)
                if ttl > 0:
                    pipe.expire(key, ttl)
                await pipe.execute()
                return
            except Exception as e:
                logger.debug("TokenQuotaManager: Redis INCR failed for %s: %s", key, e)
        # In-memory fallback
        self._memory_counters[key] = self._memory_counters.get(key, 0) + amount

    # ── Time helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _today_key() -> str:
        """Return YYYY-MM-DD for daily counter key."""
        from datetime import datetime
        return datetime.utcnow().strftime("%Y-%m-%d")

    @staticmethod
    def _month_key() -> str:
        """Return YYYY-MM for monthly counter key."""
        from datetime import datetime
        return datetime.utcnow().strftime("%Y-%m")


# ──── Singleton ────

_manager: Optional[TokenQuotaManager] = None


def get_token_quota_manager(config: Optional[Dict[str, Any]] = None) -> TokenQuotaManager:
    """Get or create the global TokenQuotaManager singleton."""
    global _manager
    if _manager is None:
        cfg = QuotaConfig.from_config(config)
        # Try to get Redis client from ComponentService
        redis_client = None
        try:
            from web.component import component
            redis_client = component.get("redis")  # type: ignore[assignment]
        except Exception:
            pass
        _manager = TokenQuotaManager(config=cfg, redis_client=redis_client)
    return _manager


def reset_token_quota_manager() -> None:
    """Reset the singleton (for testing)."""
    global _manager
    _manager = None
