"""
FallbackManager — turn-scoped model fallback (§5.7)

On each turn start, restores primary model.
On LLM error, degrades through the fallback chain:
  primary → fallback_1 → fallback_2 → hard error

Attribution fields: requested_model, model_name, is_fallback, fallback_attempt

Design invariants:
  • Fallback is TURN-SCOPED — the primary model is restored at the start of
    every new turn so a single 503 never permanently pins the runtime to a
    fallback model.
  • The _primary snapshot captures the FULL runtime state
    (model, provider, base_url, api_mode, api_key) so restore is complete.
  • Cost records must record both requested_model and actual model_name to
    support attribution queries (§14.8 cost_records).
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class FallbackConfig:
    """
    Configuration for one model in the fallback chain.

    Attributes
    ----------
    model : str
        Model identifier (e.g. "qwen3-5-27b-instruct").
    provider : str
        LLM provider name as understood by LiteLLM (e.g. "openai", "azure").
    base_url : str
        API endpoint base URL.
    api_key : str
        API key for this provider/model.
    api_mode : str
        Calling mode, e.g. "chat" or "completion".
    extra : dict
        Any additional provider-specific parameters.
    """

    model: str
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    api_mode: str = "chat"
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "api_mode": self.api_mode,
            "extra": copy.deepcopy(self.extra),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FallbackConfig":
        return cls(
            model=d.get("model", ""),
            provider=d.get("provider", ""),
            base_url=d.get("base_url", ""),
            api_key=d.get("api_key", ""),
            api_mode=d.get("api_mode", "chat"),
            extra=copy.deepcopy(d.get("extra", {})),
        )


@dataclass
class FallbackAttribution:
    """
    Attribution metadata for cost/audit records.

    Included in every LLM call's cost record so downstream analytics can
    distinguish "primary model calls" from "fallback calls" and track which
    requested model was actually served.
    """

    requested_model: str  # what the agent originally asked for
    model_name: str  # what was actually called
    is_fallback: bool
    fallback_attempt: int  # 0 = primary, 1 = first fallback, etc.


class AllFallbacksExhaustedError(Exception):
    """Raised when all fallback options have been tried and all failed."""

    def __init__(self, primary_model: str, attempts: int):
        self.primary_model = primary_model
        self.attempts = attempts
        super().__init__(
            f"All {attempts} fallback(s) exhausted for primary model '{primary_model}'. No more options available."
        )


class FallbackManager:
    """
    Turn-scoped model fallback manager.

    Wraps the LLM runtime configuration and provides:
      • ``restore_primary()``  — called at the *start* of every new turn
      • ``try_fallback()``     — called when the current model fails
      • ``get_attribution()``  — attribution metadata for cost records

    Usage::

        mgr = FallbackManager(
            primary=FallbackConfig(model="qwen3-5-27b", ...),
            chain=[FallbackConfig(model="qwen3-5-14b", ...)],
        )

        # At the start of each turn:
        mgr.restore_primary()

        # In the LLM error handler:
        if not mgr.try_fallback():
            raise AllFallbacksExhaustedError(...)
        # Now rebuild LLM client with mgr.current
    """

    def __init__(
        self,
        primary: FallbackConfig,
        chain: Optional[list[FallbackConfig]] = None,
    ):
        self._primary = copy.deepcopy(primary)
        self._chain: list[FallbackConfig] = copy.deepcopy(chain or [])
        self._chain_index: int = 0
        self._activated: bool = False  # True when a fallback is currently active
        self._current: FallbackConfig = copy.deepcopy(primary)

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def current(self) -> FallbackConfig:
        """The model config currently in use."""
        return self._current

    @property
    def is_fallback_active(self) -> bool:
        """True if the runtime is currently using a fallback (not the primary)."""
        return self._activated

    @property
    def fallback_attempt(self) -> int:
        """How many times we have fallen back this turn (0 = primary)."""
        return self._chain_index  # points to *next* to try, but tracks how many applied

    # ── Turn lifecycle ─────────────────────────────────────────────────────────

    def restore_primary(self) -> None:
        """
        Restore the primary model at the start of a new turn.

        Idempotent — safe to call even if no fallback was activated.
        This is the core guarantee of turn-scoped fallback: a transient
        error in turn N never bleeds into turn N+1.
        """
        if not self._activated:
            return
        self._current = copy.deepcopy(self._primary)
        self._chain_index = 0
        self._activated = False
        logger.info(
            "FallbackManager: restored primary model '%s'",
            self._primary.model,
        )

    def try_fallback(self) -> bool:
        """
        Switch to the next model in the fallback chain.

        Returns
        -------
        bool
            True  — successfully switched; ``self.current`` is now the fallback.
            False — chain exhausted; the caller should raise an error.
        """
        if self._chain_index >= len(self._chain):
            logger.error(
                "FallbackManager: chain exhausted after %d attempt(s) for primary '%s'",
                self._chain_index,
                self._primary.model,
            )
            return False

        next_cfg = self._chain[self._chain_index]
        self._chain_index += 1
        self._activated = True
        self._current = copy.deepcopy(next_cfg)

        logger.warning(
            "FallbackManager: switching to fallback #%d — model='%s'",
            self._chain_index,
            next_cfg.model,
        )
        return True

    # ── Attribution ────────────────────────────────────────────────────────────

    def get_attribution(self) -> FallbackAttribution:
        """
        Return attribution metadata for the current LLM call.

        Always records the *originally requested* primary model so cost
        analytics can answer "how much did we intend to spend on Qwen3.5-27B
        vs how much actually landed on a cheaper fallback".
        """
        return FallbackAttribution(
            requested_model=self._primary.model,
            model_name=self._current.model,
            is_fallback=self._activated,
            fallback_attempt=self._chain_index,  # 0 = primary, N = Nth fallback
        )

    # ── Factory ────────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: Any) -> "FallbackManager":
        """
        Build a FallbackManager from an application config object.

        Expected config shape (conf/default.yaml)::

            llm:
              model_name: "qwen3-5-27b-instruct"
              openai_api_base: "http://..."
              api_key: "..."
              fallback_chain:
                - model_name: "qwen3-5-14b-instruct"
                  openai_api_base: "http://..."
                  api_key: "..."
        """
        try:
            llm_cfg = getattr(config, "llm", None) or {}

            def _get(obj, key, default=""):
                if isinstance(obj, dict):
                    return obj.get(key, default)
                return getattr(obj, key, default)

            primary = FallbackConfig(
                model=_get(llm_cfg, "model_name", ""),
                base_url=_get(llm_cfg, "openai_api_base", ""),
                api_key=_get(llm_cfg, "api_key", ""),
            )

            chain_raw = _get(llm_cfg, "fallback_chain", []) or []
            chain = [
                FallbackConfig(
                    model=_get(c, "model_name", ""),
                    base_url=_get(c, "openai_api_base", ""),
                    api_key=_get(c, "api_key", ""),
                )
                for c in chain_raw
            ]

            return cls(primary=primary, chain=chain)

        except Exception as exc:
            logger.warning("FallbackManager.from_config failed (%s), using no-op", exc)
            return cls(primary=FallbackConfig(model="unknown"))

    def __repr__(self) -> str:
        return (
            f"FallbackManager(primary={self._primary.model!r}, "
            f"chain={[c.model for c in self._chain]}, "
            f"active={self._activated})"
        )
