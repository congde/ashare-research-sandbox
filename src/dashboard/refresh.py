from __future__ import annotations

from typing import Any, Callable

from config.env import load_env
from dashboard import api as dashboard_api
from dashboard.snapshot import list_snapshots, save_snapshot
from dashboard.upstream import upstream_available


Fetcher = Callable[[], dict[str, Any]]


def _resolve(name: str, fetcher: Fetcher) -> tuple[dict[str, Any], str]:
    payload = fetcher()
    origin = str(payload.get("source") or "live")
    if payload.get("ok") is False:
        raise RuntimeError(str(payload.get("message") or f"{name} fetch failed"))
    return payload, origin


def refresh_all(*, save: bool = True) -> dict[str, Any]:
    """Fetch dashboard payloads (upstream → live) and optionally persist snapshots."""
    load_env()
    jobs: list[tuple[str, Fetcher]] = [
        ("ai_picks", dashboard_api.ai_picks),
        ("sector_fund", lambda: dashboard_api.sector_fund(1)),
        ("token_fund", lambda: dashboard_api.token_fund("BTC")),
        ("onchain", lambda: dashboard_api.onchain("BTC")),
        ("dex_trending", lambda: dashboard_api.dex_trending(chain="solana", limit=10)),
        ("market_tickers", lambda: dashboard_api.market_tickers(limit=100)),
        ("opportunity_scan", lambda: dashboard_api.opportunity_scan(top_k=5, max_symbols=20)),
        ("market_candles", lambda: dashboard_api.market_candles(limit=120, short=3, long=7)),
    ]

    saved: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for name, fetcher in jobs:
        try:
            payload, origin = _resolve(name, fetcher)
            if save:
                path = save_snapshot(name, payload, origin=origin)
                saved.append({"name": name, "path": str(path), "origin": origin})
        except Exception as exc:
            errors.append({"name": name, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "upstream_available": upstream_available(),
        "saved": saved,
        "errors": errors,
        "snapshots": list_snapshots(),
    }
