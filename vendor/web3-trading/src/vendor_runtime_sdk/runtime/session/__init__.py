"""
Session management — FSM, Resume, Lineage (§5.4)

Implements the 6-state Session state machine:
idle → running → compacted → forked → terminated
                → requires_approval → running | terminated
                → failed | timeout → terminated
"""

from vendor_runtime_sdk.runtime.session.fsm import (
    TERMINAL_STATES,
    IllegalTransitionError,
    SessionFSM,
    SessionState,
    aggregate_child_states,
)
from vendor_runtime_sdk.runtime.session.lineage import (
    LineageReason,
    LineageRecord,
    SessionLineage,
)
from vendor_runtime_sdk.runtime.session.resume import (
    DataCorruptionError,
    EnvironmentDriftError,
    ResumedConfig,
    ResumeError,
    SessionResume,
    ToolSchemaDriftError,
    compute_env_vars_sha256,
    compute_tool_schemas_sha256,
)
from vendor_runtime_sdk.runtime.session_core import Session, SessionJournal

__all__ = [
    # FSM
    "SessionFSM",
    "SessionState",
    "IllegalTransitionError",
    "TERMINAL_STATES",
    "aggregate_child_states",
    # Lineage
    "SessionLineage",
    "LineageRecord",
    "LineageReason",
    # Resume
    "SessionResume",
    "ResumedConfig",
    "DataCorruptionError",
    "ToolSchemaDriftError",
    "EnvironmentDriftError",
    "ResumeError",
    "compute_tool_schemas_sha256",
    "compute_env_vars_sha256",
    # Session core
    "Session",
    "SessionJournal",
]
