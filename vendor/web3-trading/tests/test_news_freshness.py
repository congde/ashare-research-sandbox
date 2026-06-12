# -*- coding: utf-8 -*-
import unittest
from datetime import datetime, timedelta, timezone

from web.api.news_freshness import filter_fresh_news, parse_published_at, prepare_signal_news


class TestNewsFreshness(unittest.TestCase):
    def test_parse_iso_z(self):
        dt = parse_published_at("2026-06-04T10:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)

    def test_filter_drops_stale_and_untimestamped(self):
        now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
        fresh_ts = (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        stale_ts = (now - timedelta(hours=20)).isoformat().replace("+00:00", "Z")
        items = [
            {"title": "fresh", "publishedAt": fresh_ts},
            {"title": "stale", "publishedAt": stale_ts},
            {"title": "no time"},
        ]
        fresh = filter_fresh_news(items, max_age_hours=12, now=now)
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh[0]["title"], "fresh")

    def test_prepare_meta_gate_not_applicable_when_empty_fresh(self):
        now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
        stale_ts = (now - timedelta(hours=30)).isoformat().replace("+00:00", "Z")
        items = [{"title": "old", "publishedAt": stale_ts}]
        fresh, meta = prepare_signal_news(items)
        self.assertEqual(len(fresh), 0)
        self.assertFalse(meta["gateApplicable"])
        self.assertEqual(meta["totalCount"], 1)


if __name__ == "__main__":
    unittest.main()
