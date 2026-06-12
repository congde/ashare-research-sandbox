# -*- coding: utf-8 -*-
"""
OpenTelemetry integration — Phase 7.1

Provides a thin, fail-soft wrapper around the OpenTelemetry SDK that bridges
the existing KuCoin AI Agent runtime into distributed tracing.

Design rules
------------
- **Fail-soft**: every OTEL operation is wrapped in try/except; any SDK failure
  degrades to a log warning and a no-op span, never interrupting the live path.
- **Toggle-gated**: all tracing is gated by the ``otel_tracing`` ModuleToggle.
  When the toggle is off, ``get_tracer()`` returns the global NoopTracer.
- **Non-invasive**: existing TelemetryRecorder and SpanEvent machinery is
  preserved unchanged; this module only *adds* an export path alongside it.
- **Single responsibility**: this module owns provider setup only.  Callers in
  ``conversation.py`` own their own span lifecycle.

Span hierarchy (one trace per agent turn):

  Trace (trace_id = new per turn)
  └── Span: agent_turn          (session_id, user_id, query[:100])
        ├── Span: tool_call     (tool_name, scope: tool_use)
        ├── Span: llm_inference (model, scope: llm_call)
        └── Event: <SpanEvent>  (span_type, metadata — bridged from SpanEvent)

Configuration (conf/default.yaml → observability:)::

    observability:
      otel_enabled: false          # master switch (also driven by toggle)
      otlp_endpoint: ""            # e.g. http://localhost:4317 (gRPC) or
                                   # http://localhost:4318 (http/protobuf)
      otlp_protocol: grpc          # grpc | http/protobuf
      service_name: kucoin-ai-agent
      sample_rate: 1.0             # 1.0 = sample everything

Env overrides (higher priority than conf/default.yaml):
  OTEL_ENABLED=true/false
  OTEL_EXPORTER_OTLP_ENDPOINT=http://...
  OTEL_SERVICE_NAME=kucoin-ai-agent

Usage::

    # App startup (application.py lifespan):
    from vendor_runtime_sdk.runtime.otel import setup_otel
    setup_otel(config)            # idempotent

    # At a span boundary:
    from vendor_runtime_sdk.runtime.otel import get_tracer, otel_is_active
    if otel_is_active():
        with get_tracer().start_as_current_span("agent_turn", attributes=...):
            ...
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)

# ── Internal state ─────────────────────────────────────────────────────────────

_setup_done: bool = False
_setup_lock = threading.Lock()
_otel_active: bool = False   # True only after a successful setup with a real exporter


# ── Config accessor ────────────────────────────────────────────────────────────


def _get_obs_config(app_config: Any) -> dict[str, Any]:
    """Extract observability sub-config from the app config object."""
    # Handle both AttrDict-style and plain dict configs
    obs = None
    if app_config is not None:
        try:
            obs = getattr(app_config, "observability", None)
        except Exception:
            pass
        if obs is None and isinstance(app_config, dict):
            obs = app_config.get("observability")

    if isinstance(obs, dict):
        return obs
    if obs is not None:
        # AttrDict / similar — convert to plain dict for uniform access
        try:
            return dict(obs)
        except Exception:
            pass
    return {}


# ── Provider setup ─────────────────────────────────────────────────────────────


def setup_otel(app_config: Any = None) -> None:
    """
    Initialise the OpenTelemetry provider.

    Idempotent — safe to call multiple times (only the first call takes effect).
    Fail-soft — any SDK or configuration error downgrades to a log warning and
    leaves OTEL inactive (``otel_is_active()`` returns False).

    Args:
        app_config: Application config object (AttrDict or dict).  When omitted
                    the function reads env vars and conf defaults.
    """
    global _setup_done, _otel_active

    if _setup_done:
        return

    with _setup_lock:
        if _setup_done:
            return
        _setup_done = True

        # ── Toggle check (runtime toggle gating) ──────────────────────────
        try:
            from vendor_runtime_sdk.runtime.config.guards import is_module_enabled
            if not is_module_enabled("otel_tracing"):
                logger.info("otel_tracing toggle disabled — OpenTelemetry not initialised")
                return
        except Exception:
            # Guards unavailable — check env var directly
            if os.getenv("RUNTIME__MODULES__OTL_TRACING__ENABLED", "false").lower() not in ("1", "true", "yes"):
                return

        # ── Load config ───────────────────────────────────────────────────
        obs = _get_obs_config(app_config)

        # Config values (env > yaml)
        otel_enabled = (
            os.getenv("OTEL_ENABLED", str(obs.get("otel_enabled", "false"))).lower()
            in ("1", "true", "yes")
        )
        if not otel_enabled:
            logger.info("observability.otel_enabled=false — OpenTelemetry not initialised")
            return

        endpoint = (
            os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            or obs.get("otlp_endpoint")
            or ""
        ).strip()
        protocol = (
            os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL")
            or obs.get("otlp_protocol")
            or "grpc"
        ).strip().lower()
        service_name = (
            os.getenv("OTEL_SERVICE_NAME")
            or obs.get("service_name")
            or "kucoin-ai-agent"
        )
        sample_rate = float(os.getenv("OTEL_SAMPLE_RATE", str(obs.get("sample_rate", 1.0))))

        # ── Import SDK ────────────────────────────────────────────────────
        try:
            from opentelemetry import trace as _trace
            from opentelemetry.sdk.resources import Resource, SERVICE_NAME
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.trace.sampling import TraceIdRatioBased, ALWAYS_ON
        except ImportError as exc:
            logger.warning("OpenTelemetry SDK not installed (%s) — tracing disabled", exc)
            return

        # ── Build exporter ────────────────────────────────────────────────
        span_exporter = None
        if endpoint:
            try:
                if protocol == "grpc":
                    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                    span_exporter = OTLPSpanExporter(endpoint=endpoint)
                else:
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                    span_exporter = OTLPSpanExporter(endpoint=endpoint)
                logger.info(
                    "[otel] OTLP exporter configured: endpoint=%s protocol=%s", endpoint, protocol
                )
            except Exception as exc:
                logger.warning("[otel] OTLP exporter creation failed (%s) — tracing disabled", exc)
                return
        else:
            # No endpoint configured — use in-process logger exporter for dev visibility
            try:
                from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
                span_exporter = InMemorySpanExporter()
                logger.info("[otel] No OTLP endpoint set — using in-memory exporter (dev mode)")
            except Exception:
                # In-memory not available — skip entirely
                logger.info("[otel] No OTLP endpoint set and in-memory exporter unavailable — tracing disabled")
                return

        # ── Build provider ────────────────────────────────────────────────
        try:
            sampler = ALWAYS_ON if sample_rate >= 1.0 else TraceIdRatioBased(sample_rate)
            resource = Resource(attributes={SERVICE_NAME: service_name})
            provider = TracerProvider(sampler=sampler, resource=resource)
            provider.add_span_processor(BatchSpanProcessor(span_exporter))
            _trace.set_tracer_provider(provider)
            _otel_active = True
            logger.info(
                "[otel] TracerProvider initialised: service=%s sample_rate=%.2f",
                service_name, sample_rate,
            )
        except Exception as exc:
            logger.warning("[otel] TracerProvider setup failed (%s) — tracing disabled", exc)
            return

        # ── Instrument FastAPI + httpx (when available) ───────────────────
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor().instrument()
            logger.info("[otel] FastAPI auto-instrumented")
        except Exception as exc:
            logger.debug("[otel] FastAPI instrumentation skipped: %s", exc)

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            HTTPXClientInstrumentor().instrument()
            logger.info("[otel] httpx auto-instrumented")
        except Exception as exc:
            logger.debug("[otel] httpx instrumentation skipped: %s", exc)


# ── Runtime accessors ──────────────────────────────────────────────────────────


def otel_is_active() -> bool:
    """Return True if OTEL was successfully initialised with a real exporter."""
    return _otel_active


def get_tracer(name: str = "kucoin.agent.runtime") -> Any:
    """
    Return an OpenTelemetry Tracer.

    When OTEL is inactive this returns the global NoopTracer, so callers can
    always call ``get_tracer().start_as_current_span(...)`` without branching.
    """
    try:
        from opentelemetry import trace as _trace
        return _trace.get_tracer(name)
    except Exception:
        return _NoopTracer()


def get_current_span() -> Any:
    """Return the currently active OTEL span (or a no-op span if none)."""
    try:
        from opentelemetry import trace as _trace
        return _trace.get_current_span()
    except Exception:
        return _NoopSpan()


# ── Span context manager helpers ───────────────────────────────────────────────


@contextmanager
def agent_turn_span(
    session_id: str,
    user_id: str,
    query: str,
    agent_type: str = "",
) -> Generator[Any, None, None]:
    """
    Context manager that wraps a single agent turn in an OTEL span.

    Usage::

        async with agent_turn_span(session_id, user_id, query):
            # run agent turn ...

    Fail-soft: any OTEL error yields the body without a span.
    """
    attrs = {
        "session.id": session_id or "",
        "user.id": user_id or "",
        "agent.type": agent_type or "",
        "query.preview": (query or "")[:120],
    }
    try:
        tracer = get_tracer()
        with tracer.start_as_current_span("agent_turn", attributes=attrs) as span:
            yield span
    except Exception as exc:
        logger.debug("[otel] agent_turn_span error: %s", exc)
        yield _NoopSpan()


@contextmanager
def tool_call_span(
    tool_name: str,
    session_id: str = "",
    success: Optional[bool] = None,
) -> Generator[Any, None, None]:
    """
    Context manager that wraps a single tool call in a child OTEL span.

    Fail-soft: any OTEL error yields the body without a span.
    """
    attrs = {
        "tool.name": tool_name or "",
        "session.id": session_id or "",
    }
    try:
        tracer = get_tracer()
        with tracer.start_as_current_span(f"tool_call:{tool_name}", attributes=attrs) as span:
            yield span
            if success is not None:
                try:
                    span.set_attribute("tool.success", success)
                except Exception:
                    pass
    except Exception as exc:
        logger.debug("[otel] tool_call_span error: %s", exc)
        yield _NoopSpan()


def add_span_event(span_type: str, metadata: dict[str, Any] | None = None) -> None:
    """
    Add a lightweight event to the *current* active OTEL span.

    Bridges the existing SpanEvent pattern to OTEL span events without
    coupling TelemetryRecorder to the OTEL SDK.  No-ops when OTEL is inactive.
    """
    if not _otel_active:
        return
    try:
        from opentelemetry import trace as _trace
        span = _trace.get_current_span()
        if span is not None and span.is_recording():
            span.add_event(
                span_type,
                attributes={k: str(v) for k, v in (metadata or {}).items() if v is not None},
            )
    except Exception as exc:
        logger.debug("[otel] add_span_event(%s) failed: %s", span_type, exc)


# ── Noop fallbacks ─────────────────────────────────────────────────────────────
# Returned by get_tracer() / get_current_span() when OTEL SDK is unavailable
# so callers never need to branch on `otel_is_active()`.


class _NoopSpan:
    """Drop-in replacement for an OTEL Span when tracing is disabled."""

    def is_recording(self) -> bool:
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def add_event(self, name: str, attributes: Any = None) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NoopTracer:
    """Drop-in replacement for an OTEL Tracer when tracing is disabled."""

    def start_as_current_span(self, name: str, **kwargs: Any) -> "_NoopSpan":  # type: ignore[override]
        return _NoopSpan()

    def start_span(self, name: str, **kwargs: Any) -> "_NoopSpan":
        return _NoopSpan()
