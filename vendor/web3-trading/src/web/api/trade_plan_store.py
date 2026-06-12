# -*- coding: utf-8 -*-
"""Persist entry tradePlan per open futures position (survives process restarts)."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_STORE_PATH = Path("data/live_futures_trade_plans.json")
_lock = threading.Lock()


def _key(account_id: str, symbol: str) -> str:
    base = str(symbol or "").upper().split("-")[0].split("/")[0]
    return f"{str(account_id or 'default').lower()}:{base}"


def _load_all() -> Dict[str, Any]:
    if not _STORE_PATH.exists():
        return {}
    try:
        with _STORE_PATH.open(encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("trade plan store load failed: %s", exc)
        return {}


def _save_all(data: Dict[str, Any]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    tmp.replace(_STORE_PATH)


def save_entry_trade_plan(
    account_id: str,
    symbol: str,
    plan: Dict[str, Any],
    *,
    side: str,
    entry_price: float = 0.0,
) -> None:
    if not plan or not plan.get("stop"):
        return
    payload = {
        "plan": dict(plan),
        "side": side,
        "entryPrice": entry_price,
        "savedAt": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        data = _load_all()
        data[_key(account_id, symbol)] = payload
        _save_all(data)


def get_entry_trade_plan(account_id: str, symbol: str) -> Optional[Dict[str, Any]]:
    with _lock:
        row = _load_all().get(_key(account_id, symbol))
    if not isinstance(row, dict):
        return None
    plan = row.get("plan")
    return plan if isinstance(plan, dict) else None


def clear_entry_trade_plan(account_id: str, symbol: str) -> None:
    with _lock:
        data = _load_all()
        key = _key(account_id, symbol)
        if key in data:
            del data[key]
            _save_all(data)


def resolve_position_trade_plan(
    account_id: str,
    symbol: str,
    fallback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Prefer plan locked at entry; fall back to current analysis only if missing."""
    stored = get_entry_trade_plan(account_id, symbol)
    if stored:
        return stored
    return fallback if isinstance(fallback, dict) else {}


def reconcile_stored_plans(account_id: str, open_symbols: set[str]) -> list[str]:
    """Drop locked plans when exchange has no position (e.g. manual close)."""
    removed: list[str] = []
    prefix = f"{str(account_id or 'default').lower()}:"
    with _lock:
        data = _load_all()
        for key in list(data.keys()):
            if not key.startswith(prefix):
                continue
            sym = key.split(":", 1)[-1]
            if sym not in open_symbols:
                del data[key]
                removed.append(sym)
        if removed:
            _save_all(data)
    return removed
