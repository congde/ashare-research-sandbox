"""`ai_trading.api.research` — strategy-facing Research Agent surface.

Strategies can call market-intelligence tools through a curated
`ctx.research.*` namespace exposed by `StrategyContext`. This module
defines the public Protocol so strategies have something to type-hint
against, and a sandbox-safe default implementation that fails closed
when the runtime hasn't wired an actual Research Agent.

Why a Protocol vs the service directly
--------------------------------------

The runtime constructs an actual `ResearchAgentService` (which talks
to ValueScan + DexScan + MCP) and passes it to the strategy as
`ctx.research`. Tests + the backtest engine pass a stub that returns
canned data (or raises so the strategy can't accidentally hit the
network during a deterministic backtest).

Strategies code against the **Protocol**, not the concrete service —
so:

  1. Tests can stub `ctx.research` without importing the heavy
     integration layer.
  2. The sandbox enforces the surface: only Protocol methods are
     reachable; the strategy can't reach into ResearchAgentService
     to grab the underlying httpx client.

Per-turn credit governance
--------------------------

When the strategy is running inside the LLM-driven Strategy
Architect (S6 conversation), `ctx.research.turn_id` is populated
with the current LLM turn id. Each `query()` / `resolve_symbol()`
call charges the per-turn credit governor (default ceiling 20).
Backtest + live-runtime usage leaves `turn_id` as None — those
contexts have their own cost accounting + are not subject to the
LLM-loop budget.
"""

from __future__ import annotations

from typing import Any, Protocol


class ResearchSurface(Protocol):
    """Public Protocol for `ctx.research`.

    Strategy code calls these methods; the runtime resolves them to
    a real ResearchAgentService or to a stub. The Protocol is what
    appears in the DSL safelist — anything outside this surface is
    unreachable from sandboxed user code.
    """

    async def query(
        self,
        tool: str,
        payload: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke a Research tool by qualified key.

        Args:
            tool: qualified key like `"vs.token_detail"`,
                `"dex.current_price"`, or `"mcp.ai_chance_coin_list"`.
            payload: dict (most tools) or list (some DexScan tools).

        Returns the upstream envelope. Strategies should inspect
        `result["code"]` and `result["data"]` per ValueScan/DexScan
        conventions.

        Raises tool-specific errors if the call fails (the runtime
        maps each integration's native errors to a stable strategy-
        facing exception set; see `ResearchToolError`).
        """
        ...

    async def resolve_symbol(self, symbol: str) -> int:
        """Resolve a token symbol (e.g. "BTC") to its ValueScan
        `vsTokenId`. Cached for 24h.

        Use this BEFORE calling `vs.token_detail` / `vs.kline` /
        most other ValueScan endpoints — they take vsTokenId, not
        symbol.
        """
        ...


class ResearchToolError(RuntimeError):
    """Raised when a Research tool call fails.

    Strategies see ONE exception class regardless of which integration
    backed the failure (ValueScan / DexScan / MCP) so they can
    `try / except` cleanly without coupling to specific providers.

    Subclasses (mapped from the runtime's `ResearchAgent*Error`):
        ResearchNotConfiguredError — provider keys missing
        ResearchToolNotFoundError  — tool name unknown
        ResearchUpstreamError      — transport / non-JSON failure
        ResearchCreditExceededError — per-turn credit ceiling hit
    """


class ResearchNotConfiguredError(ResearchToolError):
    """Underlying provider has no API key. Backtest / dev only."""


class ResearchToolNotFoundError(ResearchToolError):
    """Tool name is not in the catalogue."""


class ResearchUpstreamError(ResearchToolError):
    """Transport-level failure or non-JSON upstream response."""


class ResearchCreditExceededError(ResearchToolError):
    """LLM agent loop hit the per-turn credit ceiling."""


class NoOpResearch:
    """Default `ctx.research` for contexts without a wired runtime.

    Backtests are deterministic by contract: a strategy that calls
    `ctx.research.query(...)` during a backtest would introduce a
    non-deterministic external dependency. The NoOpResearch surface
    raises a clear error so the strategy author knows to gate
    research-dependent code with `if ctx.in_live_mode:` (a future
    helper) — or pre-compute research data into a constant.
    """

    async def query(
        self,
        tool: str,
        payload: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        raise ResearchNotConfiguredError(
            f"ctx.research is not wired in this runtime. Cannot call "
            f"'{tool}'. (Backtest contexts deliberately disable the "
            f"research surface to keep runs deterministic.)",
        )

    async def resolve_symbol(self, symbol: str) -> int:
        raise ResearchNotConfiguredError(
            f"ctx.research is not wired; cannot resolve '{symbol}'.",
        )


__all__ = [
    "NoOpResearch",
    "ResearchCreditExceededError",
    "ResearchNotConfiguredError",
    "ResearchSurface",
    "ResearchToolError",
    "ResearchToolNotFoundError",
    "ResearchUpstreamError",
]
