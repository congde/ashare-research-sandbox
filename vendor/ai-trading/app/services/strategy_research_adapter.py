"""Adapter that exposes the ResearchAgentService to strategy code.

Strategies code against `ai_trading.api.ResearchSurface` — a small,
stable Protocol. Internally, the runtime wires a real
`ResearchAgentService` (which talks to ValueScan + DexScan + MCP).
This adapter is the glue: it satisfies the Protocol while delegating
to the service, and translates each integration's native error
taxonomy into the single strategy-facing exception class set
(`ResearchToolError` + subclasses).

This separation matters because:

1. **Strategy sandbox** — the DSL safelist only allows references
   to `ai_trading.api.*` types. The adapter is in the platform code
   path but its surface is the API Protocol, so the sandbox boundary
   stays intact.

2. **Stable contract** — the underlying `ResearchAgent*Error`
   classes can be renamed / split / merged without breaking
   strategies. The adapter pins the strategy-facing taxonomy.

3. **Turn-id wiring** — the adapter holds the LLM turn id (set by
   the Strategy Architect orchestrator at construction time) so each
   `query()` call is automatically charged against the right turn.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.ai_trading_api.research import (
    ResearchCreditExceededError,
    ResearchNotConfiguredError,
    ResearchToolNotFoundError,
    ResearchUpstreamError,
)
from app.core.resilience import CircuitBreaker, CircuitOpenError
from app.services.research_agent import (
    ResearchAgentCreditExceededError,
    ResearchAgentNotConfiguredError,
    ResearchAgentService,
    ResearchAgentToolError,
    ResearchAgentUpstreamError,
)

_T = TypeVar("_T")


class StrategyResearchAdapter:
    """Bridges ResearchAgentService → strategy-facing ResearchSurface.

    Construction:
        adapter = StrategyResearchAdapter(
            service=ResearchAgentService(),
            turn_id="llm-conversation-msg-42",
        )
        # Pass `adapter` as `ctx.research` to the strategy.

    The `turn_id` is bound at construction so every call this adapter
    makes credits the same turn. Use a fresh adapter per LLM turn
    (cheap — no I/O at construction).

    Trade-path safety (ADR-0020 PR-B). For the live runtime, pass
    ``timeout_seconds`` + a ``breaker``: each upstream call runs under a timeout
    (inside the circuit breaker, so a timeout counts as a breaker failure), and
    a slow/stalled upstream or an OPEN breaker surfaces as the strategy-facing
    ``ResearchUpstreamError`` — never an unbounded await that would block the
    per-tick strategy loop. The breaker should EXCLUDE business errors
    (not-configured / unknown-tool / credit-exceeded) so they don't trip it;
    only transport failures + timeouts should. Backtest / LLM-loop callers leave
    both ``None`` (no guard).
    """

    def __init__(
        self,
        *,
        service: ResearchAgentService,
        turn_id: str | None = None,
        timeout_seconds: float | None = None,
        breaker: CircuitBreaker | None = None,
        window_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._service = service
        self._turn_id = turn_id
        self._timeout_seconds = timeout_seconds
        self._breaker = breaker
        # When set (live runtime, ADR-0020 §4.3), the credit "turn" is the
        # owning turn_id PLUS the current time window — so the per-turn credit
        # ceiling becomes a steady-state per-window rate limit that resets every
        # ``window_seconds`` instead of accumulating for the whole run.
        self._window_seconds = window_seconds
        self._clock = clock

    def _effective_turn_id(self) -> str | None:
        """The credit-attribution id for the current call. Windowed when
        ``window_seconds`` is set (so the budget resets per window); otherwise
        the fixed ``turn_id`` (LLM-loop / backtest behaviour)."""
        if self._turn_id is None or self._window_seconds is None:
            return self._turn_id
        window = int(self._clock() // self._window_seconds)
        return f"{self._turn_id}:w{window}"

    async def _guarded(self, call: Callable[[], Awaitable[_T]]) -> _T:
        """Run a service call under the optional timeout + circuit breaker.

        Timeout is nested INSIDE the breaker so a timeout is recorded as a
        breaker failure (repeated stalls then fail fast via CircuitOpenError).
        """

        async def _timed() -> _T:
            if self._timeout_seconds is None:
                return await call()
            return await asyncio.wait_for(call(), timeout=self._timeout_seconds)

        if self._breaker is None:
            return await _timed()
        result: _T = await self._breaker.call(_timed)
        return result

    async def query(
        self,
        tool: str,
        payload: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke a Research tool by qualified key.

        Errors from the underlying service are mapped to the
        strategy-facing exception hierarchy so user code can catch
        a single class without knowing which integration backed the
        call.
        """
        try:
            return await self._guarded(
                lambda: self._service.invoke(
                    tool, payload=payload, turn_id=self._effective_turn_id()
                )
            )
        except ResearchAgentCreditExceededError as exc:
            # Preserve the structured fields so the strategy can
            # render a helpful message ("over budget by X credits").
            raise ResearchCreditExceededError(str(exc)) from exc
        except ResearchAgentNotConfiguredError as exc:
            raise ResearchNotConfiguredError(str(exc)) from exc
        except ResearchAgentToolError as exc:
            raise ResearchToolNotFoundError(str(exc)) from exc
        except ResearchAgentUpstreamError as exc:
            raise ResearchUpstreamError(str(exc)) from exc
        except (TimeoutError, CircuitOpenError) as exc:
            # Trade-path safety: a stalled upstream or an open breaker fails
            # fast as an upstream error — the strategy try/excepts and degrades
            # gracefully; the per-tick loop is never blocked.
            raise ResearchUpstreamError(
                f"research call guarded ({type(exc).__name__}): {exc}"
            ) from exc

    async def resolve_symbol(self, symbol: str) -> int:
        """Resolve a token symbol to its ValueScan vsTokenId."""
        try:
            return await self._guarded(lambda: self._service.resolve_symbol(symbol))
        except ResearchAgentToolError as exc:
            raise ResearchToolNotFoundError(str(exc)) from exc
        except ResearchAgentUpstreamError as exc:
            raise ResearchUpstreamError(str(exc)) from exc
        except (TimeoutError, CircuitOpenError) as exc:
            raise ResearchUpstreamError(
                f"research resolve_symbol guarded ({type(exc).__name__}): {exc}"
            ) from exc


__all__ = ["StrategyResearchAdapter"]
