from dashboard.news import build_web3_news_signal, parse_rss_feed


def test_parse_rss_feed_extracts_items() -> None:
    xml = """<?xml version="1.0"?>
<rss><channel><item><title>Bitcoin ETF approval boosts ETH sentiment</title>
<link>https://example.com/a</link><description>DeFi growth</description>
<pubDate>Thu, 02 Jul 2026 00:00:00 GMT</pubDate></item></channel></rss>"""

    items = parse_rss_feed(xml, source_id="test", source_name="Test")

    assert items[0]["source"] == "Test"
    assert items[0]["title"].startswith("Bitcoin ETF")
    assert items[0]["published_at"] == "2026-07-02T00:00:00+00:00"


def test_build_web3_news_signal_tags_assets_topics_and_risk() -> None:
    payload = build_web3_news_signal(
        [
            {
                "source": "Test",
                "title": "Ethereum DeFi exploit triggers SEC review",
                "summary": "hack and stolen funds",
                "url": "https://example.com/risk",
            },
            {
                "source": "Test",
                "title": "Bitcoin ETF inflow sets record",
                "summary": "approval and adoption",
                "url": "https://example.com/good",
            },
        ],
        watch_symbols=["BTC", "ETH"],
    )

    assert payload["metrics"]["article_count"] == 2
    assert payload["metrics"]["risk_event_count"] == 1
    assert payload["factor_signals"]["asset_mention_count_24h"]["BTC"] == 1
    assert payload["items"][0]["assets"]
