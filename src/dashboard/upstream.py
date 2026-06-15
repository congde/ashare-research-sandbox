from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

from config.web3_trading import get_upstream_base_url
from dashboard.http_client import http_get


def upstream_mode() -> str:
    return os.environ.get("WEB3_TRADING_UPSTREAM", "never").strip().lower()


def upstream_enabled() -> bool:
    return upstream_mode() != "never" and bool(get_upstream_base_url())


def upstream_get(
    api_path: str,
    query: dict[str, str | int | float | bool] | None = None,
    *,
    timeout: float = 12,
) -> dict[str, Any] | None:
    if not upstream_enabled():
        return None
    base = get_upstream_base_url()
    if not base:
        return None
    path = api_path if api_path.startswith("/") else f"/{api_path}"
    url = f"{base.rstrip('/')}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    try:
        payload = http_get(url, timeout=timeout)
    except RuntimeError:
        return None
    return payload if isinstance(payload, dict) else None


def upstream_available() -> bool:
    if not upstream_enabled():
        return False
    probe = upstream_get("/api/market/tickers", {"quote": "USDT", "limit": 1}, timeout=5)
    return bool(probe and probe.get("ok"))
