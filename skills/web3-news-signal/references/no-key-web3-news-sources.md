# No-Key Web3 News Sources

Use this reference when implementing Web3 message-side data without API keys.

## Primary Sources

| Source | URL | Use | Notes |
| --- | --- | --- | --- |
| Cointelegraph RSS | `https://cointelegraph.com/rss` | Crypto news, ETF, DeFi, exchange and project headlines | Public RSS; use as one of several sources, not single truth |
| The Block RSS | `https://www.theblock.co/rss.xml` | Institutional crypto, funding, exchange, DeFi, regulatory headlines | Public RSS; Cloudflare may occasionally slow responses |
| Decrypt RSS | `https://decrypt.co/feed` | Crypto, NFT, Web3 culture, AI x crypto, project news | Public RSS; useful for broader Web3 narratives |
| CryptoSlate RSS | `https://cryptoslate.com/feed/` | Crypto market, policy, exchange and ecosystem headlines | Public RSS |
| Cryptopolitan RSS | `https://www.cryptopolitan.com/feed/` | Broad crypto/Web3 headlines | Public RSS |
| Bitcoin Magazine RSS | `https://bitcoinmagazine.com/feed` | Bitcoin-specific market and policy headlines | Public RSS |
| BeInCrypto RSS | `https://beincrypto.com/feed/` | Crypto market and token news | Public RSS |
| Ethereum Foundation RSS | `https://blog.ethereum.org/feed.xml` | Protocol upgrades, Ethereum ecosystem announcements | Public RSS/Atom |
| GDELT DOC API | `https://api.gdeltproject.org/api/v2/doc/doc` | Global indexed news query for crypto/Web3 keywords | Public no-key API; query with `mode=artlist&format=json` |

## Optional Public Sources

- Protocol blogs and feeds: Ethereum Foundation blog, Chainlink blog, Uniswap governance, Aave governance, Maker/Sky forum, Lido forum.
- Security event sources: project postmortems, audit firm blogs, public incident reports.
- Repository signals: GitHub releases and commits for major protocols when repository relevance is known.
- Exchange/status feeds: public status pages and announcement RSS where available.

## Normalized Row

```json
{
  "source": "Cointelegraph",
  "source_id": "cointelegraph",
  "title": "Bitcoin ETF inflows lift market sentiment",
  "url": "https://...",
  "published_at": "2026-07-02T00:00:00+00:00",
  "summary": "Short cleaned summary text",
  "assets": ["BTC"],
  "topics": ["ETF"],
  "sentiment": 2,
  "risk_event": false
}
```

## Keyword Tags

Assets:

- `BTC`: bitcoin, btc, spot bitcoin, bitcoin etf
- `ETH`: ethereum, eth, ether, staking
- `SOL`: solana, sol
- `BNB`: bnb, binance
- `XRP`: xrp, ripple
- `USDT`: tether, usdt
- `USDC`: usdc, circle

Topics:

- `ETF`: etf
- `DeFi`: defi, dex, liquidity pool, lending protocol
- `Stablecoin`: stablecoin, usdt, usdc, tether, circle
- `Security`: hack, exploit, breach, stolen, vulnerability, rug pull
- `Regulation`: sec, cftc, lawsuit, regulation, regulator, compliance
- `Airdrop`: airdrop, points program, token launch
- `Layer2`: layer 2, l2, rollup, optimism, arbitrum, base
- `NFT`: nft, ordinals

## Signals

Use these as dashboard metrics or factor-mining inputs:

- `news_heat_24h`: count of deduped Web3 news items in the window.
- `risk_event_count_24h`: count of items tagged `risk_event=true`.
- `positive_news_ratio_24h`: positive item count divided by total item count.
- `asset_mention_count_24h`: map of asset symbol to mention count.
- `topic_heat_24h`: map of topic tag to count.
- `source_breadth_24h`: number of independent sources covering a topic or asset.

For historical backtests, compute these with rolling windows using publication time. Never compute a candle's feature using articles published after that candle.
