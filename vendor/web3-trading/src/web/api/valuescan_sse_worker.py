# -*- coding: utf-8 -*-
"""Persistent ValueScan SSE subscriptions (market + token signals) with in-process cache."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

import httpx

logger = logging.getLogger(__name__)

_market_task: Optional[asyncio.Task] = None
_signal_task: Optional[asyncio.Task] = None
_refresh_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        try:
            from web.config import config

            attr = name.lower()
            if hasattr(config, attr):
                val = getattr(config, attr)
                if isinstance(val, bool):
                    return val
                if val is not None:
                    return str(val).lower() in ("1", "true", "yes", "y")
        except Exception:
            pass
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "y")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


def worker_enabled() -> bool:
    if not _env_bool("VS_SSE_WORKER_ENABLED", True):
        return False
    from web.api import valuescan_service as vs

    return bool(vs.VS_API_KEY and vs.VS_SECRET_KEY)


@dataclass
class _StreamCache:
    market_events: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=30))
    signals_by_token: Dict[int, Deque[Dict[str, Any]]] = field(default_factory=dict)
    watch_token_ids: Set[int] = field(default_factory=set)
    symbol_to_token_id: Dict[str, int] = field(default_factory=dict)
    market_connected: bool = False
    signal_connected: bool = False
    last_market_ts: int = 0
    last_signal_ts: int = 0
    last_error: str = ""
    reconnect_count: int = 0


_cache = _StreamCache()
_cache_lock = asyncio.Lock()


def _parse_sse_payload(raw_data: str) -> Dict[str, Any]:
    try:
        outer = json.loads(raw_data)
    except json.JSONDecodeError:
        return {"raw": raw_data}
    if not isinstance(outer, dict):
        return {"raw": raw_data}
    content = outer.get("content")
    if isinstance(content, str) and content.strip().startswith("{"):
        try:
            inner = json.loads(content)
            if isinstance(inner, dict):
                return {**outer, "parsed": inner}
        except json.JSONDecodeError:
            pass
    return outer


async def _append_market(event: Dict[str, Any]) -> None:
    async with _cache_lock:
        _cache.market_events.append(event)
        _cache.last_market_ts = int(time.time() * 1000)
        _cache.market_connected = True


async def _append_signal(vs_token_id: int, event: Dict[str, Any]) -> None:
    async with _cache_lock:
        if vs_token_id not in _cache.signals_by_token:
            max_n = _env_int("VS_SSE_MAX_EVENTS_PER_TOKEN", 30)
            _cache.signals_by_token[vs_token_id] = deque(maxlen=max_n)
        _cache.signals_by_token[vs_token_id].append(event)
        _cache.last_signal_ts = int(time.time() * 1000)
        _cache.signal_connected = True


async def _sse_consume_loop(
    path: str,
    *,
    extra_params: Optional[Dict[str, Any]] = None,
    on_event,
    stream_name: str,
    accept_events: Tuple[str, ...] = ("market", "signal", ""),
) -> None:
    from web.api.valuescan_service import VS_STREAM_BASE, _stream_query

    backoff = max(2, _env_int("VS_SSE_RECONNECT_SEC", 5))
    max_backoff = 120

    while _stop_event and not _stop_event.is_set():
        url = f"{VS_STREAM_BASE}{path}?{_stream_query(extra_params)}"
        event_name = ""
        data_lines: List[str] = []

        def _flush() -> Optional[Dict[str, Any]]:
            nonlocal event_name, data_lines
            name = event_name or ""
            if data_lines and (name in accept_events or (not name and stream_name == "market")):
                raw = "\n".join(data_lines)
                payload = _parse_sse_payload(raw) if raw else {}
                event_name = ""
                data_lines = []
                if payload:
                    return payload
            event_name = ""
            data_lines = []
            return None

        try:
            timeout = httpx.Timeout(None, connect=30.0)
            async with httpx.AsyncClient(verify=False, timeout=timeout) as client:
                async with client.stream(
                    "GET",
                    url,
                    headers={"Accept": "text/event-stream"},
                ) as resp:
                    if resp.status_code != 200:
                        raise RuntimeError(f"HTTP {resp.status_code}")
                    async for line in resp.aiter_lines():
                        if _stop_event and _stop_event.is_set():
                            break
                        if not line:
                            payload = _flush()
                            if payload:
                                await on_event(payload)
                            continue
                        if line.startswith(":"):
                            continue
                        if line.startswith("event:"):
                            flushed = _flush()
                            if flushed:
                                await on_event(flushed)
                            event_name = line[6:].strip()
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].strip())
                    flushed = _flush()
                    if flushed:
                        await on_event(flushed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            async with _cache_lock:
                _cache.last_error = f"{stream_name}: {type(exc).__name__}: {exc}"
                _cache.reconnect_count += 1
                if stream_name == "market":
                    _cache.market_connected = False
                else:
                    _cache.signal_connected = False
            logger.warning("VS SSE %s disconnected: %s — retry in %ss", stream_name, exc, backoff)
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=backoff)
                break
            except asyncio.TimeoutError:
                backoff = min(max_backoff, backoff * 2)


async def _market_loop() -> None:
    async def _on(payload: Dict[str, Any]) -> None:
        await _append_market({"event": "market", **payload})

    await _sse_consume_loop(
        "/stream/market/subscribe",
        on_event=_on,
        stream_name="market",
        accept_events=("market", "connected", ""),
    )


async def _signal_loop() -> None:
    async def _on(payload: Dict[str, Any]) -> None:
        token_id = int(payload.get("tokenId") or payload.get("token_id") or 0)
        if token_id <= 0:
            return
        await _append_signal(token_id, {"event": "signal", **payload})

    while _stop_event and not _stop_event.is_set():
        async with _cache_lock:
            token_ids = sorted(_cache.watch_token_ids)
        extra = {"tokens": ",".join(str(i) for i in token_ids)} if token_ids else {"tokens": ""}
        await _sse_consume_loop(
            "/stream/signal/subscribe",
            extra_params=extra,
            on_event=_on,
            stream_name="signal",
            accept_events=("signal",),
        )


def _normalize_symbol(value: str) -> str:
    return str(value or "").strip().upper().split("-")[0].split("/")[0]


async def resolve_symbols_to_token_ids(symbols: List[str]) -> Dict[str, int]:
    from web.api import valuescan_service as vs

    out: Dict[str, int] = {}
    for sym in symbols:
        base = _normalize_symbol(sym)
        if not base or base in out:
            continue
        try:
            token = await vs.search_token(base)
            if token and token.get("id"):
                out[base] = int(token["id"])
        except Exception as exc:
            logger.debug("VS token resolve %s: %s", base, exc)
    return out


async def update_watch_symbols(symbols: List[str]) -> Dict[str, int]:
    """Merge symbols into SSE subscription watchlist; returns symbol→vsTokenId."""
    bases = [_normalize_symbol(s) for s in symbols if _normalize_symbol(s)]
    mapping = await resolve_symbols_to_token_ids(bases)
    async with _cache_lock:
        for sym, vs_id in mapping.items():
            _cache.symbol_to_token_id[sym] = vs_id
            _cache.watch_token_ids.add(vs_id)
    return mapping


async def _watchlist_refresh_loop() -> None:
    interval = max(30, _env_int("VS_SSE_WATCH_REFRESH_SEC", 90))
    default_syms = os.environ.get("VS_SSE_WATCH_SYMBOLS", "BTC,ETH,HYPE,SOL")
    while _stop_event and not _stop_event.is_set():
        symbols = [s.strip() for s in default_syms.replace(";", ",").split(",") if s.strip()]
        try:
            from web.api.position_vs_alerts import collect_watch_symbols_for_sse

            symbols = await collect_watch_symbols_for_sse(symbols)
        except Exception as exc:
            logger.debug("watchlist collect: %s", exc)
        await update_watch_symbols(symbols)
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            continue


def get_worker_status() -> Dict[str, Any]:
    return {
        "enabled": worker_enabled(),
        "marketConnected": _cache.market_connected,
        "signalConnected": _cache.signal_connected,
        "watchTokenCount": len(_cache.watch_token_ids),
        "watchSymbols": list(_cache.symbol_to_token_id.keys()),
        "lastMarketTs": _cache.last_market_ts,
        "lastSignalTs": _cache.last_signal_ts,
        "reconnectCount": _cache.reconnect_count,
        "lastError": _cache.last_error or None,
        "marketEventCount": len(_cache.market_events),
        "signalTokenCount": len(_cache.signals_by_token),
    }


def get_cached_market_events(limit: int = 5) -> List[Dict[str, Any]]:
    return list(_cache.market_events)[-limit:]


def get_cached_signal_events(
    *,
    vs_token_id: Optional[int] = None,
    symbol: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    tid = vs_token_id
    if tid is None and symbol:
        tid = _cache.symbol_to_token_id.get(_normalize_symbol(symbol))
    if not tid:
        return []
    dq = _cache.signals_by_token.get(int(tid))
    if not dq:
        return []
    return list(dq)[-limit:]


def get_worker_snapshot(vs_token_id: Optional[int] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
    return {
        "status": get_worker_status(),
        "market": get_cached_market_events(5),
        "signals": get_cached_signal_events(vs_token_id=vs_token_id, symbol=symbol, limit=10),
    }


async def start_valuescan_sse_worker() -> None:
    global _market_task, _signal_task, _refresh_task, _stop_event
    if not worker_enabled():
        logger.info("ValueScan SSE worker disabled (credentials or VS_SSE_WORKER_ENABLED)")
        return
    if _market_task and not _market_task.done():
        return
    _stop_event = asyncio.Event()
    default_syms = os.environ.get("VS_SSE_WATCH_SYMBOLS", "BTC,ETH,HYPE,SOL")
    await update_watch_symbols([s.strip() for s in default_syms.split(",") if s.strip()])
    _market_task = asyncio.create_task(_market_loop(), name="vs-sse-market")
    _signal_task = asyncio.create_task(_signal_loop(), name="vs-sse-signal")
    _refresh_task = asyncio.create_task(_watchlist_refresh_loop(), name="vs-sse-watch-refresh")
    logger.info("ValueScan SSE worker started (watch=%s)", list(_cache.symbol_to_token_id.keys()))


async def stop_valuescan_sse_worker() -> None:
    global _market_task, _signal_task, _refresh_task, _stop_event
    if _stop_event:
        _stop_event.set()
    for task in (_market_task, _signal_task, _refresh_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _market_task = None
    _signal_task = None
    _refresh_task = None
    _stop_event = None
    async with _cache_lock:
        _cache.market_connected = False
        _cache.signal_connected = False
    logger.info("ValueScan SSE worker stopped")
