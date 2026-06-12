# -*- coding: utf-8 -*-
"""V2 HITL auto-resume Prometheus metrics.

PRD reference: L4 — V2 ``hitl_auto_resume`` monitoring surface. The MVP
shipped in commit ``f6cf79a9`` and the deep tests landed in ``313d9da9``;
this module gives ops Grafana-actionable signals so a regression in
the continuation flow is visible without dogfood.

Metrics
-------
* ``hitl_auto_resume_total{outcome}`` — Counter of every
  ``continue_after_hitl_approval`` terminal disposition. Labels:

  - ``completed`` — resumed agent ran to natural end, SSE closed clean.
  - ``chained``  — resumed agent itself paused at another HITL gate;
    SSE stays open for the next /hitl/decide cycle.
  - ``qa_not_found`` — parent QA missing from mongo at resume time.
  - ``session_not_found`` — parent session missing.
  - ``mongo_error`` — any other mongo / schema load failure.
  - ``unexpected_error`` — anything else in the outer try/except.

* ``push_tool_envelope_total{final}`` — Counter of every
  ``push_tool_envelope`` call. ``final`` is ``"true"`` for V1 path
  (close SSE) and ``"false"`` for V2 path (keep SSE open). Lets ops
  see at a glance how much V2 traffic the gate is taking.

Design notes
------------
* Every recorder is a **no-op** when ``prometheus_client`` isn't
  installed. The whole module imports successfully in offline / CI /
  air-gapped environments — no hard dependency.
* Recorders never raise — observability must never break the resume
  hot path. Internal exceptions are swallowed at DEBUG.
* Label cardinality is bounded (≤6 outcome values, ≤2 final values) so
  Prometheus storage stays predictable.
"""

from __future__ import annotations

import logging
from typing import Final, Tuple

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter
    _HAS_PROMETHEUS: Final[bool] = True
except ImportError:  # pragma: no cover — offline fallback
    _HAS_PROMETHEUS = False


# Closed enum of outcome labels. Anything outside this set will be
# downgraded to ``unexpected_error`` to keep cardinality bounded.
_VALID_OUTCOMES: Final[Tuple[str, ...]] = (
    "completed",
    "chained",
    "qa_not_found",
    "session_not_found",
    "mongo_error",
    "unexpected_error",
)


if _HAS_PROMETHEUS:
    HITL_AUTO_RESUME_TOTAL = Counter(
        "hitl_auto_resume_total",
        "V2 HITL auto-resume continuation outcomes",
        ["outcome"],
    )

    PUSH_TOOL_ENVELOPE_TOTAL = Counter(
        "push_tool_envelope_total",
        "HITL approve tool-result envelope push (V1 vs V2 path)",
        ["final"],
    )


def record_auto_resume_outcome(outcome: str) -> None:
    """Increment ``hitl_auto_resume_total{outcome=...}``.

    Unknown outcome strings are normalised to ``unexpected_error`` so
    label cardinality stays bounded. No-op when prometheus_client
    isn't installed; never raises.
    """
    if not _HAS_PROMETHEUS:
        return
    normalised = outcome if outcome in _VALID_OUTCOMES else "unexpected_error"
    try:
        HITL_AUTO_RESUME_TOTAL.labels(outcome=normalised).inc()
    except Exception as exc:  # noqa: BLE001 — never let metrics break the hot path
        logger.debug("record_auto_resume_outcome skipped: %s", exc)


def record_push_envelope(final: bool) -> None:
    """Increment ``push_tool_envelope_total{final=...}``.

    ``final`` is normalised to the string ``"true"`` / ``"false"`` so
    Prometheus label semantics are deterministic (rather than relying
    on bool repr quirks across client versions).
    """
    if not _HAS_PROMETHEUS:
        return
    label = "true" if final else "false"
    try:
        PUSH_TOOL_ENVELOPE_TOTAL.labels(final=label).inc()
    except Exception as exc:  # noqa: BLE001
        logger.debug("record_push_envelope skipped: %s", exc)


__all__ = [
    "record_auto_resume_outcome",
    "record_push_envelope",
]
