from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from paths import DATA_DIR

MANIFEST_PATH = DATA_DIR / "dashboard" / "manifest.json"
MANIFEST_VERSION = 1

DatasetCheck = Callable[[dict[str, Any]], tuple[bool, str]]

SNAPSHOT_NAMES = (
    "ai_picks",
    "sector_fund",
    "token_fund",
    "onchain",
    "dex_trending",
    "market_tickers",
    "opportunity_scan",
    "market_candles",
)


def _has_items(payload: dict[str, Any], key: str, *, minimum: int = 1) -> tuple[bool, str]:
    items = payload.get(key)
    if not isinstance(items, list) or len(items) < minimum:
        return False, f"missing or short list: {key}"
    return True, ""


def _check_opportunity_scan(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _has_items(payload, "opportunities", minimum=1)
    if not ok:
        return ok, reason
    sample = payload["opportunities"][0]
    required = ("symbol", "signal", "label", "score", "confidence", "change24h", "volume24h", "rank")
    missing = [field for field in required if sample.get(field) in (None, "")]
    if missing:
        return False, f"opportunity fields incomplete: {', '.join(missing)}"
    return True, ""


def _check_market_candles(payload: dict[str, Any]) -> tuple[bool, str]:
    curve = payload.get("curve") or []
    candles = payload.get("candles") or []
    if isinstance(curve, list) and len(curve) >= 5:
        return True, ""
    if isinstance(candles, list) and len(candles) >= 5:
        return True, ""
    return False, "missing curve/candles (need >= 5 points)"


DATASET_CHECKS: dict[str, DatasetCheck] = {
    "ai_picks": lambda payload: _has_items(payload, "chance", minimum=1),
    "sector_fund": lambda payload: _has_items(payload, "sectors", minimum=1),
    "token_fund": lambda payload: (True, "") if isinstance(payload.get("fund"), dict) else (False, "missing fund"),
    "onchain": lambda payload: (
        True,
        "",
    )
    if isinstance((payload.get("marketSentiment") or {}).get("fearGreed"), dict)
    and (payload.get("marketSentiment") or {}).get("fearGreed", {}).get("value") is not None
    else (False, "missing fearGreed.value"),
    "dex_trending": lambda payload: _has_items(payload, "tokens", minimum=1),
    "market_tickers": lambda payload: _has_items(payload, "tickers", minimum=1),
    "opportunity_scan": _check_opportunity_scan,
    "market_candles": _check_market_candles,
    "valuescan_token_full": lambda payload: (
        (True, "") if payload.get("vsTokenId") else (False, "missing vsTokenId")
    ),
    "valuescan_global": lambda payload: _has_items(payload, "chance", minimum=1),
    "kucoin_markets": lambda payload: _has_items(payload, "markets", minimum=1),
}


def is_complete(name: str, payload: dict[str, Any] | None) -> bool:
    if not payload or payload.get("ok") is False:
        return False
    checker = DATASET_CHECKS.get(name)
    if checker is None:
        return True
    ok, _ = checker(payload)
    return ok


def completeness_detail(name: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"complete": False, "reason": "missing payload"}
    if payload.get("ok") is False:
        return {"complete": False, "reason": payload.get("message") or "ok=false"}
    checker = DATASET_CHECKS.get(name)
    if checker is None:
        return {"complete": True, "reason": ""}
    ok, reason = checker(payload)
    return {"complete": ok, "reason": reason}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        return {"version": MANIFEST_VERSION, "updated_at": None, "datasets": {}}
    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": MANIFEST_VERSION, "updated_at": None, "datasets": {}}
    if not isinstance(payload, dict):
        return {"version": MANIFEST_VERSION, "updated_at": None, "datasets": {}}
    payload.setdefault("version", MANIFEST_VERSION)
    payload.setdefault("datasets", {})
    return payload


def save_manifest(manifest: dict[str, Any]) -> Path:
    manifest["version"] = MANIFEST_VERSION
    manifest["updated_at"] = _now_iso()
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return MANIFEST_PATH


def record_dataset(
    name: str,
    *,
    layer: str,
    origin: str,
    path: str,
    complete: bool,
    reason: str = "",
    cache_key: str | None = None,
    latest_path: str | None = None,
    history_id: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest()
    datasets = manifest.setdefault("datasets", {})
    entry: dict[str, Any] = {
        "layer": layer,
        "origin": origin,
        "path": path,
        "complete": complete,
        "reason": reason,
        "updated_at": _now_iso(),
    }
    if cache_key:
        entry["cache_key"] = cache_key
    if latest_path:
        entry["latest_path"] = latest_path
    if history_id:
        entry["history_id"] = history_id
    datasets[name] = entry
    save_manifest(manifest)
    return datasets[name]


def offline_status() -> dict[str, Any]:
    from dashboard.snapshot import fixture_path, load_fixture, load_snapshot

    datasets: dict[str, Any] = {}
    for name in SNAPSHOT_NAMES:
        snapshot = load_snapshot(name)
        fixture = load_fixture(name)
        snapshot_detail = completeness_detail(name, snapshot)
        fixture_detail = completeness_detail(name, fixture)
        active = "none"
        active_payload = None
        if snapshot_detail["complete"]:
            active = "snapshot"
            active_payload = snapshot
        elif fixture_detail["complete"]:
            active = "fixture"
            active_payload = fixture
        elif snapshot:
            active = "snapshot"
            active_payload = snapshot
        elif fixture.get("ok") is not False:
            active = "fixture"
            active_payload = fixture
        datasets[name] = {
            "snapshot": {
                "path": str((DATA_DIR / "dashboard" / "snapshots" / f"{name}.json")),
                **snapshot_detail,
            },
            "fixture": {
                "path": str(fixture_path(name)),
                **fixture_detail,
            },
            "active_layer": active,
            "active_source": (active_payload or {}).get("source"),
        }
    complete_count = sum(
        1
        for item in datasets.values()
        if item["snapshot"]["complete"] or item["fixture"]["complete"]
    )
    return {
        "ok": True,
        "manifest": load_manifest(),
        "datasets": datasets,
        "complete_count": complete_count,
        "total_count": len(SNAPSHOT_NAMES),
    }
