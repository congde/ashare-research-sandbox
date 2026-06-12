# -*- coding: utf-8 -*-
"""
ContextStore — PR-E3 of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E3.

Goal
----
Replace the engine layer's direct dependency on
``dao.mongo.dbs.ai_assistant_db`` (the ai-buddy-specific Mongo
``BaseDAO`` singleton) with a Protocol-based seam. SDK consumers
install their own ContextStore at boot; ai-buddy installs an adapter
that wraps ``ai_assistant_db`` so the existing engine code path is
byte-identical.

Today every engine call site that needs a Mongo collection does::

    from vendor_runtime_sdk.agent.schema import ai_assistant_db
    _coll = await ai_assistant_db.kia_sessions.collection       # direct attr
    await _coll.find_one(...)
    # OR
    collection = getattr(ai_assistant_db, _USER_PREF_COLLECTION, None)  # dynamic name
    # OR
    await ai_assistant_db.kia_qa.add_or_update_one(...)         # high-level DaoHelper

That import path is unreachable when the engine is packaged as the
SDK :mod:`kucoin-agent-runtime-sdk` (``dao/`` is the business layer,
kept outside the SDK). PR-E3 introduces the abstraction.

Scope (V1)
----------
This PR handles the 5 tier-1 call-site anchors:

* ``src/runtime/checkpoint/dag_state.py``
* ``src/runtime/policy/decision_memory.py``
* ``src/runtime/storage/mongo_backend.py``
* ``src/runtime/conversation/_stream.py``
* ``src/agent/schema.py``  (the seam through which 17/28 imports flow)

Fall-back path (PR-E3 only; deleted in Phase 2)
-----------------------------------------------
When no provider is installed via :func:`set_context_store`,
:func:`get_context_store` lazily synthesises one that wraps
``dao.mongo.dbs.ai_assistant_db``. This makes PR-E3 a zero-behaviour-
change refactor for ai-buddy's current boot path. SDK consumers
(Phase 2) must call ``set_context_store(...)`` at boot before any
engine path runs.

Per-collection access pattern
-----------------------------
The Protocol exposes BOTH a canonical ``get_collection(name: str)``
method AND attribute-style access via ``__getattr__``. Rationale:

* 24/28 audited call sites use direct attribute access
  (``ai_assistant_db.kia_sessions``).
* 2/28 use dynamic-name access (``getattr(ai_assistant_db, name)``).
* New code should prefer ``get_collection(name)`` for IDE-completion
  and type-checker friendliness; ``__getattr__`` is back-compat
  sugar that delegates to ``get_collection``.

Same pattern as PR-E1 :class:`EngineConfig` and PR-E5
:class:`BackendClientProvider` — engine carries its own contract;
business layer keeps its own concrete types; the SDK seam lives at
the import boundary.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

logger = logging.getLogger(__name__)


class ContextStoreNotInstalledError(RuntimeError):
    """Raised when :func:`get_context_store` is called before any
    provider is installed AND the legacy ``dao.mongo.dbs`` fallback is
    not reachable.

    SDK consumers (Phase 2 onwards) MUST call
    ``set_context_store(...)`` during boot before any engine module
    runs.
    """


@runtime_checkable
class ContextStore(Protocol):
    """Pluggable accessor for the ai-buddy Mongo collection family.

    Concrete impls expose collections through :meth:`get_collection`;
    callers may also use direct attribute access
    (``store.kia_sessions``) which implementations delegate via
    ``__getattr__``.

    Returns ``Any`` (not a typed ``Collection`` Protocol) to preserve
    the DaoHelper duck-type: high-level coroutine methods
    (``add_or_update_one`` / ``query`` / ``get`` / ``insert_many`` /
    ``count`` / ``delete`` / ``find_and_update`` / ``aggregate``)
    PLUS the async ``.collection`` property that yields the raw motor
    collection. A typed Collection Protocol can be added in PR-E4
    once the surface stabilises; for now ``Any`` keeps the migration
    zero-friction.
    """

    def get_collection(self, name: str) -> Any:
        """Return the named collection.

        The canonical Protocol method — implementations resolve
        ``name`` to a DaoHelper-shaped object exposing the legacy
        coroutine surface plus the async ``.collection`` property.
        """
        ...

    def __getattr__(self, name: str) -> Any:
        """Attribute-style access — delegates to :meth:`get_collection`.

        Required for back-compat with 24/28 existing call sites that
        hard-code ``ai_assistant_db.kia_sessions`` etc. Implementations
        MUST guard ``name.startswith("_")`` to avoid infinite-creation
        triggered by pickle / copy / debugger introspection.
        """
        ...

    def __contains__(self, name: str) -> bool:
        """Return ``True`` if the named collection has already been
        materialised by a prior :meth:`get_collection` /
        ``__getattr__`` call.

        Implements the ``in`` operator so callers can replace the
        ``ai_assistant_db.__dict__.get(name)`` anti-pattern documented
        in :mod:`runtime.policy.decision_memory`.
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_context_store: Optional[ContextStore] = None


def set_context_store(store: ContextStore) -> None:
    """Install the ContextStore used by all engine modules.

    Store is NOT validated at install time beyond a structural Protocol
    check — the Protocol's methods are called lazily at use time, so a
    non-conforming implementation surfaces at first use, not at boot.
    Mirrors :func:`runtime.protocols.backend_provider.set_backend_provider`
    semantics.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot
    order is auditable. **Never** logs the store itself or any
    collection contents (Mongo collections can hold PII / secret-
    bearing payloads).

    Raises:
        TypeError: when ``store`` does not satisfy the
            :class:`ContextStore` Protocol at the structural level
            (missing ``get_collection`` / ``__getattr__`` / ``__contains__``).
    """
    if not isinstance(store, ContextStore):
        raise TypeError(
            f"set_context_store: store must satisfy ContextStore "
            f"Protocol (get_collection / __getattr__ / __contains__), "
            f"got {type(store).__name__}"
        )
    global _context_store
    _context_store = store
    logger.info(
        "ContextStore installed: %s",
        type(store).__name__,
    )


def get_context_store() -> ContextStore:
    """Return the installed ContextStore, falling back to a lazy
    adapter that wraps :data:`dao.mongo.dbs.ai_assistant_db` when no
    explicit provider is installed.

    The fall-back is PR-E3-only and will be deleted in Phase 2 of the
    SDK extraction plan. SDK consumers MUST install a provider at
    boot.

    Raises:
        ContextStoreNotInstalledError: when no provider is installed
            AND ``dao.mongo.dbs`` is not importable.
    """
    if _context_store is not None:
        return _context_store

    # PR-E3 fall-back. Probe ``dao.mongo.dbs`` module reachability —
    # only the module needs to exist; the legacy adapter handles the
    # case where the ``ai_assistant_db`` singleton is missing.
    try:
        import importlib
        importlib.import_module("dao.mongo.dbs")
    except ImportError as exc:
        raise ContextStoreNotInstalledError(
            "ContextStore has not been installed and dao.mongo.dbs "
            "is not importable. Call set_context_store(store) at "
            "boot before any engine code path runs."
        ) from exc

    # Lazy-construct on first miss; cache so subsequent calls skip
    # the importlib probe.
    return _LegacyContextStoreProvider.get_singleton()


def reset_context_store_for_test() -> None:
    """Test-only helper to clear the installed provider between cases.

    NOT for production use. Mirrors
    :func:`runtime.protocols.backend_provider.reset_backend_provider_for_test`.
    """
    global _context_store
    _context_store = None
    _LegacyContextStoreProvider.reset_singleton_for_test()


# ── Legacy ai_assistant_db adapter (fallback) ───────────────────────────


class _LegacyContextStoreProvider:
    """Adapter that exposes :data:`dao.mongo.dbs.ai_assistant_db` (the
    pre-built ``BaseDAO`` singleton in ai-buddy) via the
    :class:`ContextStore` Protocol.

    Used only via the fall-back path in :func:`get_context_store`
    when no SDK-side provider is installed. ai-buddy can choose to
    install this adapter explicitly at boot (cleaner audit trail) or
    rely on the fall-back (zero boot wiring).

    Reads ``dao.mongo.dbs.ai_assistant_db`` lazily inside each method
    so the adapter survives early-boot scenarios where the singleton's
    motor client isn't ready yet — same fail-soft pattern as
    :class:`runtime.protocols.backend_provider._LegacyComponentBackendProvider`.
    """

    _SINGLETON: Optional["_LegacyContextStoreProvider"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyContextStoreProvider":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    @staticmethod
    def _db() -> Any:
        """Read the ai-buddy ``ai_assistant_db`` singleton lazily.

        We re-read on every call instead of caching so a late init
        still resolves. Returns ``None`` when ``dao.mongo.dbs`` isn't
        importable — callers see :class:`ContextStoreNotInstalledError`
        on first :meth:`get_collection` use.
        """
        try:
            from dao.mongo.dbs import ai_assistant_db
        except ImportError:
            return None
        return ai_assistant_db

    def get_collection(self, name: str) -> Any:
        db = self._db()
        if db is None:
            raise ContextStoreNotInstalledError(
                f"_LegacyContextStoreProvider: dao.mongo.dbs not "
                f"importable; requested collection {name!r}"
            )
        return getattr(db, name)

    def __getattr__(self, name: str) -> Any:
        # Guard internal / dunder lookups so pickle / copy / debugger
        # introspection doesn't trigger infinite collection creation.
        if name.startswith("_"):
            raise AttributeError(name)
        return self.get_collection(name)

    def __contains__(self, name: str) -> bool:
        db = self._db()
        if db is None:
            return False
        # ``BaseDAO`` caches DaoHelper instances on ``_db_map``;
        # collections that have never been touched are absent — this
        # mirrors the lazy-collection semantics of the underlying
        # BaseDAO and matches how callers used to do
        # ``ai_assistant_db.__dict__.get(name)``.
        return name in getattr(db, "_db_map", {})


# ── In-memory ContextStore for tests + SDK default ──────────────────────


class _InMemoryCursor:
    """Async iterable that yields buffered docs.

    Mirrors the motor cursor protocol used in audited call sites:
    ``[doc async for doc in coll.find(query)]``. Sort / skip / limit
    helpers chain via ``return self`` so callers may write
    ``coll.find(q).sort(...).skip(...).limit(...)``.
    """

    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs: List[Dict[str, Any]] = list(docs)

    def sort(self, *args: Any, **kwargs: Any) -> "_InMemoryCursor":
        # Two call shapes seen in the audit:
        #   .sort([("createTime", -1)])
        #   .sort("createTime", -1)
        spec: List[Tuple[str, int]] = []
        if args:
            first = args[0]
            if isinstance(first, list):
                spec = list(first)
            elif isinstance(first, str) and len(args) >= 2:
                spec = [(first, int(args[1]))]
        for key, direction in reversed(spec):
            self._docs.sort(
                key=lambda d, _k=key: d.get(_k),
                reverse=(direction == -1),
            )
        return self

    def skip(self, n: int) -> "_InMemoryCursor":
        self._docs = self._docs[max(0, int(n)) :]
        return self

    def limit(self, n: int) -> "_InMemoryCursor":
        n_int = int(n)
        if n_int > 0:
            self._docs = self._docs[:n_int]
        return self

    def __aiter__(self) -> "_InMemoryCursor":
        self._iter = iter(self._docs)
        return self

    async def __anext__(self) -> Dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration

    async def to_list(self, length: Optional[int] = None) -> List[Dict[str, Any]]:
        if length is None:
            return list(self._docs)
        return list(self._docs[: int(length)])


def _matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    """Subset matcher: top-level field equality plus ``$in``.

    Deliberately narrow — anything tighter (``$gt`` / ``$exists`` /
    ``$or`` / nested-path) raises :class:`NotImplementedError` so
    tests using unsupported operators fail loudly rather than silently
    returning the wrong result set.
    """
    for key, expected in query.items():
        if isinstance(expected, dict):
            # Only ``$in`` is supported in V1.
            if "$in" in expected and len(expected) == 1:
                if doc.get(key) not in expected["$in"]:
                    return False
                continue
            raise NotImplementedError(
                f"InMemoryCollection: query operator {expected!r} on "
                f"field {key!r} not supported in PR-E3 V1 — tests "
                f"using richer matchers should construct a tighter "
                f"fixture or extend _matches()."
            )
        if doc.get(key) != expected:
            return False
    return True


class _InMemoryMotorCollection:
    """Raw-motor-style facade for :class:`InMemoryCollection`.

    Exposes the small subset of motor's surface that audited engine
    code touches: ``find`` / ``find_one`` / ``update_one`` /
    ``find_one_and_update`` / ``insert_many`` / ``count_documents``.
    """

    def __init__(self, owner: "InMemoryCollection") -> None:
        self._owner = owner

    def find(
        self,
        query: Optional[Dict[str, Any]] = None,
        *args: Any,
        **kwargs: Any,
    ) -> _InMemoryCursor:
        q = query or {}
        docs = [d for d in self._owner._docs if _matches(d, q)]
        return _InMemoryCursor(docs)

    async def find_one(
        self,
        query: Optional[Dict[str, Any]] = None,
        projection: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        q = query or {}
        for doc in self._owner._docs:
            if _matches(doc, q):
                return dict(doc)
        return None

    async def update_one(
        self,
        query: Dict[str, Any],
        update: Any,
        upsert: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Apply a Mongo-shaped ``update`` to the first matching doc.

        Supports the operator subset exercised by engine code:

        * ``$set`` / ``$unset`` — field-level modifications
        * ``$pull`` — array filtering by sub-query (the once-token
          mechanism in :mod:`runtime.policy.decision_memory` relies on
          this; a silent no-op would make tests pass but production
          break)
        * ``$push`` — append to array
        * ``$addToSet`` — append-if-absent to array (treats list as set)

        Aggregation-pipeline updates (``update`` as a ``list`` of
        stages) are NOT supported in V1 and raise
        :class:`NotImplementedError` so the test fail-loud rather than
        silently succeed. Engine call sites using pipeline shape must
        either avoid the in-memory store for that scenario or extend
        this method.
        """
        if isinstance(update, list):
            raise NotImplementedError(
                "_InMemoryMotorCollection.update_one: aggregation "
                "pipeline updates (list-of-stages) are not supported "
                "in V1. Tests using pipeline updates must extend this "
                "method or use AsyncMock for that path."
            )

        target_index: Optional[int] = None
        for idx, doc in enumerate(self._owner._docs):
            if _matches(doc, query):
                target_index = idx
                break

        modified_count = 0
        if target_index is not None:
            doc = self._owner._docs[target_index]
            if "$set" in update:
                doc.update(update["$set"])
                modified_count = 1
            if "$unset" in update:
                for k in update["$unset"]:
                    doc.pop(k, None)
                modified_count = 1
            if "$pull" in update:
                for field, condition in update["$pull"].items():
                    existing = doc.get(field)
                    if not isinstance(existing, list):
                        continue
                    if isinstance(condition, dict):
                        # ``$pull: {field: {<sub-query>}}`` — remove
                        # elements that match the sub-query.  ``$or``
                        # branch supported (the only operator decision_
                        # memory uses; extend here if other operators
                        # appear in audit).
                        if "$or" in condition:
                            branches = condition["$or"]
                            doc[field] = [
                                e for e in existing
                                if not any(_matches(e, b) for b in branches)
                            ]
                        else:
                            doc[field] = [
                                e for e in existing
                                if not _matches(e, condition)
                            ]
                    else:
                        # ``$pull: {field: literal_value}`` — remove
                        # elements equal to the literal.
                        doc[field] = [e for e in existing if e != condition]
                modified_count = 1
            if "$push" in update:
                for field, value in update["$push"].items():
                    existing = doc.get(field)
                    if not isinstance(existing, list):
                        existing = []
                    if isinstance(value, dict) and "$each" in value:
                        # ``$push: {field: {$each: [...]}}`` Mongo idiom
                        existing.extend(value["$each"])
                        if "$slice" in value:
                            n = value["$slice"]
                            existing = existing[n:] if n < 0 else existing[:n]
                    else:
                        existing.append(value)
                    doc[field] = existing
                modified_count = 1
            if "$addToSet" in update:
                for field, value in update["$addToSet"].items():
                    existing = doc.get(field, [])
                    if not isinstance(existing, list):
                        existing = []
                    if value not in existing:
                        existing.append(value)
                    doc[field] = existing
                modified_count = 1
        elif upsert:
            new_doc = dict(query)
            if "$set" in update:
                new_doc.update(update["$set"])
            if "$push" in update:
                for field, value in update["$push"].items():
                    if isinstance(value, dict) and "$each" in value:
                        new_doc[field] = list(value["$each"])
                    else:
                        new_doc[field] = [value]
            if "$addToSet" in update:
                for field, value in update["$addToSet"].items():
                    new_doc[field] = [value]
            self._owner._docs.append(new_doc)
            modified_count = 1

        class _Result:
            def __init__(self, mc: int) -> None:
                self.modified_count = mc
                self.matched_count = mc
                self.upserted_id = None
                # ``DaoHelper.add_or_update_one`` reads ``raw_result['ok']``
                self.raw_result = {"ok": 1, "n": mc}

        return _Result(modified_count)

    async def find_one_and_update(
        self,
        query: Dict[str, Any],
        update: Dict[str, Any],
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """Match real Motor's ``find_one_and_update`` contract:

        * default returns the PRE-update doc (matching Motor's
          ``return_document=ReturnDocument.BEFORE`` default)
        * pass ``return_document="after"`` to get POST-update doc
        * supports ``$set`` / ``$unset`` (extend if engine code uses
          others)
        """
        for doc in self._owner._docs:
            if _matches(doc, query):
                before = dict(doc)  # snapshot pre-update for default return
                if "$set" in update:
                    doc.update(update["$set"])
                if "$unset" in update:
                    for k in update["$unset"]:
                        doc.pop(k, None)
                return_after = kwargs.get("return_document") == "after"
                return dict(doc) if return_after else before
        return None

    async def insert_many(
        self, docs: List[Dict[str, Any]], **kwargs: Any
    ) -> Any:
        ids = []
        for doc in docs:
            self._owner._docs.append(dict(doc))
            ids.append(doc.get("id"))

        class _Result:
            def __init__(self, ids: List[Any]) -> None:
                self.inserted_ids = ids

        return _Result(ids)

    async def count_documents(self, query: Optional[Dict[str, Any]] = None) -> int:
        q = query or {}
        return sum(1 for d in self._owner._docs if _matches(d, q))

    async def delete_one(self, query: Dict[str, Any]) -> Any:
        for idx, doc in enumerate(self._owner._docs):
            if _matches(doc, query):
                del self._owner._docs[idx]

                class _Result:
                    raw_result = {"ok": 1, "n": 1}

                return _Result()

        class _Result:
            raw_result = {"ok": 1, "n": 0}

        return _Result()


class _AwaitableCollection:
    """Make :class:`InMemoryCollection`'s ``.collection`` attribute
    awaitable (mirrors :class:`libs.wrapper.async_property`).

    Audited call sites do ``await coll.collection`` exactly once
    (single await — unlike the legacy double-await documented in
    :mod:`runtime.policy.decision_memory`, the in-memory test impl
    yields the motor-style facade synchronously on a single await).
    """

    def __init__(self, motor_collection: _InMemoryMotorCollection) -> None:
        self._motor_collection = motor_collection

    def __await__(self):
        async def _resolve() -> _InMemoryMotorCollection:
            return self._motor_collection

        return _resolve().__await__()


class InMemoryCollection:
    """Test + SDK-default backing for a single named collection.

    Implements the :class:`dao.mongo.orm.DaoHelper`-compatible subset
    exercised by tier-1 files: ``add_or_update_one`` /
    ``add_or_update_one_by_id`` / ``get`` / ``query`` /
    ``insert_many`` / ``find_and_update`` / ``count`` / ``delete``,
    plus an awaitable ``.collection`` attribute returning
    :class:`_InMemoryMotorCollection`.

    All operations dict-backed (list of docs per collection, linear
    scan on every query — fine for tests since N is small). ``_id``
    is never auto-generated; tests must supply explicit ``id``
    fields when calling :meth:`add_or_update_one_by_id`, matching the
    real :class:`DaoHelper` contract.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._docs: List[Dict[str, Any]] = []
        # Pre-bind a single motor facade so callers comparing identity
        # across awaits get a consistent object.
        self._motor = _InMemoryMotorCollection(self)

    # ── High-level DaoHelper surface ──────────────────────────────

    async def add_or_update_one(
        self,
        matcher: Dict[str, Any],
        data: Dict[str, Any],
        output_names: Optional[List[str]] = None,
        hidden_names: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        await self._motor.update_one(matcher, {"$set": data}, upsert=True)
        existing = await self._motor.find_one(matcher)
        return existing or dict(data)

    async def add_or_update_one_by_id(
        self,
        data: Dict[str, Any],
        output_names: Optional[List[str]] = None,
        hidden_names: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        # Mirror DaoHelper.add_or_update_one_by_id at orm.py:55 —
        # KeyError when ``id`` is missing.
        sample_id = data["id"]
        await self._motor.update_one(
            {"id": sample_id}, {"$set": data}, upsert=True
        )
        existing = await self._motor.find_one({"id": sample_id})
        return existing or dict(data)

    async def get(
        self,
        id: Optional[str] = None,
        matcher: Optional[Dict[str, Any]] = None,
        output_names: Optional[List[str]] = None,
        hidden_names: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        m = dict(matcher or {})
        if id is not None:
            m["id"] = id
        return await self._motor.find_one(m)

    async def query(
        self,
        matcher: Optional[Dict[str, Any]] = None,
        output_names: Optional[List[str]] = None,
        hidden_names: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 0,
        sort: Optional[List[Tuple[str, int]]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        q = dict(matcher or {})
        cursor = self._motor.find(q)
        if sort:
            cursor = cursor.sort(sort)
        if page_size and page_size > 0:
            cursor = cursor.skip(max(0, (page - 1) * page_size)).limit(page_size)
        return await cursor.to_list()

    async def insert_many(
        self, data: List[Dict[str, Any]], **kwargs: Any
    ) -> Any:
        return await self._motor.insert_many(data)

    async def find_and_update(
        self,
        matcher: Dict[str, Any],
        update: Dict[str, Any],
        output_names: Optional[List[str]] = None,
        hidden_names: Optional[List[str]] = None,
        resp_doc: bool = True,
        **kwargs: Any,
    ) -> Optional[List[Dict[str, Any]]]:
        modified = 0
        for doc in self._docs:
            if _matches(doc, matcher):
                doc.update(update)
                modified += 1
        if resp_doc and modified:
            return [
                dict(d) for d in self._docs if _matches(d, matcher)
            ]
        return None

    async def count(self, matcher: Optional[Dict[str, Any]] = None) -> int:
        return await self._motor.count_documents(matcher or {})

    async def delete(
        self,
        id: Optional[str] = None,
        matcher: Optional[Dict[str, Any]] = None,
    ) -> Any:
        m = dict(matcher or {})
        if id is not None:
            m["id"] = id
        if not m:
            return None
        return await self._motor.delete_one(m)

    # ── Raw motor-style facade ────────────────────────────────────

    @property
    def collection(self) -> _AwaitableCollection:
        """Awaitable property — ``await coll.collection`` yields the
        :class:`_InMemoryMotorCollection`. Single-await semantics; the
        production :class:`DaoHelper` uses double-await (async_property
        returning Task) — the in-memory test impl simplifies because
        tests don't need to exercise the Task-wrapper bug.
        """
        return _AwaitableCollection(self._motor)

    # ── Motor-shaped direct proxies ────────────────────────────────
    # Some migrated engine code calls these methods directly on the
    # collection object returned by ``store.get_collection(name)`` (e.g.
    # decision_memory.py:332,581).  Real DaoHelper delegates these to
    # the underlying motor collection via ``__getattr__``; we mirror
    # the dispatch explicitly so the InMemoryCollection is a drop-in
    # replacement without an unexpected AttributeError being swallowed
    # by an upstream ``except Exception``.

    def find(self, *args: Any, **kwargs: Any) -> _InMemoryCursor:
        """Proxy to :meth:`_InMemoryMotorCollection.find`."""
        return self._motor.find(*args, **kwargs)

    async def find_one(self, *args: Any, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Proxy to :meth:`_InMemoryMotorCollection.find_one`."""
        return await self._motor.find_one(*args, **kwargs)

    async def update_one(self, *args: Any, **kwargs: Any) -> Any:
        """Proxy to :meth:`_InMemoryMotorCollection.update_one`."""
        return await self._motor.update_one(*args, **kwargs)

    async def find_one_and_update(self, *args: Any, **kwargs: Any) -> Any:
        """Proxy to :meth:`_InMemoryMotorCollection.find_one_and_update`."""
        return await self._motor.find_one_and_update(*args, **kwargs)

    async def count_documents(self, *args: Any, **kwargs: Any) -> int:
        """Proxy to :meth:`_InMemoryMotorCollection.count_documents`."""
        return await self._motor.count_documents(*args, **kwargs)

    async def delete_one(self, *args: Any, **kwargs: Any) -> Any:
        """Proxy to :meth:`_InMemoryMotorCollection.delete_one`."""
        return await self._motor.delete_one(*args, **kwargs)


class InMemoryContextStore:
    """ContextStore impl for tests and SDK self-bundled default.

    Backed by a per-collection dict of :class:`InMemoryCollection`
    instances. Same collection name resolves to the same instance
    across calls — preserves the identity-of-collection invariant
    that real :class:`BaseDAO` provides via its ``_db_map`` cache.
    """

    def __init__(self) -> None:
        self._collections: Dict[str, InMemoryCollection] = {}

    def get_collection(self, name: str) -> InMemoryCollection:
        if name not in self._collections:
            self._collections[name] = InMemoryCollection(name)
        return self._collections[name]

    def __getattr__(self, name: str) -> InMemoryCollection:
        # Guard internal / dunder lookups — without this guard, pickle
        # / copy / debugger introspection would create bogus
        # collections named ``__getstate__`` / ``_pytest_*`` / etc.
        if name.startswith("_"):
            raise AttributeError(name)
        return self.get_collection(name)

    def __contains__(self, name: str) -> bool:
        return name in self._collections


__all__ = [
    "ContextStore",
    "ContextStoreNotInstalledError",
    "InMemoryCollection",
    "InMemoryContextStore",
    "set_context_store",
    "get_context_store",
    "reset_context_store_for_test",
]
# ``_LegacyContextStoreProvider`` is intentionally NOT exported — it is
# the PR-E3-only fallback adapter and matches the PR-E5 convention
# (``_LegacyComponentBackendProvider`` is also private).  Tests import
# it directly by name, which is fine for private symbols.
