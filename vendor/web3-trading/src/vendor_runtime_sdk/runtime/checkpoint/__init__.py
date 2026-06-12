# -*- coding: utf-8 -*-
"""
Checkpoint + Trajectory — local filesystem persistence for session snapshots
and ShareGPT-compatible fine-tuning data collection.

CheckpointManager  — save/load/list/prune session state snapshots
TrajectoryRecorder — append-only JSONL turn records (success + failure files)
"""

from vendor_runtime_sdk.runtime.checkpoint.manager import CheckpointManager, CheckpointRecord
from vendor_runtime_sdk.runtime.checkpoint.trajectory import TrajectoryRecorder

__all__ = [
    "CheckpointManager",
    "CheckpointRecord",
    "TrajectoryRecorder",
]
