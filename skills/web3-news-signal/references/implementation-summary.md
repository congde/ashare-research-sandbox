# Web3 News Signal Implementation Summary

Use this summary when explaining the current Web3 message-side implementation or planning the next iteration.

## What External Examples Suggest

Common crypto sentiment/news systems use three layers:

1. News/RSS aggregation
   - Pull many RSS/Atom feeds from crypto media and protocol blogs.
   - Normalize each article into one schema.
   - Deduplicate by URL/title.
   - Track source health because public feeds often timeout or change.
2. News-index enrichment
   - Query public indexes such as GDELT for wider coverage.
   - Use this as a supplement, not the only source, because public rate limits can be strict.
3. Signal extraction
   - Tag assets, topics, and risk events.
   - Produce rolling metrics such as article count, positive ratio, risk-event count, source breadth, and asset mention counts.
   - Keep all signals point-in-time for backtests.

Avoid relying on social platforms as the default no-key source. X/Twitter, Reddit, Telegram, and Discord usually require keys, login state, scraping workarounds, or strict rate-limit handling.

## Current Repo Implementation

Backend files:

- `src/dashboard/news.py`
  - Fetches no-key RSS/Atom feeds.
  - Optionally enriches with GDELT DOC API.
  - Parses RSS/Atom with standard-library XML.
  - Tags assets, topics, sentiment, and risk events.
  - Produces `metrics` and `factor_signals`.
- `src/dashboard/api.py`
  - Exposes `web3_news(limit, refresh)`.
  - Uses the existing cache/snapshot flow.
- `app.py`
  - Adds `/api/dashboard/web3-news`.
- `src/dashboard/catalog.py`
  - Adds `web3_news` to offline completeness checks.
- `data/dashboard/web3_news.json`
  - Provides an offline fixture.

Frontend files:

- `src/web/src/api.ts`
  - Adds `fetchWeb3News`.
- `src/web/src/types.ts`
  - Adds `Web3NewsPayload` and `Web3NewsItem`.
- `src/web/src/pages/research/ResearchPage.tsx`
  - Shows "Web3 消息面情报" on `/research`.
  - Loads up to 80 items.
  - Displays 12 recent items.
  - Makes news rows clickable in a new browser tab.
- `src/web/src/pages/research/research.css`
  - Adds link hover affordance.

## Default No-Key Sources

Current default RSS/Atom sources:

- Cointelegraph
- The Block
- Decrypt
- CryptoSlate
- Cryptopolitan
- Bitcoin Magazine
- BeInCrypto
- Ethereum Foundation

Supplemental source:

- GDELT DOC API

Observed behavior from implementation testing:

- A live refresh can reach about 80 deduplicated items when public feeds respond.
- Some sources occasionally timeout or fail; keep them in source health metadata instead of failing the whole endpoint.
- GDELT may return HTTP 429 when queried too frequently; use cached snapshots and only refresh on demand.

## Output Schema

Article row:

```json
{
  "source": "The Block",
  "source_id": "theblock",
  "source_category": "news",
  "title": "Article title",
  "url": "https://...",
  "published_at": "2026-07-02T02:20:24+00:00",
  "summary": "Short text",
  "assets": ["BTC"],
  "topics": ["ETF"],
  "sentiment": 1,
  "risk_event": false
}
```

Aggregate metrics:

- `article_count`
- `positive_count`
- `negative_count`
- `risk_event_count`
- `positive_ratio`
- `sentiment_score`
- `top_topics`
- `top_assets`
- `source_breadth`

Factor signals:

- `news_heat_24h`
- `risk_event_count_24h`
- `positive_news_ratio_24h`
- `asset_mention_count_24h`
- `source_breadth_24h`

## Current Tradeoffs

- RSS/Atom is stable and no-key, but source quality varies.
- GDELT improves breadth, but must be rate-limited and cached.
- Rule-based sentiment is auditable, but weaker than a calibrated NLP/LLM classifier.
- Current features are dashboard-level signals. Historical backtest integration must compute rolling features by article publication time to avoid lookahead.

## Next Expansion

Recommended next steps:

1. Add source-health UI:
   - Show each source as ok/error/count.
   - Surface GDELT 429 separately as "rate limited".
2. Add topic filters:
   - `All`, `ETF`, `DeFi`, `Security`, `Regulation`, `Stablecoin`, `Protocol`.
3. Add historical news feature store:
   - Persist articles with published time.
   - Build rolling point-in-time features for each candle.
4. Add LLM-assisted classification as optional:
   - Use LLM only when a key is configured.
   - Keep deterministic keyword fallback.
5. Add protocol-specific feeds:
   - Ethereum Foundation is already included.
   - Add more only after verifying stable RSS/Atom endpoints.
