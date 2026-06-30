from __future__ import annotations

from typing import Any, Callable

from dashboard.background import schedule_background_refresh
from dashboard.catalog import is_complete
from dashboard.fixtures import load_offline
from dashboard.mode import background_refresh_enabled, dashboard_data_mode, serve_offline_first


def complete_offline(name: str, **parts: str | int) -> dict[str, Any] | None:
    payload = load_offline(name, **parts)
    if payload.get("ok") is False:
        return None
    if not is_complete(name, payload):
        return None
    return payload


def try_cached_first(
    name: str,
    *,
    refresh: bool = False,
    background_key: str | None = None,
    fetch_live: Callable[[], None] | None = None,
    **parts: str | int,
) -> dict[str, Any] | None:
    """Prefer complete offline snapshots for teaching demos; optional background live refresh."""
    if not serve_offline_first(refresh=refresh):
        return None

    mode = dashboard_data_mode()
    if mode == "offline":
        payload = load_offline(name, **parts)
        return payload if payload.get("ok") is not False else None

    cached = complete_offline(name, **parts)
    if cached is None:
        return None
    if background_refresh_enabled() and background_key and fetch_live is not None:
        schedule_background_refresh(background_key, fetch_live)
    return cached
