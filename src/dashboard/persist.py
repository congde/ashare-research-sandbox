from __future__ import annotations

from typing import Any

from dashboard.catalog import is_complete
from dashboard.snapshot import resolve_cache_key, save_snapshot

PERSISTABLE_SOURCES = frozenset({"live", "web3-trading-upstream"})


def is_persistable_source(payload: dict[str, Any]) -> bool:
    if payload.get("live_error"):
        return False
    source = str(payload.get("source") or "")
    return source in PERSISTABLE_SOURCES


def maybe_persist(name: str, payload: dict[str, Any], **parts: str | int) -> None:
    if not is_persistable_source(payload):
        return
    if not is_complete(name, payload):
        return
    cache_key = resolve_cache_key(name, **parts)
    origin = str(payload.get("source") or "live")
    save_snapshot(cache_key, payload, origin=origin)


def annotate_cached(payload: dict[str, Any]) -> dict[str, Any]:
    tagged = dict(payload)
    tagged["live_error"] = True
    meta = tagged.get("snapshot") if isinstance(tagged.get("snapshot"), dict) else {}
    if meta.get("saved_at"):
        tagged["cached_at"] = meta["saved_at"]
    tagged["source"] = "snapshot"
    return tagged
