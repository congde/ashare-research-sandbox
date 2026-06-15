from __future__ import annotations

import os
from typing import Any, Callable

from config.env import load_env
from dashboard import api as dashboard_api
from dashboard.catalog import completeness_detail, offline_status
from dashboard.full_datasets import (
    fetch_full_dex_trending,
    fetch_full_kucoin_markets,
    fetch_full_market_candles,
    fetch_full_market_tickers,
    fetch_full_opportunity_scan,
    fetch_full_valuescan_global,
    fetch_full_valuescan_token,
)
from dashboard.normalize import normalize_ai_picks
from dashboard.snapshot import list_snapshots, save_snapshot
from dashboard.upstream import upstream_available
from dashboard import valuescan


Fetcher = Callable[[], dict[str, Any]]


def _resolve(name: str, fetcher: Fetcher) -> tuple[dict[str, Any], str]:
    payload = fetcher()
    origin = str(payload.get("source") or "live")
    if payload.get("ok") is False:
        raise RuntimeError(str(payload.get("message") or f"{name} fetch failed"))
    return payload, origin


def refresh_all(*, save: bool = True, data_mode: str = "auto") -> dict[str, Any]:
    """Fetch dashboard payloads (upstream → live) and optionally persist snapshots."""
    load_env()
    previous_mode = os.environ.get("DASHBOARD_DATA_MODE")
    os.environ["DASHBOARD_DATA_MODE"] = data_mode
    def _ai_picks_full() -> dict[str, Any]:
        if valuescan.configured():
            return normalize_ai_picks(valuescan.get_ai_picks())
        return dashboard_api.ai_picks()

    jobs: list[tuple[str, Fetcher]] = [
        ("ai_picks", _ai_picks_full),
        ("sector_fund", lambda: dashboard_api.sector_fund(1)),
        ("token_fund", lambda: dashboard_api.token_fund("BTC")),
        ("onchain", lambda: dashboard_api.onchain("BTC")),
        ("dex_trending", lambda: fetch_full_dex_trending(chain="solana")),
        ("market_tickers", lambda: fetch_full_market_tickers()),
        ("kucoin_markets", fetch_full_kucoin_markets),
        ("opportunity_scan", fetch_full_opportunity_scan),
        ("market_candles", lambda: fetch_full_market_candles()),
    ]
    if valuescan.configured():
        jobs.extend(
            [
                ("valuescan_global", fetch_full_valuescan_global),
                ("valuescan_token_full", lambda: fetch_full_valuescan_token("BTC")),
            ]
        )

    saved: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    try:
        for name, fetcher in jobs:
            try:
                payload, origin = _resolve(name, fetcher)
                detail = completeness_detail(name, payload)
                if save:
                    path = save_snapshot(name, payload, origin=origin)
                    saved.append(
                        {
                            "name": name,
                            "path": str(path),
                            "origin": origin,
                            "complete": detail["complete"],
                            "reason": detail.get("reason") or "",
                        }
                    )
                else:
                    saved.append(
                        {
                            "name": name,
                            "origin": origin,
                            "complete": detail["complete"],
                            "reason": detail.get("reason") or "",
                        }
                    )
            except Exception as exc:
                errors.append({"name": name, "error": str(exc)})
    finally:
        if previous_mode is None:
            os.environ.pop("DASHBOARD_DATA_MODE", None)
        else:
            os.environ["DASHBOARD_DATA_MODE"] = previous_mode

    status = offline_status()
    return {
        "ok": len(errors) == 0,
        "data_mode": data_mode,
        "upstream_available": upstream_available(),
        "saved": saved,
        "errors": errors,
        "snapshots": list_snapshots(),
        "offline": status,
    }
