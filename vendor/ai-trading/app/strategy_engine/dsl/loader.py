"""Compile a validated strategy source string into an ``on_tick`` callable.

Per ADR-0007, this is the missing bridge between the static DSL safelist /
validator and an *executable* strategy. The backtest engine and the live
runtime both need the SAME ``on_tick(ctx, candle) -> OrderIntent | None``
callable; until now both fell back to a hard-coded harness
(``backtest_service.make_harness_strategy`` / ``strategies_runtime.
_buy_once_strategy``) because no compile step existed. This module is that
step — the single place user / LLM strategy code becomes runnable.

Trust model
-----------
``compile_strategy`` runs the strategy source via ``exec`` in the *current
process*. That is the same trust posture the backtest engine already has
when it invokes a strategy callable — it must be, because ``on_tick`` is
called once per candle and a per-tick subprocess hop is not viable. The
defense is therefore static + a restricted execution namespace:

  1. :func:`validate_strategy_code` rejects denied imports / builtins /
     attributes / eval / exec BEFORE we ever ``exec`` (defense layer 2).
  2. The exec namespace's ``__builtins__`` strips ``DENIED_BUILTINS`` and
     installs a guarded ``__import__`` that resolves only the safelist —
     defense in depth, catching anything the AST pass missed.

Heavyweight process isolation (Docker, ADR-0005) remains the runtime
*deployment* boundary; it wraps the whole runner, orthogonal to this
per-tick compile.
"""

from __future__ import annotations

import builtins as _builtins
import importlib
import sys
import types
from typing import TYPE_CHECKING, Any, cast

from app.strategy_engine.dsl.safelist import (
    ALLOWED_IMPORTS,
    DENIED_BUILTINS,
    DENIED_IMPORTS,
    REQUIRED_FUNCTION_NAME,
)
from app.strategy_engine.dsl.validator import ValidationError, validate_strategy_code

if TYPE_CHECKING:
    from app.strategy_engine.backtest.engine import StrategyFn

# Source-of-truth module that the strategy-facing ``ai_trading.api`` alias
# resolves to. Kept as a string so importing this module is cheap — the
# real import only happens on first compile.
_AI_TRADING_SOURCE = "app.ai_trading_api"


class StrategyCompileError(ValueError):
    """Strategy source failed to compile into an ``on_tick`` callable.

    Carries the validator's structured ``errors`` when the failure is a
    safelist / syntax violation, so callers (the LLM self-correction loop,
    an API 422) can surface line-level feedback. ``errors`` is empty for
    runtime exec failures (the code raised while defining ``on_tick``).
    """

    def __init__(self, message: str, errors: tuple[ValidationError, ...] = ()) -> None:
        super().__init__(message)
        self.errors = errors


def _ensure_ai_trading_alias() -> None:
    """Register ``ai_trading.api`` -> ``app.ai_trading_api`` in ``sys.modules``.

    So strategy code's ``from ai_trading.api import market_buy`` resolves
    in-process. Idempotent. Mirrors what the docker / local sandbox does
    inside its subprocess; here we do it in-process for the backtest +
    live-runtime callable path. ``app.ai_trading_api`` stays the single
    source of truth — the alias only re-points the import name.
    """
    if "ai_trading" in sys.modules and "ai_trading.api" in sys.modules:
        return
    api_mod = importlib.import_module(_AI_TRADING_SOURCE)
    pkg = sys.modules.get("ai_trading")
    if pkg is None:
        pkg = types.ModuleType("ai_trading")
        pkg.__path__ = []  # mark as a (namespace) package
        sys.modules["ai_trading"] = pkg
    pkg.api = api_mod  # type: ignore[attr-defined]
    sys.modules["ai_trading.api"] = api_mod


def _guarded_import(
    name: str,
    globals: dict[str, Any] | None = None,
    locals: dict[str, Any] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    """Restricted ``__import__`` for the strategy exec namespace.

    Only the safelist resolves; everything else raises ``ImportError`` —
    defense in depth behind the AST validator. ``ai_trading.api`` is
    pre-aliased by :func:`_ensure_ai_trading_alias`. Signature matches the
    real ``__import__`` so the ``import`` statement dispatches to it.
    """
    top = name.split(".")[0]
    if name in DENIED_IMPORTS or top in DENIED_IMPORTS:
        raise ImportError(f"import denied by strategy safelist: {name}")
    if not (name in ALLOWED_IMPORTS or top in ALLOWED_IMPORTS):
        raise ImportError(f"import not on strategy safelist: {name}")
    return _builtins.__import__(name, globals, locals, fromlist, level)


def _safe_builtins() -> dict[str, Any]:
    """``builtins`` with ``DENIED_BUILTINS`` removed and ``__import__``
    replaced by the guarded importer. Everyday builtins (len, sum, range,
    float, sorted, ...) are preserved so ordinary strategies run."""
    safe = {k: v for k, v in vars(_builtins).items() if k not in DENIED_BUILTINS}
    safe["__import__"] = _guarded_import
    return safe


def compile_strategy(code: str, *, filename: str = "<strategy>") -> StrategyFn:
    """Validate + compile strategy source into its ``on_tick`` callable.

    Raises :class:`StrategyCompileError` if the source fails the DSL
    safelist / syntax check, defines no ``on_tick``, or ``on_tick`` is not
    callable after exec. The returned callable has the
    ``(ctx, candle) -> OrderIntent | None`` shape and is suitable for both
    the backtest engine and the live runtime.
    """
    result = validate_strategy_code(code)
    if not result.valid:
        first = result.first_error
        msg = (
            f"strategy failed validation: {first.rule}: {first.message}"
            if first is not None
            else "strategy failed validation"
        )
        raise StrategyCompileError(msg, errors=result.errors)

    _ensure_ai_trading_alias()

    # Same dict for globals AND locals so module-level imports land in the
    # namespace that ``on_tick``'s ``__globals__`` points at — otherwise the
    # closure can't see ``from ai_trading.api import market_buy``.
    namespace: dict[str, Any] = {"__builtins__": _safe_builtins()}
    try:
        compiled = compile(code, filename, "exec")
        exec(compiled, namespace, namespace)
    except Exception as exc:
        raise StrategyCompileError(
            f"strategy code raised at import time: {type(exc).__name__}: {exc}"
        ) from exc

    on_tick = namespace.get(REQUIRED_FUNCTION_NAME)
    if not callable(on_tick):
        raise StrategyCompileError(f"strategy defines no callable {REQUIRED_FUNCTION_NAME!r}")
    return cast("StrategyFn", on_tick)
