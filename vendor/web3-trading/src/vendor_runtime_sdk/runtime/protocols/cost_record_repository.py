# -*- coding: utf-8 -*-
"""
CostRecordRepository — PR-E4 of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E4.

Goal
----
Replace the engine layer's direct dependency on
``dao.mysql.cost_record`` (the ai-buddy-specific MySQL DAO singleton)
with a Protocol-based seam. SDK consumers install their own
CostRecordRepository at boot; ai-buddy installs an adapter that wraps
``get_cost_record_dao()`` so the existing engine code path is
byte-identical.

Today every engine call site that persists or reads cost records does::

    from dao.mysql.cost_record import get_cost_record_dao, CostRecordRow
    dao = get_cost_record_dao()
    await dao.create(rec)                               # write per LLM/tool call
    await dao.add_record(rec)                           # CLI offline-sync write
    await dao.get_monthly_cost(workspace_id=ws_id)      # AlertPolicy MTD aggregate

Cost tracking is the BUDGET enforcement seam — ``avatar_budget_cap``,
fallback decisions, and MTD aggregates feed :mod:`runtime.alert.service`
so the engine cannot ship without it. Protocol surface is intentionally
narrow (3 methods, exactly what the audit shows engine code does).

Scope (V1)
----------
This PR handles the 2 tier-1 call-site anchors:

* ``src/runtime/hooks/cost_tracking.py`` — 2 write callsites
  (``record_llm_cost`` + ``record_tool_cost``)
* ``src/runtime/alert/metrics.py`` — 1 read callsite
  (``get_monthly_cost`` for AlertMetrics MTD aggregate)

The sibling ``alert_config`` DAO callsite in
``runtime/alert/metrics.py:42`` is deferred to PR-E4b — single read of
budget config, doesn't justify its own Protocol surface in V1.

Return-type contracts
---------------------
* :meth:`create` returns ``Optional[str]`` (the inserted row id) —
  fire-and-forget, ``None`` on failure mirrors the current ``logger.
  warning + return None`` contract in ``cost_tracking.py``.
* :meth:`add_record` returns ``None`` — preserves the storage/
  mongo_backend.py:298 call-site contract. The two verbs look like the
  same write but the production DAO has different return semantics —
  collapsing them would break the offline-sync caller silently.
* :meth:`get_monthly_cost` returns ``Decimal`` (non-negotiable for
  financial accuracy per audit doc §Gap 5). Returns ``Decimal('0')``
  when there are no matching records — NOT ``None``.

CostRecordRow re-export
-----------------------
:class:`CostRecordRow` currently lives in ``src/dao/mysql/cost_record.
py``. PR-E4 re-exports it from this protocol module via a guarded
import: when ``dao.mysql.cost_record`` is reachable we re-export the
canonical dataclass; otherwise we synthesise a minimal local replica
with the same field surface. In Phase 2 (post-extraction) the local
replica becomes the canonical definition and the ``dao.mysql``
version is deleted.

Fall-back path (PR-E4 only; deleted in Phase 2)
-----------------------------------------------
When no repository is installed via :func:`set_cost_record_repository`,
:func:`get_cost_record_repository` lazily synthesises one that wraps
:func:`dao.mysql.cost_record.get_cost_record_dao`. This makes PR-E4
a zero-behaviour-change refactor for ai-buddy's current boot path.

Same pattern as PR-E1 :class:`EngineConfig`, PR-E3
:class:`ContextStore`, and PR-E5 :class:`BackendClientProvider` —
engine carries its own contract; business layer keeps its own
concrete types; the SDK seam lives at the import boundary.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── CostRecordRow re-export ─────────────────────────────────────────────
#
# Re-export the canonical dataclass when ``dao.mysql.cost_record`` is
# reachable so engine code only needs to know the Protocol module.
# When the SDK is extracted (Phase 2) the local replica below becomes
# the canonical definition; until then the legacy one wins so we don't
# accidentally bind to a partially-overlapping shape.

try:
    from dao.mysql.cost_record import CostRecordRow as _LegacyCostRecordRow
    CostRecordRow = _LegacyCostRecordRow  # type: ignore[misc,assignment]
except ImportError:  # pragma: no cover — exercised only in SDK-extracted scenario
    @dataclass
    class CostRecordRow:  # type: ignore[no-redef]
        """Minimal local replica of
        :class:`dao.mysql.cost_record.CostRecordRow`.

        Mirrors the field surface used by engine call sites. Fields
        not consumed by the engine (e.g. ``recorded_at`` /
        ``created_at`` audit timestamps) are accepted but not required.
        Replica is activated only when ``dao.mysql.cost_record`` is
        not importable — i.e. the SDK-extracted scenario where the
        ``dao/`` package is no longer on the import path.
        """

        id: str = ""
        cost_type: str = "llm_token"
        cost_amount: Decimal = field(default_factory=lambda: Decimal("0"))
        currency: str = "CNY"
        workspace_id: Optional[str] = None
        session_id: Optional[str] = None
        agent_id: Optional[str] = None
        avatar_id: Optional[str] = None
        issue_id: Optional[str] = None
        agent_type: Optional[str] = None
        parent_agent_id: Optional[str] = None
        tool_id: Optional[str] = None
        model_name: Optional[str] = None
        requested_model: Optional[str] = None
        is_fallback: bool = False
        fallback_attempt: int = 0
        turn_number: int = 0
        token_input: int = 0
        token_output: int = 0
        cache_creation_tokens: int = 0
        cache_read_tokens: int = 0
        cache_hit_ratio: float = 0.0
        request_id: Optional[str] = None
        user_id: Optional[str] = None
        recorded_at: str = ""
        created_at: str = ""


class CostRecordRepositoryNotInstalledError(RuntimeError):
    """Raised when :func:`get_cost_record_repository` is called before
    any repository is installed AND the legacy
    ``dao.mysql.cost_record`` fallback is not reachable.

    SDK consumers (Phase 2 onwards) MUST call
    ``set_cost_record_repository(repo)`` during boot before any
    engine module runs.
    """


@runtime_checkable
class CostRecordRepository(Protocol):
    """Pluggable repository for cost-record persistence + aggregation.

    Methods are coarse-grained business operations matched to the 3
    audited engine call sites. ``create`` and ``add_record`` are both
    write APIs with different return contracts — preserving both is
    intentional (see module docstring).

    Implementations MUST be safe to call concurrently — cost tracking
    fires from every LLM call site without serialisation.
    """

    async def create(self, record: "CostRecordRow") -> Optional[str]:
        """Persist a cost record. Returns the inserted ``id`` on
        success, ``None`` on storage failure.

        Fire-and-forget — engine callers wrap in try/except and
        continue on failure (cost records are non-critical for the
        in-flight request; they're aggregated downstream by
        :mod:`runtime.alert.service`).
        """
        ...

    async def add_record(self, record: "CostRecordRow") -> None:
        """Persist a cost record without returning the inserted id.

        Used by the CLI offline-sync path
        (``runtime/storage/mongo_backend.py:298``) where the caller
        already knows the id. Implementations may delegate to
        :meth:`create` internally.
        """
        ...

    async def get_monthly_cost(
        self,
        *,
        workspace_id: str,
        year_month: Optional[str] = None,
    ) -> Decimal:
        """Return the aggregated cost for ``workspace_id`` over the
        UTC calendar month.

        ``year_month`` is ``"YYYY-MM"``; ``None`` resolves to the
        current UTC month. Returns ``Decimal("0")`` (NOT ``None``)
        when there are no matching records — preserves the real DAO
        contract. Uses half-open UTC bounds on ``recorded_at`` so the
        aggregate is independent of the MySQL session timezone (plan
        §Gap 5 — "账单月边界按 UTC 计算").
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_cost_record_repository: Optional[CostRecordRepository] = None


def set_cost_record_repository(repo: CostRecordRepository) -> None:
    """Install the CostRecordRepository used by engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot
    order is auditable. **Never** logs the repo contents — cost
    records contain ``user_id`` / ``request_id`` (PII).

    Raises:
        TypeError: when ``repo`` does not satisfy the
            :class:`CostRecordRepository` Protocol at the structural
            level.
    """
    if not isinstance(repo, CostRecordRepository):
        raise TypeError(
            f"set_cost_record_repository: repo must satisfy "
            f"CostRecordRepository Protocol (create / add_record / "
            f"get_monthly_cost), got {type(repo).__name__}"
        )
    global _cost_record_repository
    _cost_record_repository = repo
    logger.info(
        "CostRecordRepository installed: %s",
        type(repo).__name__,
    )


def get_cost_record_repository() -> CostRecordRepository:
    """Return the installed repository, falling back to a lazy adapter
    that wraps :func:`dao.mysql.cost_record.get_cost_record_dao` when
    no explicit repository is installed.

    The fall-back is PR-E4-only and will be deleted in Phase 2 of the
    SDK extraction plan. SDK consumers MUST install a repository at
    boot.

    Raises:
        CostRecordRepositoryNotInstalledError: when no repository is
            installed AND ``dao.mysql.cost_record`` is not importable.
    """
    if _cost_record_repository is not None:
        return _cost_record_repository

    # PR-E4 fall-back. Probe ``dao.mysql.cost_record`` reachability.
    try:
        import importlib
        importlib.import_module("dao.mysql.cost_record")
    except ImportError as exc:
        raise CostRecordRepositoryNotInstalledError(
            "CostRecordRepository has not been installed and "
            "dao.mysql.cost_record is not importable. Call "
            "set_cost_record_repository(repo) at boot before any "
            "engine code path runs."
        ) from exc

    return _LegacyCostRecordRepository.get_singleton()


def reset_cost_record_repository_for_test() -> None:
    """Test-only helper to clear the installed repository between
    cases.

    NOT for production use. Mirrors
    :func:`runtime.protocols.context_store.reset_context_store_for_test`.
    """
    global _cost_record_repository
    _cost_record_repository = None
    _LegacyCostRecordRepository.reset_singleton_for_test()


# ── Legacy cost_record_dao adapter (fallback) ───────────────────────────


class _LegacyCostRecordRepository:
    """Adapter that exposes
    :func:`dao.mysql.cost_record.get_cost_record_dao` (the pre-built
    singleton in ai-buddy) via the :class:`CostRecordRepository`
    Protocol.

    Used only via the fall-back path in
    :func:`get_cost_record_repository` when no SDK-side repository
    is installed. ai-buddy can choose to install this adapter
    explicitly at boot (cleaner audit trail) or rely on the fall-back
    (zero boot wiring).

    Reads ``get_cost_record_dao()`` lazily inside each method so the
    adapter survives early-boot scenarios where the MySQL pool isn't
    ready yet — same fail-soft pattern as
    :class:`runtime.protocols.context_store._LegacyContextStoreProvider`.
    """

    _SINGLETON: Optional["_LegacyCostRecordRepository"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyCostRecordRepository":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    @staticmethod
    def _dao() -> Any:
        """Read the ai-buddy ``get_cost_record_dao()`` singleton
        lazily.

        Returns ``None`` when ``dao.mysql.cost_record`` isn't
        importable — callers see
        :class:`CostRecordRepositoryNotInstalledError` on first use.
        """
        try:
            from dao.mysql.cost_record import get_cost_record_dao
        except ImportError:
            return None
        return get_cost_record_dao()

    async def create(self, record: "CostRecordRow") -> Optional[str]:
        dao = self._dao()
        if dao is None:
            raise CostRecordRepositoryNotInstalledError(
                "_LegacyCostRecordRepository: "
                "dao.mysql.cost_record not importable; "
                "cannot persist cost record"
            )
        return await dao.create(record)

    async def add_record(self, record: "CostRecordRow") -> None:
        dao = self._dao()
        if dao is None:
            raise CostRecordRepositoryNotInstalledError(
                "_LegacyCostRecordRepository: "
                "dao.mysql.cost_record not importable; "
                "cannot persist cost record"
            )
        # Real DAO singleton exposes ``add_record`` for the offline
        # sync path; preserve that verb. Some installs only have
        # ``create``, so we fall back transparently.
        add_record = getattr(dao, "add_record", None)
        if add_record is not None:
            await add_record(record)
            return
        await dao.create(record)

    async def get_monthly_cost(
        self,
        *,
        workspace_id: str,
        year_month: Optional[str] = None,
    ) -> Decimal:
        dao = self._dao()
        if dao is None:
            raise CostRecordRepositoryNotInstalledError(
                "_LegacyCostRecordRepository: "
                "dao.mysql.cost_record not importable; "
                "cannot aggregate monthly cost"
            )
        # The real DAO's ``get_monthly_cost`` signature is
        # ``(workspace_id: Optional[str] = None)`` — it ignores
        # ``year_month`` (defaults to current UTC month internally).
        # When ``year_month`` is supplied we route through
        # ``get_monthly_cost_by_avatar`` / similar fallbacks if the
        # caller's intent was a specific month; the engine call site
        # currently passes only ``workspace_id`` so the bare path is
        # sufficient.
        if year_month is None:
            result = await dao.get_monthly_cost(workspace_id=workspace_id)
        else:
            # Defer to richer aggregate when the DAO exposes one.
            # Real DAO method signature varies by version; fall back
            # to the workspace-only call if a year_month-aware variant
            # is unavailable.
            method = getattr(dao, "get_monthly_cost_by_month", None)
            if method is not None:
                result = await method(
                    workspace_id=workspace_id, year_month=year_month
                )
            else:
                # WARN: silent fallback to current-month aggregate.
                # The legacy DAO does not expose a year-month-aware
                # variant, so requesting a historical month silently
                # returns the current MTD figure.  Log so operators
                # can detect when the audit / billing UI requests
                # historical data and the result is silently wrong.
                logger.warning(
                    "_LegacyCostRecordRepository.get_monthly_cost: "
                    "year_month=%r requested but DAO lacks "
                    "get_monthly_cost_by_month; falling back to "
                    "current-month aggregate (callers receiving "
                    "this WARN should treat the returned value as "
                    "MTD-of-now, not the requested month)",
                    year_month,
                )
                result = await dao.get_monthly_cost(workspace_id=workspace_id)
        if result is None:
            return Decimal("0")
        if isinstance(result, Decimal):
            return result
        return Decimal(str(result))


# ── In-memory CostRecordRepository for tests + SDK default ──────────────


import re as _re  # noqa: E402 — imported here to keep top-of-module imports lean
from datetime import datetime, timezone  # noqa: E402

_YEAR_MONTH_RE = _re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _utc_month_bounds(year_month: Optional[str]) -> tuple[datetime, datetime]:
    """Half-open UTC bounds for a calendar month — mirrors
    :func:`dao.mysql.cost_record._utc_month_range` so the in-memory
    aggregate matches production behaviour."""
    if year_month is None:
        now = datetime.now(timezone.utc)
        year, month = now.year, now.month
    else:
        m = _YEAR_MONTH_RE.match(year_month)
        if not m:
            raise ValueError(
                f"Invalid year_month: {year_month!r} (expected 'YYYY-MM')"
            )
        year = int(m.group(1))
        month = int(m.group(2))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _coerce_recorded_at(val: Any) -> Optional[datetime]:
    """Coerce a record's ``recorded_at`` to a UTC ``datetime`` for
    aggregation. Returns ``None`` when the value is unparseable —
    such records are excluded from the aggregate (matches real DAO
    behaviour where rows with NULL ``recorded_at`` default to NOW()
    at insert time)."""
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        # Accept ISO-format and rough YYYY-MM-DD HH:MM:SS shape.
        try:
            parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


class InMemoryCostRecordRepository:
    """CostRecordRepository impl for tests and SDK self-bundled default.

    Backed by a dict ``_records: Dict[str, CostRecordRow]`` keyed by
    record id. :meth:`create` and :meth:`add_record` both insert (with
    auto-generated UUID when ``record.id`` is empty).
    :meth:`get_monthly_cost` does a linear scan filtered by
    ``workspace_id`` + UTC half-open bounds — fine for tests where N
    is small.

    Returns ``Decimal('0')`` on empty match — preserves the real DAO
    contract.
    """

    def __init__(self) -> None:
        self._records: Dict[str, CostRecordRow] = {}

    async def create(self, record: "CostRecordRow") -> Optional[str]:
        rec_id = getattr(record, "id", "") or str(uuid.uuid4())
        # Update the id on the row when generated so the caller sees
        # the persisted id (real DAO does the same).
        try:
            record.id = rec_id
        except (AttributeError, TypeError):
            # frozen dataclass or similar — fall back to a copy
            pass
        self._records[rec_id] = record
        return rec_id

    async def add_record(self, record: "CostRecordRow") -> None:
        await self.create(record)

    async def get_monthly_cost(
        self,
        *,
        workspace_id: str,
        year_month: Optional[str] = None,
    ) -> Decimal:
        start, end = _utc_month_bounds(year_month)
        total = Decimal("0")
        for rec in self._records.values():
            if getattr(rec, "workspace_id", None) != workspace_id:
                continue
            recorded = _coerce_recorded_at(getattr(rec, "recorded_at", None))
            if recorded is None:
                # Match real DAO default — records without explicit
                # ``recorded_at`` count toward the current month.
                if year_month is None:
                    pass  # accept into current-month aggregate
                else:
                    continue
            elif not (start <= recorded < end):
                continue
            amount = getattr(rec, "cost_amount", Decimal("0"))
            if isinstance(amount, Decimal):
                total += amount
            else:
                try:
                    total += Decimal(str(amount))
                except Exception:
                    continue
        return total

    # ── Test helpers (not part of the Protocol) ──────────────────

    def list_records(self) -> List["CostRecordRow"]:
        return list(self._records.values())

    def clear(self) -> None:
        self._records.clear()


__all__ = [
    "CostRecordRow",
    "CostRecordRepository",
    "CostRecordRepositoryNotInstalledError",
    "InMemoryCostRecordRepository",
    "set_cost_record_repository",
    "get_cost_record_repository",
    "reset_cost_record_repository_for_test",
]
# ``_LegacyCostRecordRepository`` is intentionally NOT exported — same
# convention as ``_LegacyContextStoreProvider`` (PR-E3) and
# ``_LegacyComponentBackendProvider`` (PR-E5). Tests import it
# directly by name, which is fine for private symbols.
