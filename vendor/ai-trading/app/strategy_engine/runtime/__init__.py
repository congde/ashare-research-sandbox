"""Live + dry-run strategy runtime.

Sprint-S7 deliverable. The runtime drives the SAME ``on_tick(ctx,
candle) -> OrderIntent | None`` contract used by the backtest engine,
but with a real-time candle source (WS aggregator) and a real-or-
simulated order router.

Composition over inheritance: the runtime is the orchestrator; the
candle source and the order router are injected Protocols, so the
exact same ``StrategyRuntime`` class powers:

  * **dry-run** — replay or live WS feed + ``SimOrderRouter`` (paper
    fills at slipped close)
  * **live**   — live WS feed + a real-adapter-backed router (next PR)

The runtime is intentionally NOT a long-running daemon yet — v1.0
ships ``run_until_complete`` (consume a finite candle stream then
return). A daemon variant with start / stop / health endpoints lives
in S7-2 once the ACP checkpoint integration is wired.
"""

from app.strategy_engine.runtime.adapter_order_router import AdapterOrderRouter
from app.strategy_engine.runtime.protocol import CandleSource, OrderRouter
from app.strategy_engine.runtime.risk_manager import (
    AbnormalCandleRule,
    KillSwitch,
    MaxDrawdownRule,
    MaxPositionRule,
    MaxSlippageRule,
    RiskCheckResult,
    RiskManager,
    RiskRule,
    RiskThresholdPatchError,
)
from app.strategy_engine.runtime.runner import (
    HealthSnapshot,
    RestartPolicy,
    RunnerState,
    StrategyRunner,
    make_runtime_factory,
    runner_age_seconds,
)
from app.strategy_engine.runtime.runtime import (
    RuntimeEvent,
    StrategyRuntime,
    StrategyRuntimeResult,
)
from app.strategy_engine.runtime.sim_order_router import SimOrderRouter
from app.strategy_engine.runtime.ws_candle_source import WSCandleSource

__all__ = [
    "AbnormalCandleRule",
    "AdapterOrderRouter",
    "CandleSource",
    "HealthSnapshot",
    "KillSwitch",
    "MaxDrawdownRule",
    "MaxPositionRule",
    "MaxSlippageRule",
    "OrderRouter",
    "RestartPolicy",
    "RiskCheckResult",
    "RiskManager",
    "RiskRule",
    "RiskThresholdPatchError",
    "RunnerState",
    "RuntimeEvent",
    "SimOrderRouter",
    "StrategyRunner",
    "StrategyRuntime",
    "StrategyRuntimeResult",
    "WSCandleSource",
    "make_runtime_factory",
    "runner_age_seconds",
]
