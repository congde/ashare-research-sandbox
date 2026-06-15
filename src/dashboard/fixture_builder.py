from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from dashboard import market, opportunity
from dashboard.catalog import SNAPSHOT_NAMES, is_complete
from dashboard.snapshot import fixture_path, load_fixture, load_snapshot, save_snapshot
from paths import DATA_DIR


def _write_fixture(name: str, payload: dict[str, Any]) -> Path:
    body = dict(payload)
    body["ok"] = body.get("ok", True)
    body["source"] = "fixture"
    body.pop("snapshot", None)
    path = fixture_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_opportunity_scan_from_tickers(tickers_payload: dict[str, Any], *, top_k: int = 5) -> dict[str, Any]:
    tickers = list(tickers_payload.get("tickers") or [])
    if not tickers:
        raise RuntimeError("market_tickers fixture has no tickers")
    original_fetch = market.fetch_market_tickers

    def _local_tickers(*, quote: str = "USDT", limit: int = 300) -> dict[str, Any]:
        trimmed = tickers
        if limit > 0:
            trimmed = trimmed[:limit]
        return {
            "ok": True,
            "source": tickers_payload.get("source", "fixture"),
            "quote": quote.upper(),
            "count": len(trimmed),
            "tickers": trimmed,
        }

    market.fetch_market_tickers = _local_tickers  # type: ignore[assignment]
    try:
        payload = opportunity.scan_opportunities(top_k=top_k, max_symbols=min(20, len(tickers)), min_volume_24h=1000)
    finally:
        market.fetch_market_tickers = original_fetch  # type: ignore[assignment]
    payload["source"] = "fixture"
    return payload


def trim_market_candles(payload: dict[str, Any], *, limit: int = 35) -> dict[str, Any]:
    body = dict(payload)
    candles = list(body.get("candles") or [])
    if candles:
        candles = candles[-limit:]
        body["candles"] = candles
        body["curve"] = market.candles_to_curve(candles, short=3, long=7)
    curve = list(body.get("curve") or [])
    if curve and not candles:
        body["curve"] = curve[-limit:]
    body["source"] = "fixture"
    body.pop("snapshot", None)
    return body


def ensure_fixture(name: str, payload: dict[str, Any]) -> Path:
    if not is_complete(name, payload):
        raise RuntimeError(f"fixture {name} is incomplete")
    return _write_fixture(name, payload)


def rebuild_incomplete_fixtures() -> list[dict[str, Any]]:
    """Fill bundled teaching fixtures from snapshots or derived data."""
    results: list[dict[str, Any]] = []
    tickers = load_fixture("market_tickers")
    if not is_complete("market_tickers", tickers):
        raise RuntimeError("market_tickers fixture is required as seed data")

    jobs: list[tuple[str, Any]] = [
        ("opportunity_scan", lambda: build_opportunity_scan_from_tickers(tickers)),
    ]

    snapshot_candles = load_snapshot("market_candles")
    if is_complete("market_candles", snapshot_candles):
        jobs.append(("market_candles", lambda: trim_market_candles(snapshot_candles)))
    elif not is_complete("market_candles", load_fixture("market_candles")):
        jobs.append(
            (
                "market_candles",
                lambda: trim_market_candles(
                    {
                        "ok": True,
                        "symbol": "BTC-USDT",
                        "type": "1day",
                        "candles": _synthetic_candles(),
                    }
                ),
            )
        )

    for name, builder in jobs:
        current = load_fixture(name)
        if is_complete(name, current):
            results.append({"name": name, "action": "skipped", "reason": "already complete"})
            continue
        payload = builder()
        path = ensure_fixture(name, payload)
        results.append({"name": name, "action": "written", "path": str(path)})

    return results


def _synthetic_candles() -> list[dict[str, Any]]:
    """Small deterministic BTC-USDT series for offline chart fallback."""
    base = 94_000.0
    rows: list[dict[str, Any]] = []
    for index in range(35):
        drift = ((index % 5) - 2) * 180
        close = base + drift + index * 35
        ts_sec = 1_740_000_000 + index * 86_400
        rows.append(
            {
                "tsSec": ts_sec,
                "date": market._ts_to_date(ts_sec),
                "open": close - 120,
                "close": close,
                "high": close + 240,
                "low": close - 260,
                "volume": 1200 + index * 15,
            }
        )
    return rows


def promote_snapshot_to_fixture(name: str) -> Path | None:
    payload = load_snapshot(name)
    if not payload or not is_complete(name, payload):
        return None
    if name == "market_candles":
        payload = trim_market_candles(payload)
    return ensure_fixture(name, payload)


def sync_all_fixtures_from_snapshots() -> list[dict[str, Any]]:
    """Copy complete snapshots into git-tracked teaching fixtures."""
    results: list[dict[str, Any]] = []
    for name in SNAPSHOT_NAMES:
        path = promote_snapshot_to_fixture(name)
        if path:
            results.append({"name": name, "action": "written", "path": str(path)})
        else:
            current = load_fixture(name)
            if is_complete(name, current):
                results.append({"name": name, "action": "skipped", "reason": "fixture already complete"})
            else:
                results.append({"name": name, "action": "skipped", "reason": "no complete snapshot"})
    return results


def refresh_manifest_from_disk() -> dict[str, Any]:
    from dashboard.catalog import record_dataset, completeness_detail
    from dashboard.snapshot import fixture_path, load_fixture, load_snapshot

    for name in ("ai_picks", "sector_fund", "token_fund", "onchain", "dex_trending", "market_tickers", "opportunity_scan", "market_candles"):
        snapshot = load_snapshot(name)
        if snapshot:
            detail = completeness_detail(name, snapshot)
            meta = snapshot.get("snapshot") or {}
            record_dataset(
                name,
                layer="snapshot",
                origin=str(meta.get("origin") or snapshot.get("source") or "unknown"),
                path=str(DATA_DIR / "dashboard" / "snapshots" / f"{name}.json"),
                complete=detail["complete"],
                reason=str(detail.get("reason") or ""),
            )
        fixture = load_fixture(name)
        if fixture.get("ok") is not False:
            detail = completeness_detail(name, fixture)
            record_dataset(
                name,
                layer="fixture",
                origin="fixture",
                path=str(fixture_path(name)),
                complete=detail["complete"],
                reason=str(detail.get("reason") or ""),
            )
    from dashboard.catalog import load_manifest

    return load_manifest()
