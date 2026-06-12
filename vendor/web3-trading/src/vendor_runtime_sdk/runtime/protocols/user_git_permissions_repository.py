# -*- coding: utf-8 -*-
"""
UserGitPermissionsRepository — PR-E4b of the Agent Engine SDK extraction.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E4b.

Goal
----
Replace the engine layer's direct dependency on
``dao.mysql.user_git_permissions`` (the ai-buddy-specific MySQL DAO
singleton + helper functions) with a Protocol-based seam. SDK consumers
install their own :class:`UserGitPermissionsRepository` at boot;
ai-buddy installs an adapter that wraps
:func:`dao.mysql.user_git_permissions.UserGitPermissionsDao` so the
existing engine code path is byte-identical.

Today the engine call sites do::

    from dao.mysql.user_git_permissions import GitAccessLevel, allows
    granted = await dao.get_access(...)
    if not allows(granted, GitAccessLevel.WRITE): ...

That import path is unreachable when the engine is packaged as the SDK.
PR-E4b introduces the abstraction.

Scope (V1)
----------
The audit shows 23 call sites across four engine files:

* ``src/runtime/tools/git_repo_acl_hook.py`` — pre-tool hook checks
  user's repo access against the user_git_permissions snapshot.
* ``src/runtime/vault/ephemeral_git_token.py`` — references
  :class:`GitAccessLevel` only.
* ``src/agent/git_acl.py`` — validates agent ACL subset against user
  ACL via the module-level :func:`allows` helper.
* ``src/agent/git_onboarding.py`` — bulk-replace flow uses
  :meth:`replace_set` and :class:`UserGitPermissionRow`.

UNIQUE re-export shape: the legacy module exposes a module-level
:func:`allows` *function* (not just a DAO method) + the
:class:`GitAccessLevel` enum + the :class:`UserGitPermissionRow`
dataclass. The Protocol re-exports the enum + dataclass via the same
try/except ImportError shim as :class:`CostRecordRow`. The legacy
:func:`allows` becomes an *instance method* on the Protocol — invoking
it through the repository keeps the SDK boundary clean and lets future
implementations back permissions with a remote ACL service.

Fall-back path (PR-E4b only; deleted in Phase 2)
------------------------------------------------
When no provider is installed via
:func:`set_user_git_permissions_repository`,
:func:`get_user_git_permissions_repository` lazily synthesises one that
wraps :class:`dao.mysql.user_git_permissions.UserGitPermissionsDao`.

Same pattern as PR-E4 :class:`WorkflowRunRepository` /
:class:`CostRecordRepository`.
"""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    List,
    Optional,
    Protocol,
    Sequence,
    Union,
    runtime_checkable,
)

logger = logging.getLogger(__name__)


# ── GitAccessLevel + UserGitPermissionRow re-export ────────────────────


try:
    from dao.mysql.user_git_permissions import (
        GitAccessLevel as _LegacyGitAccessLevel,
    )
    from dao.mysql.user_git_permissions import (
        UserGitPermissionRow as _LegacyUserGitPermissionRow,
    )
    GitAccessLevel = _LegacyGitAccessLevel  # type: ignore[misc,assignment]
    UserGitPermissionRow = _LegacyUserGitPermissionRow  # type: ignore[misc,assignment]
except ImportError:  # pragma: no cover — SDK-extracted scenario only
    class GitAccessLevel(str, Enum):  # type: ignore[no-redef]
        """Minimal local replica of
        :class:`dao.mysql.user_git_permissions.GitAccessLevel`.

        Activated only when ``dao.mysql.user_git_permissions`` is not
        importable.
        """

        READ = "read"
        WRITE = "write"

    _VALID_SOURCES = frozenset({"gitlab", "bitbucket", "manual", "celery"})

    @dataclass
    class UserGitPermissionRow:  # type: ignore[no-redef]
        """Minimal local replica of
        :class:`dao.mysql.user_git_permissions.UserGitPermissionRow`.

        Activated only when ``dao.mysql.user_git_permissions`` is not
        importable.
        """

        user_id: str = ""
        workspace_id: str = ""
        repo: str = ""
        access: str = "read"
        last_synced_at: float = field(default_factory=time.time)
        source: str = "gitlab"
        created_at: str = ""
        updated_at: str = ""

        def __post_init__(self) -> None:
            if not self.user_id:
                raise ValueError("user_id is required")
            if not self.workspace_id:
                raise ValueError("workspace_id is required")
            if not self.repo:
                raise ValueError("repo is required")
            if self.access not in {lvl.value for lvl in GitAccessLevel}:
                raise ValueError(f"invalid access level: {self.access!r}")
            if self.source not in _VALID_SOURCES:
                raise ValueError(f"invalid source: {self.source!r}")


def allows_pure(
    granted: Union[str, GitAccessLevel],
    requested: Union[str, GitAccessLevel],
) -> bool:
    """Pure-function variant of :func:`dao.mysql.user_git_permissions.allows`.

    Local to this module so engine code does not have to reach into the
    legacy DAO for the helper. Mirrors the legacy semantics exactly:
    ``READ`` is satisfied by ``READ`` or ``WRITE``; ``WRITE`` requires
    ``WRITE``.
    """
    g = (
        GitAccessLevel(granted)
        if not isinstance(granted, GitAccessLevel)
        else granted
    )
    r = (
        GitAccessLevel(requested)
        if not isinstance(requested, GitAccessLevel)
        else requested
    )
    if r is GitAccessLevel.READ:
        return g in (GitAccessLevel.READ, GitAccessLevel.WRITE)
    return g is GitAccessLevel.WRITE


class UserGitPermissionsRepositoryNotInstalledError(RuntimeError):
    """Raised when :func:`get_user_git_permissions_repository` is called
    before any repository is installed AND the legacy
    ``dao.mysql.user_git_permissions`` fallback is not reachable.
    """


@runtime_checkable
class UserGitPermissionsRepository(Protocol):
    """Pluggable repository for user git permission snapshots.

    Methods cover the 23 audited engine call sites:

    * :meth:`find_by_user` — per-task ACL snapshot dump.
    * :meth:`get_access` — fast-path single-repo lookup.
    * :meth:`allows` — async wrapper around the access-level comparison
      so future remote-ACL implementations can re-route.
    * :meth:`replace_set` — bulk onboarding / Celery refresh.
    * :meth:`upsert` — single-row admin update.

    The legacy module-level :func:`allows` is intentionally **sync**
    (it's a pure enum comparison, no IO). Making the Protocol method
    async is intentional: future implementations may back permissions
    with a remote service (GitLab API call). The in-memory impl wraps
    the sync helper.

    Implementations MUST be safe to call concurrently — ACL checks
    happen on every git command.
    """

    async def find_by_user(
        self,
        *,
        user_id: str,
        workspace_id: str,
    ) -> List[UserGitPermissionRow]:
        """Return every repo permission for ``(user_id, workspace_id)``.

        Returns an empty list when no rows are present — the ACL hook
        treats absent users as "no access".
        """
        ...

    async def get_access(
        self,
        *,
        user_id: str,
        workspace_id: str,
        repo: str,
    ) -> Optional[GitAccessLevel]:
        """Single-repo access-level fast path. Returns ``None`` when the
        ``(user, workspace, repo)`` triple has no row.
        """
        ...

    async def allows(
        self,
        *,
        user_id: str,
        workspace_id: str,
        repo: str,
        requested: GitAccessLevel,
    ) -> bool:
        """Return ``True`` when the user's stored access satisfies the
        requested level. Composes :meth:`get_access` + the access-level
        lattice (``WRITE`` implies ``READ``).
        """
        ...

    async def replace_set(
        self,
        *,
        user_id: str,
        workspace_id: str,
        rows: Sequence[UserGitPermissionRow],
    ) -> None:
        """Set-diff replace — drops revoked rows + upserts the new set.

        Used by the admin-forced and Celery refresh paths.
        Implementations MUST honour the version-vector arbitration of
        the production DAO when writing through SQL.
        """
        ...

    async def upsert(self, row: UserGitPermissionRow) -> None:
        """Insert-or-update a single permission row."""
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_user_git_permissions_repository: Optional[UserGitPermissionsRepository] = None


def set_user_git_permissions_repository(
    repo: UserGitPermissionsRepository,
) -> None:
    """Install the UserGitPermissionsRepository used by engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot
    order is auditable.  **Never** logs the repo contents.

    Raises:
        TypeError: when ``repo`` does not satisfy the
            :class:`UserGitPermissionsRepository` Protocol at the
            structural level.
    """
    if not isinstance(repo, UserGitPermissionsRepository):
        raise TypeError(
            f"set_user_git_permissions_repository: repo must satisfy "
            f"UserGitPermissionsRepository Protocol (find_by_user / "
            f"get_access / allows / replace_set / upsert), "
            f"got {type(repo).__name__}"
        )
    global _user_git_permissions_repository
    _user_git_permissions_repository = repo
    logger.info(
        "UserGitPermissionsRepository installed: %s", type(repo).__name__
    )


def get_user_git_permissions_repository() -> UserGitPermissionsRepository:
    """Return the installed repository, falling back to a lazy adapter
    when ``dao.mysql.user_git_permissions`` is importable.

    Raises:
        UserGitPermissionsRepositoryNotInstalledError: when no
            repository is installed AND
            ``dao.mysql.user_git_permissions`` is not importable.
    """
    if _user_git_permissions_repository is not None:
        return _user_git_permissions_repository

    try:
        import importlib
        importlib.import_module("dao.mysql.user_git_permissions")
    except ImportError as exc:
        raise UserGitPermissionsRepositoryNotInstalledError(
            "UserGitPermissionsRepository has not been installed and "
            "dao.mysql.user_git_permissions is not importable. Call "
            "set_user_git_permissions_repository(repo) at boot before "
            "any engine code path runs."
        ) from exc

    return _LegacyUserGitPermissionsRepository.get_singleton()


def reset_user_git_permissions_repository_for_test() -> None:
    """Test-only helper to clear the installed repository between cases."""
    global _user_git_permissions_repository
    _user_git_permissions_repository = None
    _LegacyUserGitPermissionsRepository.reset_singleton_for_test()


# ── Legacy user_git_permissions adapter (fallback) ──────────────────────


class _LegacyUserGitPermissionsRepository:
    """Adapter that exposes
    :class:`dao.mysql.user_git_permissions.UserGitPermissionsDao` via
    the :class:`UserGitPermissionsRepository` Protocol.

    Constructs a fresh DAO instance lazily so the adapter survives
    early-boot. The DAO itself is stateful (table-ensured flag) but
    cheap to construct — we don't need to reuse the production
    singleton here because the DAO methods all go through
    ``component.get("mysql")``.
    """

    _SINGLETON: Optional["_LegacyUserGitPermissionsRepository"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyUserGitPermissionsRepository":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    def __init__(self) -> None:
        self._dao_instance: Any = None

    def _dao(self) -> Any:
        if self._dao_instance is not None:
            return self._dao_instance
        try:
            from dao.mysql.user_git_permissions import (
                UserGitPermissionsDao,
            )
        except ImportError:
            return None
        self._dao_instance = UserGitPermissionsDao()
        return self._dao_instance

    async def find_by_user(
        self,
        *,
        user_id: str,
        workspace_id: str,
    ) -> List[UserGitPermissionRow]:
        dao = self._dao()
        if dao is None:
            raise UserGitPermissionsRepositoryNotInstalledError(
                "_LegacyUserGitPermissionsRepository: "
                "dao.mysql.user_git_permissions not importable"
            )
        return list(await dao.find_by_user(user_id, workspace_id))

    async def get_access(
        self,
        *,
        user_id: str,
        workspace_id: str,
        repo: str,
    ) -> Optional[GitAccessLevel]:
        dao = self._dao()
        if dao is None:
            raise UserGitPermissionsRepositoryNotInstalledError(
                "_LegacyUserGitPermissionsRepository: "
                "dao.mysql.user_git_permissions not importable"
            )
        return await dao.get_access(user_id, workspace_id, repo)

    async def allows(
        self,
        *,
        user_id: str,
        workspace_id: str,
        repo: str,
        requested: GitAccessLevel,
    ) -> bool:
        granted = await self.get_access(
            user_id=user_id, workspace_id=workspace_id, repo=repo
        )
        if granted is None:
            return False
        return allows_pure(granted, requested)

    async def replace_set(
        self,
        *,
        user_id: str,
        workspace_id: str,
        rows: Sequence[UserGitPermissionRow],
    ) -> None:
        dao = self._dao()
        if dao is None:
            raise UserGitPermissionsRepositoryNotInstalledError(
                "_LegacyUserGitPermissionsRepository: "
                "dao.mysql.user_git_permissions not importable"
            )
        await dao.replace_set(user_id, workspace_id, rows)

    async def upsert(self, row: UserGitPermissionRow) -> None:
        dao = self._dao()
        if dao is None:
            raise UserGitPermissionsRepositoryNotInstalledError(
                "_LegacyUserGitPermissionsRepository: "
                "dao.mysql.user_git_permissions not importable"
            )
        await dao.upsert(row)


# ── In-memory UserGitPermissionsRepository for tests + SDK default ─────


class InMemoryUserGitPermissionsRepository:
    """UserGitPermissionsRepository impl for tests and SDK self-bundled
    default.

    Backed by a single dict ``_rows[(user_id, workspace_id, repo)] =
    UserGitPermissionRow``. All reads return deep copies.

    Concurrency: not strictly atomic across asyncio tasks — production
    multi-pod deployments must NOT share an in-memory repository.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], UserGitPermissionRow] = {}

    async def find_by_user(
        self,
        *,
        user_id: str,
        workspace_id: str,
    ) -> List[UserGitPermissionRow]:
        return [
            copy.deepcopy(r)
            for (uid, wid, _repo), r in self._rows.items()
            if uid == user_id and wid == workspace_id
        ]

    async def get_access(
        self,
        *,
        user_id: str,
        workspace_id: str,
        repo: str,
    ) -> Optional[GitAccessLevel]:
        row = self._rows.get((user_id, workspace_id, repo))
        if row is None:
            return None
        return GitAccessLevel(row.access)

    async def allows(
        self,
        *,
        user_id: str,
        workspace_id: str,
        repo: str,
        requested: GitAccessLevel,
    ) -> bool:
        granted = await self.get_access(
            user_id=user_id, workspace_id=workspace_id, repo=repo
        )
        if granted is None:
            return False
        return allows_pure(granted, requested)

    async def replace_set(
        self,
        *,
        user_id: str,
        workspace_id: str,
        rows: Sequence[UserGitPermissionRow],
    ) -> None:
        # Determine the set of repos in the new payload.
        new_repos = {r.repo for r in rows}
        # Drop any existing rows for this user/workspace that are NOT in
        # the new payload — mirrors `replace_set` semantics in the DAO.
        existing_keys = [
            key
            for key in list(self._rows.keys())
            if key[0] == user_id
            and key[1] == workspace_id
            and key[2] not in new_repos
        ]
        for key in existing_keys:
            self._rows.pop(key, None)
        # Apply version-vector arbitrated upserts.
        for row in rows:
            await self.upsert(row)

    async def upsert(self, row: UserGitPermissionRow) -> None:
        key = (row.user_id, row.workspace_id, row.repo)
        existing = self._rows.get(key)
        if existing is not None:
            # Version-vector guard — only accept newer rows for the
            # `access` / `source` fields.
            if (
                getattr(row, "last_synced_at", 0)
                < getattr(existing, "last_synced_at", 0)
            ):
                return
        self._rows[key] = copy.deepcopy(row)

    # ── Test helpers (not part of the Protocol) ──────────────────

    def seed(self, row: UserGitPermissionRow) -> None:
        key = (row.user_id, row.workspace_id, row.repo)
        self._rows[key] = copy.deepcopy(row)

    def list_keys(self) -> List[tuple[str, str, str]]:
        return list(self._rows.keys())

    def clear(self) -> None:
        self._rows.clear()


__all__ = [
    "GitAccessLevel",
    "UserGitPermissionRow",
    "UserGitPermissionsRepository",
    "UserGitPermissionsRepositoryNotInstalledError",
    "InMemoryUserGitPermissionsRepository",
    "allows_pure",
    "set_user_git_permissions_repository",
    "get_user_git_permissions_repository",
    "reset_user_git_permissions_repository_for_test",
]
# ``_LegacyUserGitPermissionsRepository`` is intentionally NOT exported
# — it is a private fallback helper.  ``allows_pure`` IS exported
# because production engine modules (src/agent/git_acl.py and
# src/runtime/tools/git_repo_acl_hook.py) use it as the pure-function
# permission-level comparator.  Pre-review it was named
# ``_allows_static`` and imported as private — reviewer caught this
# as a public-API-via-private-name violation.
