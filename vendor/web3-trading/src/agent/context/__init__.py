# -*- coding: utf-8 -*-
"""
Context Management — OpenClaw-inspired context persistence and assembly.

Two-layer persistence:
  - SessionModel (index): compaction cursors, counters, token estimates
  - Transcript (event log): append-only stream of all conversation events

Tree-structured transcript:
  - id/parentId tree enables branching for dirty work (tool retries, plan exploration)
  - branch_summary merges results back to the main line

Pre-compaction flush:
  - Before compressing old context, force-persist critical state (memory_flush)
  - Then summarize old events (compaction_summary)
  - Long tasks rely on "system saved what matters" not "model remembers"
"""

from agent.context.models import (
    TranscriptEvent,
    TranscriptEventType,
    ContextWindow,
)
from agent.context.writer import TranscriptWriter
from agent.context.reader import TranscriptReader
from agent.context.assembler import ContextAssembler
from agent.context.token_budget import TokenBudget, estimate_tokens
from agent.context.compactor import Compactor
from agent.context.branch import BranchManager

__all__ = [
    "TranscriptEvent",
    "TranscriptEventType",
    "ContextWindow",
    "TranscriptWriter",
    "TranscriptReader",
    "ContextAssembler",
    "TokenBudget",
    "estimate_tokens",
    "Compactor",
    "BranchManager",
]
