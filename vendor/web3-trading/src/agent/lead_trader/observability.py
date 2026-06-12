# -*- coding: utf-8 -*-

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
import time
import uuid
from typing import Callable, Dict, List, Optional


class EventType(str, Enum):
    SIGNAL_GENERATED = "signal.generated"
    TOOL_CALLED = "tool.called"


@dataclass
class TraceContext:
    trace_id: str
    user_id: str = ""
    started_at: float = field(default_factory=time.time)
    events: List[Dict] = field(default_factory=list)

    @property
    def elapsed_ms(self) -> int:
        return int((time.time() - self.started_at) * 1000)

    def add_event(self, event_name: str, **kwargs) -> None:
        self.events.append({"event": event_name, "ts": time.time(), **kwargs})


_trace_ctx: ContextVar[Optional[TraceContext]] = ContextVar("lead_trader_trace", default=None)


def init_trace_context(trace_id: Optional[str] = None, user_id: str = "") -> TraceContext:
    tid = trace_id or f"tr-{uuid.uuid4().hex[:10]}"
    ctx = TraceContext(trace_id=tid, user_id=user_id)
    _trace_ctx.set(ctx)
    return ctx


def get_trace_context() -> Optional[TraceContext]:
    return _trace_ctx.get()


class EventRecorder:
    def __init__(self, handlers: Optional[List[Callable[[Dict], None]]] = None):
        self._handlers = handlers or []

    def record(self, event_type: EventType, **payload) -> Dict:
        ctx = get_trace_context()
        event = {
            "event_type": event_type.value,
            "timestamp": time.time(),
            **payload,
        }
        if ctx is not None:
            event["trace_id"] = ctx.trace_id
            ctx.add_event(event_type.value, **payload)
        for handler in self._handlers:
            handler(event)
        return event

    def record_signal_event(self, pair: str, direction: str, score: float, confidence: float) -> Dict:
        return self.record(
            EventType.SIGNAL_GENERATED,
            pair=pair,
            direction=direction,
            score=score,
            confidence=confidence,
        )

    def record_tool_event(self, tool_name: str, success: bool, duration_ms: int) -> Dict:
        return self.record(
            EventType.TOOL_CALLED,
            tool_name=tool_name,
            success=bool(success),
            duration_ms=int(duration_ms),
        )
