# -*- coding: utf-8 -*-
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
for mod_name in (
    "dc_api_security",
    "dc_api_security.kc_eureka",
    "dc_api_security.kc_eureka.http_client",
):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from web.api import news_sources_extended as ext


REDDIT_SAMPLE = {
    "data": {
        "children": [
            {
                "data": {
                    "id": "abc",
                    "title": "Bitcoin hits new high",
                    "permalink": "/r/Bitcoin/comments/abc/test/",
                    "created_utc": 1710000000,
                    "selftext": "Discussion thread",
                }
            }
        ]
    }
}

MEDIUM_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>BTC outlook</title><link>https://medium.com/p/1</link>
<description><![CDATA[Summary here]]></description><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item>
</channel></rss>"""


@pytest.mark.asyncio
async def test_fetch_reddit_news_parses_json(monkeypatch):
    async def fake_get(url, **kwargs):
        assert "reddit.com" in url
        return REDDIT_SAMPLE

    monkeypatch.setattr(ext.http, "get", fake_get)
    items = await ext.fetch_reddit_news("BTC", 5)
    assert len(items) >= 1
    assert items[0]["source"].startswith("reddit_")
    assert "Bitcoin" in items[0]["title"]


@pytest.mark.asyncio
async def test_fetch_medium_rss(monkeypatch):
    async def fake_get(url, **kwargs):
        assert "medium.com/feed/tag/bitcoin" in url
        return MEDIUM_RSS

    monkeypatch.setattr(ext.http, "get", fake_get)
    items = await ext._fetch_medium_rss("BTC", 3)
    assert len(items) == 1
    assert items[0]["source"] == "medium"
    assert items[0]["title"] == "BTC outlook"


@pytest.mark.asyncio
async def test_cryptocompare_requires_key(monkeypatch):
    monkeypatch.setattr(ext, "CRYPTOCOMPARE_API_KEY", "")
    assert await ext.fetch_cryptocompare_news("BTC", 5) == []


@pytest.mark.asyncio
async def test_cryptocompare_parses_with_key(monkeypatch):
    monkeypatch.setattr(ext, "CRYPTOCOMPARE_API_KEY", "test-key")

    async def fake_get(url, **kwargs):
        return {
            "Data": [
                {
                    "id": 1,
                    "title": "ETH upgrade news",
                    "url": "https://example.com/a",
                    "body": "details",
                    "published_on": 1710000000,
                    "source_info": {"name": "cryptocompare"},
                }
            ]
        }

    monkeypatch.setattr(ext.http, "get", fake_get)
    items = await ext.fetch_cryptocompare_news("ETH", 5)
    assert len(items) == 1
    assert items[0]["title"] == "ETH upgrade news"


def test_parse_lunarcrush_posts():
    payload = {
        "data": [
            {
                "id": "p1",
                "post_title": "BTC pump",
                "post_link": "https://x.com/user/status/1",
                "network": "twitter",
                "post_text": "moon",
            }
        ]
    }
    items = ext._parse_lunarcrush_posts(payload, "lunarcrush", 5)
    assert items[0]["source"] == "lunarcrush_twitter"
    assert "x.com" in items[0]["url"]


@pytest.mark.asyncio
async def test_fetch_extended_merges_sources(monkeypatch):
    async def fake_medium(symbol, limit):
        return [{"id": "1", "title": "M1", "url": "", "source": "medium", "publishedAt": "", "body": ""}]

    async def fake_reddit(symbol, limit):
        return [{"id": "2", "title": "R1", "url": "", "source": "reddit_bitcoin", "publishedAt": "", "body": ""}]

    monkeypatch.setattr(ext, "_fetch_medium_rss", fake_medium)
    monkeypatch.setattr(ext, "fetch_reddit_news", fake_reddit)
    monkeypatch.setattr(ext, "CRYPTOCOMPARE_API_KEY", "")
    monkeypatch.setattr(ext, "COINGECKO_API_KEY", "")
    monkeypatch.setattr(ext, "LUNARCRUSH_API_KEY", "")

    items, sources = await ext.fetch_extended_news_sources("BTC", 10)
    assert len(items) == 2
    assert "medium" in sources
    assert "reddit" in sources
