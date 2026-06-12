from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import DATA_DIR

SNAPSHOT_DIR = DATA_DIR / "dashboard" / "snapshots"
FIXTURE_DIR = DATA_DIR / "dashboard"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def snapshot_path(name: str) -> Path:
    return SNAPSHOT_DIR / f"{name}.json"


def fixture_path(name: str) -> Path:
    return FIXTURE_DIR / f"{name}.json"


def save_snapshot(name: str, payload: dict[str, Any], *, origin: str) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body["ok"] = body.get("ok", True)
    body["source"] = "snapshot"
    body["snapshot"] = {
        "name": name,
        "saved_at": _now_iso(),
        "origin": origin,
    }
    path = snapshot_path(name)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_snapshot(name: str) -> dict[str, Any] | None:
    path = snapshot_path(name)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    payload.setdefault("ok", True)
    payload.setdefault("source", "snapshot")
    return payload


def load_fixture(name: str) -> dict[str, Any]:
    path = fixture_path(name)
    if not path.is_file():
        return {"ok": False, "message": f"missing fixture: {name}", "source": "fixture"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("source", "fixture")
    payload.setdefault("ok", True)
    return payload


def load_offline(name: str) -> dict[str, Any]:
    """Prefer saved snapshot, then bundled teaching fixture."""
    cached = load_snapshot(name)
    if cached and cached.get("ok") is not False:
        return cached
    return load_fixture(name)


def list_snapshots() -> list[dict[str, Any]]:
    if not SNAPSHOT_DIR.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(SNAPSHOT_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        meta = payload.get("snapshot") if isinstance(payload, dict) else {}
        items.append(
            {
                "name": path.stem,
                "path": str(path),
                "saved_at": (meta or {}).get("saved_at"),
                "origin": (meta or {}).get("origin"),
                "ok": bool((payload or {}).get("ok", True)),
            }
        )
    return items
