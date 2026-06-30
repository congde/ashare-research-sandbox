from __future__ import annotations

import os

from config.env import load_env
from dashboard import dexscan, valuescan
from dashboard.upstream import upstream_mode

VALID_MODES = frozenset({"offline", "auto", "live"})


def dashboard_data_mode() -> str:
    """Teaching default: offline snapshots/fixtures unless explicitly overridden."""
    load_env()
    explicit = os.environ.get("DASHBOARD_DATA_MODE", "").strip().lower()
    if explicit in VALID_MODES:
        return explicit
    return "offline"


def prefer_offline() -> bool:
    return dashboard_data_mode() == "offline"


def serve_offline_first(*, refresh: bool = False) -> bool:
    """Course UX: return persisted snapshots before hitting live APIs."""
    if refresh:
        return False
    return dashboard_data_mode() in {"offline", "auto"}


def background_refresh_enabled() -> bool:
    """Auto mode may refresh snapshots in a background thread after a fast response."""
    return dashboard_data_mode() == "auto"


def try_live_public() -> bool:
    return dashboard_data_mode() in {"auto", "live"}
