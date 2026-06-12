# -*- coding: utf-8 -*-
"""
AgentEngineError — PR-E7 of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E7.

Goal
----
Establish an engine-owned error hierarchy so engine modules can signal
control-flow conditions (missing resource, invalid parameter, risk
interception, etc.) WITHOUT depending on ``web.exceptions.HttpException``
— that import path is unreachable when the engine is packaged as the
:mod:`kucoin-agent-runtime-sdk`.

Hierarchy
---------
::

    AgentEngineError                  ← base (carries code / msg / extra)
    ├── ResourceNotFoundError         ← qa_id / session_id missing, etc.
    ├── InvalidParameterError         ← schema / validation failures
    ├── ConcurrencyError              ← conversation in progress, etc.
    ├── RiskInterceptedError          ← query risk / shield blocked
    └── EngineInternalError           ← unexpected internal failure

Each subclass carries the same ``(code, msg, extra, raise_user)``
attributes as ``HttpException`` so callers can pass through to the
business layer's existing FastAPI handler unchanged.

Backwards compatibility (PR-E7 only; cleaned up in Phase 2)
-----------------------------------------------------------
When ``web.exceptions`` is reachable (ai-buddy's current production
boot path), ``AgentEngineError`` **inherits from** ``HttpException`` so
the business layer's existing ``except HttpException`` blocks continue
to catch every engine error without modification. This makes PR-E7 a
zero-behaviour-change refactor.

In SDK extraction (Phase 2), when ``web.exceptions`` is no longer in
the engine's import surface, ``AgentEngineError`` falls back to
inheriting from ``Exception``. SDK consumers add their own
exception-handler middleware that catches ``AgentEngineError`` and
maps it to whatever HTTP status / event shape they want.

Same pattern as PR-E1 :mod:`runtime.protocols.engine_config` and
PR-E5 :mod:`runtime.protocols.backend_provider` — engine carries its
own contract; business layer keeps its own concrete types; the SDK
seam lives at the import boundary.
"""

from __future__ import annotations

from typing import Any, Optional

try:
    # Inherit from HttpException when available so ai-buddy's existing
    # ``except HttpException`` blocks keep catching engine errors with
    # zero change in business code.  Wire-format is identical.
    from web.exceptions import HttpException as _Base  # type: ignore[import]
    _INHERITS_HTTP_EXCEPTION = True
except ImportError:
    # SDK-extracted scenario: engine has no web/ dependency.  Provide a
    # standalone base with the same shape so engine raises remain
    # source-compatible.
    _INHERITS_HTTP_EXCEPTION = False

    class _Base(Exception):  # type: ignore[no-redef]
        def __init__(
            self,
            code: Any,
            msg: Optional[str] = None,
            extra: Any = None,
            raise_user: bool = False,
        ):
            self.code = code
            self.msg = msg if msg is not None else ""
            self.extra = extra
            self.raise_user = raise_user
            super().__init__(self.msg)

        def __repr__(self) -> str:
            return (
                f"<{type(self).__name__}(code={self.code}, "
                f"msg={self.msg}, extra={self.extra}, "
                f"raise_user={self.raise_user})>"
            )

        def __str__(self) -> str:
            return self.__repr__()


# PR-E7b: RiskInterceptedError must satisfy ``isinstance(e, RiskException)``
# in addition to ``isinstance(e, HttpException)`` so every existing
# ``except RiskException`` block in business + engine code (the 6 catch
# sites in agent/base.py + llm/shield/handler.py) keeps routing risk-
# interception flows correctly.  If web.exceptions.RiskException is
# unreachable (SDK-extracted scenario), the risk-mixin base degrades
# to ``object`` — no catch site references it in that environment.
try:
    from web.exceptions import RiskException as _RiskMixin  # type: ignore[import]
    _INHERITS_RISK_EXCEPTION = True
except ImportError:
    _RiskMixin = object  # type: ignore[assignment,misc]
    _INHERITS_RISK_EXCEPTION = False


class AgentEngineError(_Base):
    """Base for all engine-raised control-flow exceptions.

    Subclasses carve the surface into a small number of well-known
    categories that SDK consumers can pattern-match. Each instance
    carries ``code`` / ``msg`` / ``extra`` / ``raise_user`` attributes
    identical to ai-buddy's :class:`HttpException` so the existing
    FastAPI translator works unchanged.
    """


class ResourceNotFoundError(AgentEngineError):
    """A required resource lookup returned nothing.

    Replaces hard-coded ``HttpException(code=CODE_QA_ID_NOT_FOUND)`` /
    ``HttpException(code=CODE_SESSION_ID_NOT_FOUND)`` /
    ``HttpException(code=CODE_SESSION_DELETED)`` raise sites in engine
    code. The numeric ``code`` distinguishes between the specific
    missing-resource flavour for backwards-compatible client
    handling.
    """


class InvalidParameterError(AgentEngineError):
    """Request parameter failed validation (engine-side check)."""


class ConcurrencyError(AgentEngineError):
    """A concurrent operation is already in flight for the same key
    (e.g. ``CODE_CONVERSATION_IN_PROGRESS``).
    """


class RiskInterceptedError(AgentEngineError, _RiskMixin):
    """Risk / safety check refused to process the input or output.

    Conceptually parallel to ai-buddy's :class:`web.exceptions.
    RiskException` but rooted in the engine hierarchy so SDK consumers
    can match on ``RiskInterceptedError`` without importing web.

    Multiple inheritance (PR-E7b fix): when ``web.exceptions`` is
    reachable, ``RiskInterceptedError`` also inherits from
    :class:`web.exceptions.RiskException` so every existing
    ``except RiskException:`` block in business + engine code keeps
    routing risk-interception flows correctly.  Without this mixin,
    the original PR-E7b shipped a critical regression: ``except
    RiskException:`` would silently fall through to the generic
    ``except Exception:`` handler, breaking the BLOCKED_ANSWER
    code path in agent/base.py and the local-AC-Automaton fallback
    in llm/shield/handler.py.

    In SDK-extracted scenarios (``web.exceptions`` unreachable),
    the second base degrades to ``object`` — no business code in
    that environment references ``RiskException`` so no catch site
    is broken.
    """


class EngineInternalError(AgentEngineError):
    """Unexpected engine-side failure that should surface to the user
    as an internal error (e.g. shield handler upgrading a FAILED
    stream chunk to a 500-equivalent).
    """


def is_http_exception_compatible() -> bool:
    """Return True when ``AgentEngineError`` inherits from
    :class:`web.exceptions.HttpException`. Test helper — production
    code should rely on ``isinstance`` checks instead.
    """
    return _INHERITS_HTTP_EXCEPTION


def is_risk_exception_compatible() -> bool:
    """Return True when ``RiskInterceptedError`` inherits from
    :class:`web.exceptions.RiskException` (i.e. ``except RiskException``
    catches engine-raised ``RiskInterceptedError`` instances).
    """
    return _INHERITS_RISK_EXCEPTION


__all__ = [
    "AgentEngineError",
    "ResourceNotFoundError",
    "InvalidParameterError",
    "ConcurrencyError",
    "RiskInterceptedError",
    "EngineInternalError",
    "is_http_exception_compatible",
    "is_risk_exception_compatible",
]
