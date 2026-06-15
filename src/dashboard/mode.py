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


def try_live_public() -> bool:
    return dashboard_data_mode() in {"auto", "live"}
