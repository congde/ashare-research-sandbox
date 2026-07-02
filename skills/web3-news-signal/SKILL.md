---
name: web3-news-signal
description: Build or improve no-key Web3 news, RSS, GDELT, announcement, security-event, governance, and social-sentiment data pipelines, then convert those message-side inputs into cached dashboard signals, trading research features, factor-mining inputs, or backtest annotations. Use when the user asks for Web3 message-side data, crypto news, sentiment, event data, no-key news sources, or turning Web3 news into factors or skills.
---

# Web3 News Signal

## Workflow

1. Inspect the existing data path before adding sources:
   - Backend: `src/dashboard/api.py`, `src/dashboard/http_client.py`, `src/dashboard/snapshot.py`, `src/dashboard/catalog.py`.
   - Frontend: `src/web/src/api.ts`, `src/web/src/types.ts`, and the target page under `src/web/src/pages/trading/`.
   - Offline data: `data/dashboard/*.json` and `data/dashboard/snapshots/*.json`.
2. Prefer no-key public sources first. Use keyed services only as optional enhancers.
3. Normalize every item into a stable event row:
   - `source`, `source_id`, `title`, `url`, `published_at`, `summary`.
   - Derived fields: `assets`, `topics`, `sentiment`, `risk_event`.
4. Convert news rows into research signals:
   - `news_heat_24h`
   - `risk_event_count_24h`
   - `positive_news_ratio_24h`
   - `asset_mention_count_24h`
   - Optional: `topic_counts`, `source_counts`, `event_decay_score`.
5. Cache and snapshot the aggregate payload. The feature must still work with no network.
6. Expose a small API and UI surface before wiring signals into trading logic:
   - API example: `/api/dashboard/web3-news?limit=50&refresh=1`.
   - UI should show article count, sentiment, risk events, top assets/topics, and recent items.
7. When adding factors, keep message-side features point-in-time:
   - Use only items published at or before the candle timestamp.
   - Use rolling windows and decay; do not leak future articles into historical bars.

## Source Selection

Read `references/no-key-web3-news-sources.md` when choosing sources, field mappings, or signal definitions.
Read `references/implementation-summary.md` when summarizing what has been implemented, explaining tradeoffs, or planning the next expansion.

Default no-key stack:

- RSS: Cointelegraph, The Block, Decrypt.
- Global search/news index: GDELT DOC API.
- Optional public project sources: protocol blogs, GitHub releases, governance forums, status pages, and security blogs.

## Implementation Rules

- Use standard parsers where possible: XML parser for RSS/Atom, JSON parser for GDELT.
- Do not scrape arbitrary HTML pages unless RSS/API is unavailable and the target is stable.
- Use a clear `User-Agent`.
- Deduplicate by canonical URL first, then normalized title.
- Treat sentiment as a weak feature. Prefer simple, auditable scoring unless a configured LLM is explicitly available.
- Store live failures as source health metadata, not as hard page failures.
- Add fixtures and tests for parser, enrichment, and API shape.

## Verification

Run focused tests first:

```powershell
py -m pytest tests/test_dashboard.py tests/test_dashboard_news.py
```

Then run the project verifier:

```powershell
py scripts/course.py verify
```
