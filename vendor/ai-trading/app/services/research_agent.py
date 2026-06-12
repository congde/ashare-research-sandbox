"""Research Agent service — unified surface over ValueScan + DexScan.

Combines the two market-intelligence integrations into a single agent
namespace so callers (frontend Research panel, future LLM-driven
Strategy Architect) see one cohesive tool catalogue instead of two
side-by-side ones.

Design decisions
- **Pure orchestration** — no caching, no rate limiting here.
  Per-turn credit governance and the vsTokenId LRU cache live in
  dedicated services (`research_credit_governor.py`,
  `valuescan_token_cache.py` — stage 2b). This module just routes.
- **Namespace prefixes** — every tool key is exposed as `vs.<key>`
  or `dex.<key>` so the agent / dashboard can disambiguate. The
  underlying clients receive the un-prefixed key.
- **Read-only** — Research Agent never mutates state. Every call is
  a GET-flavoured market-data lookup. Routing through this service
  is therefore safe to expose to any authenticated user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from app.integrations.dexscan import (
    DEXSCAN_ENDPOINTS,
    DexScanClient,
    DexScanConfigurationError,
    DexScanEndpointError,
    DexScanError,
)
from app.integrations.valuescan import (
    VALUESCAN_ENDPOINTS,
    MCPTool,
    ValueScanClient,
    ValueScanConfigurationError,
    ValueScanEndpointError,
    ValueScanError,
    ValueScanMCPClient,
    ValueScanMCPConfigurationError,
    ValueScanMCPError,
)
from app.services.research_credit_governor import (
    CreditCeilingExceededError,
    ResearchCreditGovernor,
)
from app.services.valuescan_token_cache import (
    TokenCacheError,
    TokenNotFoundError,
    ValueScanTokenCache,
)

# Namespace separator — chosen to be visually distinct from `/` and `.`
# in URLs, so the keys appear cleanly in JSON / logs / dashboards.
NAMESPACE_SEP: Final[str] = "."


class ResearchSource(StrEnum):
    """Which underlying integration a tool belongs to."""

    VALUESCAN = "vs"
    DEXSCAN = "dex"
    # `mcp` is the ValueScan MCP SSE auto-discovered tool surface
    # (`mcp.<tool_name>` qualified key). Different transport from
    # the REST surface above — uses JSON-RPC over SSE.
    MCP = "mcp"


@dataclass(frozen=True)
class ResearchTool:
    """One unified tool exposed to Research Agent callers.

    Args:
        qualified_key: `<source>.<key>` (e.g. `vs.token_detail`,
            `dex.current_price`). Stable identifier; renaming is a
            breaking change.
        source: which integration this tool comes from.
        local_key: the un-prefixed key as known to the underlying
            integration client.
        path: the upstream HTTP path (for display only — the client
            picks the actual URL).
        label: human-readable description.
        body_shape: hint for the frontend payload editor seed. For
            ValueScan tools this is always `"dict"`; for DexScan it
            varies — see `DexScanBodyShape`. Unknown shapes get
            `"unknown"` so the UI can render a "schema TBD" warning.
    """

    qualified_key: str
    source: ResearchSource
    local_key: str
    path: str
    label: str
    body_shape: str = "dict"


@dataclass(frozen=True)
class ResearchToolCatalogue:
    """Catalogue snapshot exposed to the Research API + frontend.

    Frozen so dashboard render cycles can't observe a mid-mutation
    state. Built once at module load; cheap to copy.
    """

    tools: tuple[ResearchTool, ...]
    valuescan_configured: bool
    dexscan_configured: bool

    @property
    def tool_count(self) -> int:
        return len(self.tools)

    @property
    def by_source(self) -> dict[ResearchSource, tuple[ResearchTool, ...]]:
        """Tools grouped by source — convenience for UI rendering."""
        groups: dict[ResearchSource, list[ResearchTool]] = {
            ResearchSource.VALUESCAN: [],
            ResearchSource.DEXSCAN: [],
        }
        for tool in self.tools:
            groups[tool.source].append(tool)
        return {src: tuple(items) for src, items in groups.items()}


class ResearchAgentError(RuntimeError):
    """Base class for Research Agent failures."""


class ResearchAgentNotConfiguredError(ResearchAgentError):
    """Raised when the underlying integration is not configured.

    Mapped to HTTP 503 at the router layer.
    """


class ResearchAgentToolError(ResearchAgentError):
    """Raised when the qualified tool key is unknown.

    Mapped to HTTP 404 at the router layer.
    """


class ResearchAgentUpstreamError(ResearchAgentError):
    """Raised when the upstream provider returns a transport-level
    failure (HTTP error, non-JSON body, timeout). Mapped to HTTP 502.

    Note: business-level errors from upstream (e.g. DexScan returning
    `code:500 "Name is null"` for a malformed body) are NOT mapped
    here — those flow through as the envelope content of a successful
    call. The Research Agent does not interpret upstream business
    codes; that's the caller's responsibility.
    """


class ResearchAgentCreditExceededError(ResearchAgentError):
    """Raised when a charge() against the per-turn credit governor
    would exceed the ceiling. Mapped to HTTP 429.

    Carries the turn id + the ceiling so callers can render an
    informative "too many tool calls in this turn" message instead
    of a generic 5xx.
    """

    def __init__(
        self,
        *,
        turn_id: str,
        attempted_cost: int,
        already_spent: int,
        ceiling: int,
    ) -> None:
        self.turn_id = turn_id
        self.attempted_cost = attempted_cost
        self.already_spent = already_spent
        self.ceiling = ceiling
        super().__init__(
            f"Turn {turn_id!r} would exceed credit ceiling: "
            f"spent={already_spent} + cost={attempted_cost} > "
            f"ceiling={ceiling}",
        )


def build_research_tool_catalogue() -> tuple[ResearchTool, ...]:
    """Build the unified tool catalogue from both integrations.

    Pure function — no I/O. Called at module load and any time the
    underlying integration catalogues change (rare; typically a new
    deploy).
    """
    tools: list[ResearchTool] = []
    for ep in VALUESCAN_ENDPOINTS.values():
        tools.append(
            ResearchTool(
                qualified_key=f"vs{NAMESPACE_SEP}{ep.key}",
                source=ResearchSource.VALUESCAN,
                local_key=ep.key,
                path=ep.full_path,
                label=ep.label,
                body_shape="dict",  # ValueScan is always dict-bodied
            ),
        )
    for ep in DEXSCAN_ENDPOINTS.values():
        # Map the integration-level enum to a frontend-friendly string.
        # Keeping the strings stable (coin_key / coin_key_list / unknown)
        # means a UI-only catalogue change can't break the API contract.
        tools.append(
            ResearchTool(
                qualified_key=f"dex{NAMESPACE_SEP}{ep.key}",
                source=ResearchSource.DEXSCAN,
                local_key=ep.key,
                path=ep.path,
                label=ep.label,
                body_shape=ep.body_shape.value,
            ),
        )
    return tuple(tools)


_TOOL_CATALOGUE: Final[tuple[ResearchTool, ...]] = build_research_tool_catalogue()
_TOOLS_BY_QUALIFIED_KEY: Final[dict[str, ResearchTool]] = {
    t.qualified_key: t for t in _TOOL_CATALOGUE
}


def resolve_research_tool(qualified_key: str) -> ResearchTool:
    """Resolve `vs.<key>` or `dex.<key>` to a `ResearchTool`.

    MCP keys (`mcp.<tool_name>`) are dynamically discovered and NOT
    pre-registered in the module-level catalogue; this resolver
    accepts them by constructing a synthetic ResearchTool whose
    `local_key` is the tool name. The invoke path uses local_key as
    the JSON-RPC `tools/call name` so the tool doesn't need to exist
    in the cache for invoke to work.

    Raises:
        ResearchAgentToolError: if the key is malformed or not
            registered AND doesn't follow the MCP namespace pattern.
    """
    candidate = qualified_key.strip()
    if not candidate:
        raise ResearchAgentToolError("research tool key is empty")

    if candidate in _TOOLS_BY_QUALIFIED_KEY:
        return _TOOLS_BY_QUALIFIED_KEY[candidate]

    # MCP keys are discovered at runtime — construct a synthetic
    # ResearchTool. Validate the prefix is `mcp.` to avoid making
    # this a wildcard catch-all that hides typos for vs/dex keys.
    if candidate.startswith(f"mcp{NAMESPACE_SEP}"):
        local_key = candidate[len(f"mcp{NAMESPACE_SEP}"):]
        if not local_key:
            raise ResearchAgentToolError(
                "MCP tool key missing name after 'mcp.' prefix",
            )
        return ResearchTool(
            qualified_key=candidate,
            source=ResearchSource.MCP,
            local_key=local_key,
            path=local_key,
            label="(MCP tool — discovered at runtime)",
            body_shape="mcp",
        )

    # List a few neighbouring keys so the caller can correct typos.
    sample = ", ".join(sorted(list(_TOOLS_BY_QUALIFIED_KEY.keys())[:5]))
    raise ResearchAgentToolError(
        f"Unknown research tool '{qualified_key}'. "
        f"Sample of valid keys: {sample}, …",
    )


class ResearchAgentService:
    """Orchestrates ValueScan + DexScan client calls under a single API.

    Construction:
        svc = ResearchAgentService()
        catalogue = svc.catalogue()
        result = await svc.invoke("vs.token_detail", payload={"vsTokenId": 1})
        result = await svc.invoke("dex.current_price",
                                  payload=[{"name": "USDT", "chain": "ETH"}])

    The two clients are constructed lazily (on first invoke against
    that source) so tools tests can pass without configured creds for
    the source they aren't exercising.
    """

    def __init__(
        self,
        *,
        valuescan: ValueScanClient | None = None,
        dexscan: DexScanClient | None = None,
        mcp: ValueScanMCPClient | None = None,
        token_cache: ValueScanTokenCache | None = None,
        credit_governor: ResearchCreditGovernor | None = None,
    ) -> None:
        self._valuescan = valuescan
        self._dexscan = dexscan
        self._mcp = mcp
        # Token cache + credit governor are constructed lazily on
        # first use so tests that don't exercise them don't pay the
        # init cost; production paths share a single instance via the
        # gateway dependency wiring.
        self._token_cache = token_cache
        self._credit_governor = credit_governor
        # MCP tools cached in-memory after the first list_tools call
        # so the catalogue endpoint doesn't issue a fresh SSE
        # handshake on every request. Refresh-on-demand via
        # `refresh_mcp_catalogue()`.
        self._mcp_tools_cache: dict[str, MCPTool] | None = None

    # --- Catalogue introspection -----------------------------------

    def catalogue(self) -> ResearchToolCatalogue:
        """Return the catalogue snapshot — REST surface only.

        For the MCP-augmented catalogue (which requires an SSE call),
        use `catalogue_with_mcp()` instead. This synchronous version
        is kept stable for callers that just want to know "does this
        REST tool exist" without paying the MCP handshake cost.
        """
        return ResearchToolCatalogue(
            tools=_TOOL_CATALOGUE,
            valuescan_configured=self._lazy_valuescan().config.is_configured,
            dexscan_configured=self._lazy_dexscan().config.is_configured,
        )

    async def catalogue_with_mcp(
        self,
        *,
        refresh: bool = False,
    ) -> ResearchToolCatalogue:
        """Return the catalogue including MCP-discovered tools.

        Issues one SSE handshake on first call (subsequent calls hit
        the in-process cache). Passing `refresh=True` forces a
        re-discovery.

        MCP tools come back as `ResearchTool(source=MCP)` entries with
        qualified keys `mcp.<tool_name>`. The tool's `input_schema`
        from the MCP server is carried in the `body_shape` field
        as the literal string "mcp" (which the frontend recognizes
        as "render a generic JSON-schema form").
        """
        base_tools = list(_TOOL_CATALOGUE)
        mcp_configured = self._lazy_mcp().config.is_configured

        if mcp_configured and (refresh or self._mcp_tools_cache is None):
            try:
                discovered = await self._lazy_mcp().list_tools()
                self._mcp_tools_cache = {t.name: t for t in discovered}
            except ValueScanMCPError:
                # Failure surfaces to the caller via the
                # base catalogue + the `mcp_configured` flag below;
                # we don't crash the catalogue call just because the
                # MCP handshake failed.
                self._mcp_tools_cache = {}

        for mcp_tool in (self._mcp_tools_cache or {}).values():
            base_tools.append(
                ResearchTool(
                    qualified_key=f"mcp{NAMESPACE_SEP}{mcp_tool.name}",
                    source=ResearchSource.MCP,
                    local_key=mcp_tool.name,
                    path=mcp_tool.name,  # MCP doesn't have HTTP paths
                    label=mcp_tool.description or "(no description)",
                    body_shape="mcp",
                ),
            )

        return ResearchToolCatalogue(
            tools=tuple(base_tools),
            valuescan_configured=self._lazy_valuescan().config.is_configured,
            dexscan_configured=self._lazy_dexscan().config.is_configured,
        )

    # --- Tool invocation -------------------------------------------

    async def invoke(
        self,
        qualified_key: str,
        payload: Any = None,
        *,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        """Invoke a Research tool by qualified key.

        Routes by `source` to the appropriate client. Errors from
        the client are wrapped in `ResearchAgent*Error` so callers
        get a stable error taxonomy regardless of which provider
        was behind the tool.

        If `turn_id` is provided, the call is charged against the
        per-turn credit governor (raises
        ResearchAgentCreditExceededError on ceiling violation).
        Pass `turn_id=None` for unattributed calls (frontend manual
        probing); these don't count against any ceiling.
        """
        tool = resolve_research_tool(qualified_key)

        # Charge BEFORE the upstream call. If the charge fails the
        # turn is over budget and we don't waste an upstream credit.
        if turn_id is not None:
            await self._charge_credit(turn_id, tool.qualified_key)

        if tool.source == ResearchSource.VALUESCAN:
            return await self._invoke_valuescan(tool, payload)
        if tool.source == ResearchSource.DEXSCAN:
            return await self._invoke_dexscan(tool, payload)
        if tool.source == ResearchSource.MCP:
            return await self._invoke_mcp(tool, payload)
        raise ResearchAgentToolError(  # pragma: no cover — enum-exhaustive
            f"Unknown source for tool '{qualified_key}': {tool.source}",
        )

    async def resolve_symbol(self, symbol: str) -> int:
        """Resolve a token symbol (e.g. "BTC") to its ValueScan
        vsTokenId via the in-process LRU cache.

        Wraps `ValueScanTokenCache.resolve()` so the Research Agent
        owns the cache lifecycle. Callers needing the underlying
        cache stats can reach for `service.token_cache.stats`.
        """
        try:
            return await self._lazy_token_cache().resolve(symbol)
        except TokenNotFoundError as exc:
            raise ResearchAgentToolError(str(exc)) from exc
        except TokenCacheError as exc:
            raise ResearchAgentUpstreamError(str(exc)) from exc

    @property
    def token_cache(self) -> ValueScanTokenCache:
        """Access the token cache (lazily constructed)."""
        return self._lazy_token_cache()

    @property
    def credit_governor(self) -> ResearchCreditGovernor:
        """Access the credit governor (lazily constructed)."""
        return self._lazy_credit_governor()

    async def _charge_credit(self, turn_id: str, tool_key: str) -> None:
        governor = self._lazy_credit_governor()
        cost = governor.cost_for(tool_key)
        try:
            await governor.charge(turn_id, tool_key, cost)
        except CreditCeilingExceededError as exc:
            raise ResearchAgentCreditExceededError(
                turn_id=exc.turn_id,
                attempted_cost=exc.attempted_cost,
                already_spent=exc.already_spent,
                ceiling=exc.ceiling,
            ) from exc

    async def _invoke_valuescan(
        self,
        tool: ResearchTool,
        payload: Any,
    ) -> dict[str, Any]:
        client = self._lazy_valuescan()
        try:
            # ValueScan only accepts dict bodies.
            if payload is not None and not isinstance(payload, dict):
                raise ResearchAgentToolError(
                    f"ValueScan tool '{tool.qualified_key}' expects a "
                    f"dict payload, got {type(payload).__name__}",
                )
            return await client.post_endpoint(tool.local_key, payload)
        except ValueScanConfigurationError as exc:
            raise ResearchAgentNotConfiguredError(str(exc)) from exc
        except ValueScanEndpointError as exc:
            raise ResearchAgentToolError(str(exc)) from exc
        except ValueScanError as exc:
            raise ResearchAgentUpstreamError(str(exc)) from exc

    async def _invoke_dexscan(
        self,
        tool: ResearchTool,
        payload: Any,
    ) -> dict[str, Any]:
        client = self._lazy_dexscan()
        try:
            return await client.post_endpoint(tool.local_key, payload)
        except DexScanConfigurationError as exc:
            raise ResearchAgentNotConfiguredError(str(exc)) from exc
        except DexScanEndpointError as exc:
            raise ResearchAgentToolError(str(exc)) from exc
        except DexScanError as exc:
            raise ResearchAgentUpstreamError(str(exc)) from exc

    async def _invoke_mcp(
        self,
        tool: ResearchTool,
        payload: Any,
    ) -> dict[str, Any]:
        """Invoke an MCP tool via JSON-RPC tools/call.

        MCP tools accept a `dict` arguments parameter per the MCP
        protocol — we reject list payloads BEFORE the network call
        (the MCP server would 400 anyway, but failing fast is nicer).
        """
        client = self._lazy_mcp()
        if payload is not None and not isinstance(payload, dict):
            raise ResearchAgentToolError(
                f"MCP tool '{tool.qualified_key}' expects a dict payload, "
                f"got {type(payload).__name__}",
            )
        try:
            return await client.call_tool(
                tool.local_key, payload if isinstance(payload, dict) else None,
            )
        except ValueScanMCPConfigurationError as exc:
            raise ResearchAgentNotConfiguredError(str(exc)) from exc
        except ValueScanMCPError as exc:
            raise ResearchAgentUpstreamError(str(exc)) from exc

    # --- Lazy client construction ----------------------------------

    def _lazy_valuescan(self) -> ValueScanClient:
        if self._valuescan is None:
            self._valuescan = ValueScanClient()
        return self._valuescan

    def _lazy_dexscan(self) -> DexScanClient:
        if self._dexscan is None:
            self._dexscan = DexScanClient()
        return self._dexscan

    def _lazy_mcp(self) -> ValueScanMCPClient:
        if self._mcp is None:
            self._mcp = ValueScanMCPClient()
        return self._mcp

    def _lazy_token_cache(self) -> ValueScanTokenCache:
        if self._token_cache is None:
            # Share the VS client so cache + service hit the same
            # upstream connection pool.
            self._token_cache = ValueScanTokenCache(
                client=self._lazy_valuescan(),
            )
        return self._token_cache

    def _lazy_credit_governor(self) -> ResearchCreditGovernor:
        if self._credit_governor is None:
            self._credit_governor = ResearchCreditGovernor()
        return self._credit_governor


__all__ = [
    "NAMESPACE_SEP",
    "ResearchAgentCreditExceededError",
    "ResearchAgentError",
    "ResearchAgentNotConfiguredError",
    "ResearchAgentService",
    "ResearchAgentToolError",
    "ResearchAgentUpstreamError",
    "ResearchSource",
    "ResearchTool",
    "ResearchToolCatalogue",
    "build_research_tool_catalogue",
    "resolve_research_tool",
]
