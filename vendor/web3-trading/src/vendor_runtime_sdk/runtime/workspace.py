# -*- coding: utf-8 -*-
"""
WorkspaceManager — Filesystem isolation for Lane execution.

From claw-code V2:
  Each Session binds to a workspace_root.
  All file operations, caches, and logs are confined to that directory.
  Prevents data races between parallel lanes.

Integration with existing code:
  - Reuses memory/paths.py MemoryLayout for directory structure
  - Reuses security/path_guard.py for path traversal protection
  - Each Lane gets its own workspace_root under ~/.ai-buddy/users/{user_id}/

Directory layout per workspace:
  {workspace_root}/
  ├── .runtime/           ← Session JSONL journals, temp files
  ├── .claude/            ← Claude Code-aligned memory (reuses memory/paths.py)
  ├── agent-memory/       ← Agent-type specific memory
  ├── sessions/           ← Session state files
  └── workspace/          ← Working directory for file operations
"""

from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Default base directory for all workspaces.
#
# Plan §3.5 — production reads ``AIBUDDY_WORKSPACE_BASE``; when unset, falls
# back to the legacy ``~/.ai-buddy`` path so existing local-dev workspaces
# on disk keep resolving to the same place. The ``users/{user_id}/lanes/..``
# structure underneath is unchanged.
#
# Resolution is lazy (called from ``WorkspaceManager.__init__``) rather than
# at import time so test harnesses that mutate ``AIBUDDY_WORKSPACE_BASE``
# between imports still pick up the new value. Mirrors the pattern in
# :mod:`runtime.checkpoint.manager` and :mod:`runtime.checkpoint.trajectory`.
def _resolve_default_base() -> Path:
    import os
    val = os.environ.get("AIBUDDY_WORKSPACE_BASE")
    if val:
        return Path(val)
    return Path.home() / ".ai-buddy"

# Module-level singleton — set during app startup, accessed everywhere
_workspace_manager: Optional["WorkspaceManager"] = None


def get_workspace_manager() -> "WorkspaceManager":
    """Return the process-level WorkspaceManager singleton.

    Raises RuntimeError if called before ``set_workspace_manager()``.
    """
    global _workspace_manager
    if _workspace_manager is None:
        # Auto-create a default instance (fail-soft for test / CLI)
        _workspace_manager = WorkspaceManager()
    return _workspace_manager


def set_workspace_manager(mgr: "WorkspaceManager") -> None:
    """Install the process-level WorkspaceManager singleton (called at startup)."""
    global _workspace_manager
    _workspace_manager = mgr


@dataclass
class WorkspaceInfo:
    """Workspace metadata"""

    workspace_id: str
    root: Path
    owner_id: str  # user_id or lane_id
    lane_id: Optional[str] = None
    is_isolated: bool = True
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_type: Optional[str] = None
    agents: list = field(default_factory=list)
    workflow: Optional[str] = None
    state: str = "idle"
    created_at: Optional[str] = None


class WorkspaceManager:
    """
    Workspace lifecycle manager — create, resolve, clean up isolated workspaces.

    Central authority for workspace isolation:
      - Tracks all known workspaces (in-memory registry)
      - Tracks active ConversationRuntime sessions per workspace
      - Bridges with DB-backed workspace DAOs for persistence
      - Provides workspace-scoped queries (sessions, budget, etc.)

    Usage:
        mgr = WorkspaceManager()
        ws = mgr.create_workspace(user_id="user_123", lane_id="lane_456")
        # ws.root = Path("/home/user/.ai-buddy/users/user_123/lanes/lane_456")
        ...
        mgr.cleanup_workspace(ws.workspace_id)
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self._base = base_dir or _resolve_default_base()
        self._workspaces: Dict[str, WorkspaceInfo] = {}
        # workspace_id → set of session_ids with active runtimes
        self._workspace_sessions: Dict[str, Set[str]] = {}
        # session_id → workspace_id reverse map
        self._session_workspace: Dict[str, str] = {}
        self._lock = threading.Lock()

    def create_workspace(
        self,
        user_id: str,
        lane_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        trigger_type: Optional[str] = None,
        agents: Optional[list] = None,
        workflow: Optional[str] = None,
    ) -> WorkspaceInfo:
        """
        Create an isolated workspace for a user + lane combination.

        Layout:
          - Default:  {base}/users/{user_id}/
          - With lane: {base}/users/{user_id}/lanes/{lane_id}/
        """
        import uuid
        from datetime import datetime

        ws_id = workspace_id or f"ws_{uuid.uuid4().hex[:8]}"

        if lane_id:
            root = self._base / "users" / user_id / "lanes" / lane_id
        else:
            root = self._base / "users" / user_id

        self._ensure_dirs(root)

        info = WorkspaceInfo(
            workspace_id=ws_id,
            root=root,
            owner_id=user_id,
            lane_id=lane_id,
            name=name or ws_id,
            description=description,
            trigger_type=trigger_type,
            agents=agents or [],
            workflow=workflow,
            created_at=datetime.utcnow().isoformat(),
        )
        self._workspaces[ws_id] = info
        logger.info("Created workspace %s at %s", ws_id, root)
        return info

    def resolve_workspace(self, user_id: str, lane_id: Optional[str] = None) -> Path:
        """
        Resolve the workspace root path for a user + lane.

        Does not create directories — use create_workspace() for that.
        """
        if lane_id:
            return self._base / "users" / user_id / "lanes" / lane_id
        return self._base / "users" / user_id

    def get_workspace(self, workspace_id: str) -> Optional[WorkspaceInfo]:
        """Get workspace info by ID"""
        return self._workspaces.get(workspace_id)

    def get_or_create(
        self,
        user_id: str,
        lane_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> WorkspaceInfo:
        """Get existing workspace or create a new one.

        If *workspace_id* is provided and already registered, returns the
        existing WorkspaceInfo. Otherwise searches by user_id + lane_id.
        Falls back to creating a new workspace.
        """
        if workspace_id and workspace_id in self._workspaces:
            return self._workspaces[workspace_id]
        # Try to find existing workspace for this user+lane
        for ws in self._workspaces.values():
            if ws.owner_id == user_id and ws.lane_id == lane_id:
                return ws
        return self.create_workspace(
            user_id=user_id, lane_id=lane_id,
            workspace_id=workspace_id, name=name,
        )

    def cleanup_workspace(self, workspace_id: str) -> bool:
        """
        Clean up a workspace — removes temporary files but preserves
        important artifacts (memory, journals).

        Returns True if cleanup succeeded.
        """
        info = self._workspaces.get(workspace_id)
        if not info:
            return False

        runtime_dir = info.root / ".runtime"
        if runtime_dir.exists():
            try:
                shutil.rmtree(runtime_dir, ignore_errors=True)
                logger.info("Cleaned up runtime dir for workspace %s", workspace_id)
            except Exception as e:
                logger.warning("Failed to cleanup workspace %s: %s", workspace_id, e)
                return False

        self._workspaces.pop(workspace_id, None)
        return True

    def validate_path(self, workspace_root: Path, target: Path) -> Path:
        """
        Validate that a target path is within the workspace root.
        Uses security/path_guard.py logic.

        Raises ValueError if path escapes workspace.
        """
        try:
            from security.path_guard import resolve_safe_path
            return resolve_safe_path(str(workspace_root), str(target))
        except ImportError:
            # Fallback: simple containment check
            resolved = target.resolve()
            root_resolved = workspace_root.resolve()
            if not str(resolved).startswith(str(root_resolved)):
                raise ValueError(
                    f"Path {target} escapes workspace {workspace_root}"
                )
            return resolved

    def list_workspaces(self, user_id: Optional[str] = None) -> List[WorkspaceInfo]:
        """List all known workspaces, optionally filtered by user"""
        if user_id:
            return [ws for ws in self._workspaces.values() if ws.owner_id == user_id]
        return list(self._workspaces.values())

    # ──────────────── Session tracking ────────────────

    def register_session(self, workspace_id: str, session_id: str) -> None:
        """Register an active session under a workspace.

        Called by ConversationRuntime.__init__ / wrap_agent_stream when
        the runtime is created with a workspace_id.
        """
        if not workspace_id or not session_id:
            return
        with self._lock:
            self._workspace_sessions.setdefault(workspace_id, set()).add(session_id)
            self._session_workspace[session_id] = workspace_id
        logger.debug(
            "WorkspaceManager: registered session %s → workspace %s",
            session_id, workspace_id,
        )

    def unregister_session(self, session_id: str) -> None:
        """Unregister a session when its runtime completes.

        Called by ConversationRuntime._unregister().
        """
        if not session_id:
            return
        with self._lock:
            ws_id = self._session_workspace.pop(session_id, None)
            if ws_id and ws_id in self._workspace_sessions:
                self._workspace_sessions[ws_id].discard(session_id)
                if not self._workspace_sessions[ws_id]:
                    del self._workspace_sessions[ws_id]
        logger.debug("WorkspaceManager: unregistered session %s", session_id)

    def get_workspace_sessions(self, workspace_id: str) -> List[str]:
        """Return active session_ids for a workspace."""
        with self._lock:
            return list(self._workspace_sessions.get(workspace_id, set()))

    def get_session_workspace(self, session_id: str) -> Optional[str]:
        """Return the workspace_id that a session belongs to."""
        with self._lock:
            return self._session_workspace.get(session_id)

    def get_workspace_runtime_summary(self, workspace_id: str) -> Dict:
        """Build a runtime state summary for a workspace.

        Aggregates data from all active ConversationRuntime instances
        registered under *workspace_id*. Used by staff/workspace and
        admin dashboard APIs.
        """
        from vendor_runtime_sdk.runtime.conversation import ConversationRuntime

        session_ids = self.get_workspace_sessions(workspace_id)
        sessions_data: list = []
        total_tokens = 0
        max_pressure = "NORMAL"
        fallback_count = 0
        by_fsm: Dict[str, int] = {}
        tools_used: Dict[str, int] = {}
        _PRESSURE_ORDER = {"NORMAL": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}

        for sid in session_ids:
            rt = ConversationRuntime.get_active(sid)
            if rt is None:
                continue
            try:
                snap = rt.snapshot()
            except Exception:
                continue

            tokens = snap.get("tokens", {}).get("total", 0)
            total_tokens += tokens

            pressure = snap.get("budget", {}).get("pressure", "NORMAL")
            if _PRESSURE_ORDER.get(pressure, 0) > _PRESSURE_ORDER.get(max_pressure, 0):
                max_pressure = pressure

            if snap.get("fallback", {}).get("active"):
                fallback_count += 1

            fsm = snap.get("fsm_state", "UNKNOWN")
            by_fsm[fsm] = by_fsm.get(fsm, 0) + 1

            tool = snap.get("activity", {}).get("current_tool", "")
            if tool:
                tools_used[tool] = tools_used.get(tool, 0) + 1

            sessions_data.append({
                "session_id": sid,
                "fsm_state": fsm,
                "budget_pressure": pressure,
                "tokens": tokens,
                "fallback_active": snap.get("fallback", {}).get("active", False),
                "current_tool": tool,
            })

        return {
            "workspace_id": workspace_id,
            "active_sessions": len(sessions_data),
            "total_tokens": total_tokens,
            "budget_pressure": max_pressure,
            "fallback_active": fallback_count > 0,
            "fallback_active_sessions": fallback_count,
            "by_budget_pressure": {
                s["budget_pressure"]: sum(
                    1 for x in sessions_data if x["budget_pressure"] == s["budget_pressure"]
                )
                for s in sessions_data
            },
            "by_fsm_state": by_fsm,
            "tools_used": tools_used,
            "sessions": sessions_data,
        }

    def interrupt_workspace_sessions(self, workspace_id: str, reason: str = "workspace_archived") -> int:
        """Interrupt all active sessions in a workspace.

        Returns the number of sessions interrupted. Used when a workspace
        is archived or paused.
        """
        from vendor_runtime_sdk.runtime.conversation import ConversationRuntime

        count = 0
        for sid in self.get_workspace_sessions(workspace_id):
            rt = ConversationRuntime.get_active(sid)
            if rt is not None:
                rt.request_interrupt(reason)
                count += 1
        logger.info(
            "WorkspaceManager: interrupted %d sessions in workspace %s (%s)",
            count, workspace_id, reason,
        )
        return count

    # ──────────────── DB bridge ────────────────

    async def sync_from_db(self, workspace_id: str) -> Optional[WorkspaceInfo]:
        """Load workspace metadata from the MySQL DAO and register it.

        Returns the WorkspaceInfo if found, None otherwise.
        Fail-soft: any import/DB error returns None without raising.
        """
        try:
            from dao.mysql.workspace import get_workspace_dao
            dao = get_workspace_dao()
            row = await dao.get_by_id(workspace_id)
            if not row:
                return None

            info = WorkspaceInfo(
                workspace_id=row.id,
                root=self._base / "users" / (row.owner_id or "system"),
                owner_id=row.owner_id or "system",
                name=row.name,
                description=row.description,
                trigger_type=row.trigger_type,
                agents=list(row.agents) if row.agents else [],
                workflow=row.workflow,
                state=row.state,
            )
            self._workspaces[row.id] = info
            self._ensure_dirs(info.root)
            return info
        except Exception as exc:
            logger.debug("WorkspaceManager.sync_from_db(%s) failed: %s", workspace_id, exc)
            return None

    # ──────────────── Internal ────────────────

    def _ensure_dirs(self, root: Path) -> None:
        """Create the standard directory structure"""
        dirs = [
            root / ".runtime",
            root / ".claude",
            root / "agent-memory",
            root / "sessions",
            root / "workspace",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
