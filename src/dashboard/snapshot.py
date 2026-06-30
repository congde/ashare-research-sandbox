from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import DATA_DIR

SNAPSHOT_DIR = DATA_DIR / "dashboard" / "snapshots"
HISTORY_DIR = SNAPSHOT_DIR / "history"
FIXTURE_DIR = DATA_DIR / "dashboard"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _history_id_from_iso(saved_at: str) -> str:
    return saved_at.replace(":", "-").replace("+00:00", "Z")


def snapshot_path(name: str) -> Path:
    return SNAPSHOT_DIR / f"{name}.json"


def fixture_path(name: str) -> Path:
    return FIXTURE_DIR / f"{name}.json"


def history_dir(name: str) -> Path:
    return HISTORY_DIR / name


def variant_snapshot_name(base: str, **parts: str | int) -> str:
    if not parts:
        return base
    suffix = "__".join(f"{key}={parts[key]}" for key in sorted(parts))
    return f"{base}__{suffix}"


def resolve_cache_key(name: str, **parts: str | int) -> str:
    """Map request parameters to a snapshot key; omit defaults for canonical dataset names."""
    normalized = dict(parts)
    if name == "sector_fund" and normalized.get("trade_type") == 1:
        normalized.pop("trade_type", None)
    if name == "token_fund" and str(normalized.get("symbol", "")).upper() == "BTC":
        normalized.pop("symbol", None)
    if name == "dex_trending" and str(normalized.get("chain", "")).lower() == "solana":
        normalized.pop("chain", None)
    if name == "onchain" and str(normalized.get("symbol", "")).upper() == "BTC":
        normalized.pop("symbol", None)
    if not normalized:
        return name
    return variant_snapshot_name(name, **normalized)


def _read_payload(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    payload.setdefault("ok", True)
    payload.setdefault("source", "snapshot")
    return payload


def save_snapshot(name: str, payload: dict[str, Any], *, origin: str) -> Path:
    from dashboard.catalog import completeness_detail, record_dataset

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    saved_at = _now_iso()
    base_history_id = _history_id_from_iso(saved_at)
    history_dir(name).mkdir(parents=True, exist_ok=True)
    history_id = base_history_id
    history_path = history_dir(name) / f"{history_id}.json"
    suffix = 1
    while history_path.exists():
        history_id = f"{base_history_id}-{suffix}"
        history_path = history_dir(name) / f"{history_id}.json"
        suffix += 1

    body = dict(payload)
    body["ok"] = body.get("ok", True)
    body["source"] = "snapshot"
    body["snapshot"] = {
        "name": name,
        "saved_at": saved_at,
        "origin": origin,
        "history_id": history_id,
        "history_path": str(history_path),
    }
    encoded = json.dumps(body, ensure_ascii=False, indent=2)

    history_path.write_text(encoded, encoding="utf-8")

    latest_path = snapshot_path(name)
    latest_path.write_text(encoded, encoding="utf-8")

    detail = completeness_detail(_canonical_dataset_name(name), body)
    record_dataset(
        _canonical_dataset_name(name),
        layer="snapshot",
        origin=origin,
        path=str(history_path),
        complete=detail["complete"],
        reason=str(detail.get("reason") or ""),
        cache_key=name,
        latest_path=str(latest_path),
        history_id=history_id,
    )
    return history_path


def _canonical_dataset_name(cache_key: str) -> str:
    if "__" in cache_key:
        return cache_key.split("__", 1)[0]
    return cache_key


def load_snapshot(name: str) -> dict[str, Any] | None:
    payload = _read_payload(snapshot_path(name))
    if payload is not None:
        return payload
    hist = history_dir(name)
    if not hist.is_dir():
        return None
    history_files = sorted(hist.glob("*.json"), reverse=True)
    if not history_files:
        return None
    for path in history_files:
        payload = _read_payload(path)
        if payload is not None:
            return payload
    return None


def list_snapshot_history(name: str, *, limit: int = 50) -> list[dict[str, Any]]:
    hist = history_dir(name)
    if not hist.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(hist.glob("*.json"), reverse=True):
        if len(items) >= limit:
            break
        payload = _read_payload(path)
        if payload is None:
            continue
        meta = (payload or {}).get("snapshot") if isinstance(payload, dict) else {}
        items.append(
            {
                "name": name,
                "path": str(path),
                "history_id": path.stem,
                "saved_at": (meta or {}).get("saved_at"),
                "origin": (meta or {}).get("origin"),
                "ok": bool((payload or {}).get("ok", True)),
            }
        )
    return items


def load_fixture(name: str) -> dict[str, Any]:
    path = fixture_path(name)
    if not path.is_file():
        return {"ok": False, "message": f"missing fixture: {name}", "source": "fixture"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("source", "fixture")
    payload.setdefault("ok", True)
    return payload


def load_offline(name: str, **parts: str | int) -> dict[str, Any]:
    """Prefer latest persisted snapshot (variant-aware), then complete fixture."""
    from dashboard.catalog import is_complete

    keys: list[str] = []
    resolved = resolve_cache_key(name, **parts)
    keys.append(resolved)
    if resolved != name:
        keys.append(name)

    fixture = load_fixture(name)
    fixture_first = os.environ.get("DASHBOARD_OFFLINE_SOURCE", "").strip().lower() == "fixture"
    if fixture_first and fixture.get("ok") is not False and is_complete(name, fixture):
        return fixture

    cached: dict[str, Any] | None = None
    for key in keys:
        snap = load_snapshot(key)
        if snap and snap.get("ok") is not False and is_complete(name, snap):
            cached = snap
            break

    if cached and is_complete(name, cached):
        return cached
    if fixture.get("ok") is not False and is_complete(name, fixture):
        return fixture
    if cached and cached.get("ok") is not False:
        return cached
    return fixture


def list_snapshots() -> list[dict[str, Any]]:
    if not SNAPSHOT_DIR.is_dir():
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(SNAPSHOT_DIR.glob("*.json")):
        name = path.stem
        if name in seen:
            continue
        seen.add(name)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        meta = payload.get("snapshot") if isinstance(payload, dict) else {}
        history = list_snapshot_history(name, limit=1)
        items.append(
            {
                "name": name,
                "path": str(path),
                "saved_at": (meta or {}).get("saved_at"),
                "origin": (meta or {}).get("origin"),
                "ok": bool((payload or {}).get("ok", True)),
                "history_count": len(list_snapshot_history(name, limit=1000)),
                "latest_history_path": history[0]["path"] if history else None,
            }
        )
    return items
