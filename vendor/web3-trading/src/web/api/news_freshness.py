# -*- coding: utf-8 -*-
"""News freshness helpers for five-signal gate and LLM/signal scoring."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

_DEFAULT_GATE_HOURS = 12


def resolve_five_signal_news_gate_hours() -> int:
    """Max age (hours) for news to participate in five-signal hard gate."""
    try:
        from web.config import config

        raw = getattr(config, "five_signal_news_gate_hours", None)
        if raw is not None:
            hours = int(raw)
            return max(1, min(72, hours))
    except Exception:
        pass
    return _DEFAULT_GATE_HOURS


def parse_published_at(raw: Any) -> Optional[datetime]:
    """Parse assorted news timestamps to UTC-aware datetime."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, (int, float)):
        try:
            ts = float(raw)
        except (TypeError, ValueError):
            return None
        if ts > 1e12:
            ts /= 1000.0
        if ts <= 0:
            return None
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        text = str(raw).strip()
        if not text:
            return None
        if text.isdigit():
            return parse_published_at(int(text))
        # Unix seconds in string
        if re.fullmatch(r"\d{10,13}", text):
            return parse_published_at(int(text[:13] if len(text) > 10 else text))
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(text)
            except (TypeError, ValueError, IndexError):
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def filter_fresh_news(
    news_list: List[Dict[str, Any]],
    *,
    max_age_hours: Optional[int] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Keep items with publishedAt within max_age_hours (unparseable timestamps excluded)."""
    hours = max_age_hours if max_age_hours is not None else resolve_five_signal_news_gate_hours()
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=hours)
    fresh: List[Dict[str, Any]] = []
    for item in news_list or []:
        if not isinstance(item, dict):
            continue
        published = parse_published_at(
            item.get("publishedAt") or item.get("published_at") or item.get("pubDate")
        )
        if published is None or published < cutoff:
            continue
        fresh.append(item)
    return fresh


def build_news_meta(
    news_list: List[Dict[str, Any]],
    fresh_list: List[Dict[str, Any]],
    *,
    gate_hours: Optional[int] = None,
) -> Dict[str, Any]:
    hours = gate_hours if gate_hours is not None else resolve_five_signal_news_gate_hours()
    total = len(news_list or [])
    fresh_count = len(fresh_list or [])
    return {
        "gateHours": hours,
        "totalCount": total,
        "freshCount": fresh_count,
        "gateApplicable": fresh_count > 0,
    }


def prepare_signal_news(
    news_list: List[Dict[str, Any]],
    *,
    max_age_hours: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Filter to fresh items for LLM/scoring/gate; return (fresh, meta)."""
    hours = max_age_hours if max_age_hours is not None else resolve_five_signal_news_gate_hours()
    total_list = list(news_list or [])
    fresh = filter_fresh_news(total_list, max_age_hours=hours)
    return fresh, build_news_meta(total_list, fresh, gate_hours=hours)


def apply_news_freshness_to_aggregated(aggregated: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Set aggregated['news'] to fresh-only list and attach newsMeta."""
    raw = aggregated.get("news")
    if not isinstance(raw, list):
        raw = []
    fresh, meta = prepare_signal_news(raw)
    aggregated["news"] = fresh
    aggregated["newsCount"] = len(fresh)
    aggregated["newsMeta"] = meta
    return fresh, meta
