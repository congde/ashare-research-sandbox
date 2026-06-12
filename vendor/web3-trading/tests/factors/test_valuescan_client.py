"""tests for ValueScanClient — real API calls (.env credentials required).

使用 .env 中的 VS_OPEN_API_KEY / VS_OPEN_SECRET_KEY 调用真实 ValueScan API。
如果凭证缺失，测试自动 skip。
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

# Load .env once at module level
_ENV_LOADED = False


def _ensure_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
    _ENV_LOADED = True


def _get_env(key: str) -> str:
    _ensure_env()
    val = os.environ.get(key, "")
    if not val:
        pytest.skip(f"env missing: {key}")
    return val


def _make_client() -> "ValueScanClient":
    from libs.valuescan.client import ValueScanClient

    return ValueScanClient.from_env()


# Pre-resolve BTC token for all tests
@pytest.fixture(scope="module")
def btc_token_id() -> str:
    """Resolve BTC once for the module, returns vs_token_id."""
    import asyncio

    async def _resolve():
        client = _make_client()
        try:
            vs_id, coin_key = await client.resolve_symbol("BTC")
            assert vs_id is not None, "BTC token not found"
            return vs_id
        finally:
            await client.close()

    return asyncio.run(_resolve())


# ===================================================================
# Token resolution
# ===================================================================

@pytest.mark.asyncio
class TestTokenResolution:
    async def test_search_btc_returns_results(self) -> None:
        client = _make_client()
        try:
            tokens = await client.search_token("BTC")
            assert len(tokens) > 0
            btc = next((t for t in tokens if t.symbol.upper() == "BTC"), None)
            assert btc is not None
            assert btc.id
        finally:
            await client.close()

    async def test_resolve_symbol_btc(self) -> None:
        client = _make_client()
        try:
            vs_id, coin_key = await client.resolve_symbol("BTC")
            assert vs_id is not None
            assert vs_id != ""
            assert coin_key != ""  # BTC should have a coin_key
        finally:
            await client.close()

    async def test_resolve_symbol_eth(self) -> None:
        client = _make_client()
        try:
            vs_id, coin_key = await client.resolve_symbol("ETH")
            assert vs_id is not None
            assert vs_id != ""
        finally:
            await client.close()

    async def test_resolve_unknown_returns_none(self) -> None:
        client = _make_client()
        try:
            vs_id, coin_key = await client.resolve_symbol("NONEXISTENT_TOKEN_XYZ123")
            assert vs_id is None
            assert coin_key == ""
        finally:
            await client.close()

    async def test_get_token_detail(self, btc_token_id) -> None:
        client = _make_client()
        try:
            detail = await client.get_token_detail(btc_token_id)
            assert detail is not None
            assert detail.symbol == "BTC"
            assert len(detail.chain_addresses) > 0
        finally:
            await client.close()

    async def test_get_coin_key(self, btc_token_id) -> None:
        client = _make_client()
        try:
            coin_key = await client.get_coin_key(btc_token_id)
            assert coin_key != ""
        finally:
            await client.close()


# ===================================================================
# Fund data
# ===================================================================

@pytest.mark.asyncio
class TestFundData:
    async def test_get_realtime_fund(self, btc_token_id) -> None:
        client = _make_client()
        try:
            fund = await client.get_realtime_fund(btc_token_id)
            assert fund is not None
            assert fund.vs_token_id == btc_token_id
            assert fund.symbol == "BTC"
            assert len(fund.spot_goods_list) > 0
            # spot goods list items have expected fields
            item = fund.spot_goods_list[0]
            assert item.time_particle_enum > 0
        finally:
            await client.close()

    async def test_get_token_flow(self, btc_token_id) -> None:
        client = _make_client()
        try:
            flow = await client.get_token_flow(btc_token_id)
            assert flow is not None
            assert flow.symbol == "BTC"
            assert len(flow.items) > 0
        finally:
            await client.close()

    async def test_get_fund_snapshot(self, btc_token_id) -> None:
        client = _make_client()
        try:
            import time
            snap = await client.get_fund_snapshot(btc_token_id, date_ms=int(time.time() * 1000) - 7 * 86400000)
            assert snap is not None
            assert snap.symbol == "BTC"
        finally:
            await client.close()

    async def test_get_fund_market_cap_ratio(self, btc_token_id) -> None:
        client = _make_client()
        try:
            ratio = await client.get_fund_market_cap_ratio(btc_token_id)
            assert ratio is not None
            assert ratio.symbol == "BTC"
        finally:
            await client.close()


# ===================================================================
# Whale cost
# ===================================================================

@pytest.mark.asyncio
class TestWhaleCost:
    async def test_get_whale_cost(self, btc_token_id) -> None:
        client = _make_client()
        try:
            costs = await client.get_whale_cost(btc_token_id, days=7)
            assert len(costs) > 0
            item = costs[0]
            assert item.symbol == "BTC"
            assert item.price > 0
            assert item.cost > 0
            assert item.balance > 0
        finally:
            await client.close()

    async def test_whale_cost_returns_chronological(self, btc_token_id) -> None:
        client = _make_client()
        try:
            costs = await client.get_whale_cost(btc_token_id, days=7)
            dates = [c.date for c in costs]
            assert dates == sorted(dates), "whale cost should be chronological"
        finally:
            await client.close()


# ===================================================================
# Market indicators
# ===================================================================

@pytest.mark.asyncio
class TestMarketIndicators:
    async def test_get_price_indicators(self, btc_token_id) -> None:
        client = _make_client()
        try:
            indicators = await client.get_price_indicators(btc_token_id, days=7)
            if indicators:  # only BTC/ETH have this data
                item = indicators[0]
                assert item.symbol == "BTC"
        finally:
            await client.close()

    async def test_get_social_sentiment(self, btc_token_id) -> None:
        client = _make_client()
        try:
            sentiment = await client.get_social_sentiment(btc_token_id)
            assert sentiment is not None
            assert sentiment.symbol == "BTC"
            # bullish_ratio + bearish_ratio + neutral_ratio should be ~1.0
            total = sentiment.bullish_ratio + sentiment.bearish_ratio + sentiment.neutral_ratio
            assert 0.9 <= total <= 1.1, f"sentiment ratios sum to {total}"
        finally:
            await client.close()


# ===================================================================
# On-chain data
# ===================================================================

@pytest.mark.asyncio
class TestOnChainData:
    async def test_get_large_transactions(self, btc_token_id) -> None:
        client = _make_client()
        try:
            txs = await client.get_large_transactions(btc_token_id)
            # may be empty or have items
            for tx in txs:
                assert tx.symbol == "BTC"
                assert tx.amount > 0
        finally:
            await client.close()

    async def test_get_holder_list(self, btc_token_id) -> None:
        client = _make_client()
        try:
            holders = await client.get_holder_list(btc_token_id, page_size=5)
            for h in holders:
                assert h.symbol == "BTC"
                assert h.balance >= 0
        finally:
            await client.close()


# ===================================================================
# AI coin lists
# ===================================================================

@pytest.mark.asyncio
class TestAICoinLists:
    async def test_get_chance_coin_list(self) -> None:
        client = _make_client()
        try:
            coins = await client.get_chance_coin_list()
            assert len(coins) > 0
            for c in coins:
                assert c.vs_token_id
                assert c.symbol
                assert 0 <= c.score <= 100
        finally:
            await client.close()

    async def test_get_risk_coin_list(self) -> None:
        client = _make_client()
        try:
            coins = await client.get_risk_coin_list()
            assert len(coins) > 0
            for c in coins:
                assert c.vs_token_id
                assert c.symbol
        finally:
            await client.close()

    async def test_get_funds_coin_list(self) -> None:
        client = _make_client()
        try:
            coins = await client.get_funds_coin_list()
            assert len(coins) > 0
            for c in coins:
                assert c.vs_token_id
                assert c.symbol
        finally:
            await client.close()


# ===================================================================
# Sector data
# ===================================================================

@pytest.mark.asyncio
class TestSectorData:
    async def test_get_sector_fund_list_spot(self) -> None:
        client = _make_client()
        try:
            sectors = await client.get_sector_fund_list(trade_type=1)
            assert len(sectors) > 0
            for s in sectors:
                assert s.tag != "" or s.tags_simplified != ""
        finally:
            await client.close()

    async def test_get_sector_fund_list_contract(self) -> None:
        client = _make_client()
        try:
            sectors = await client.get_sector_fund_list(trade_type=2)
            assert len(sectors) > 0
        finally:
            await client.close()

    async def test_get_sector_coin_trade_list(self) -> None:
        client = _make_client()
        try:
            # Get first tag from sector fund list
            sectors = await client.get_sector_fund_list(trade_type=1)
            if sectors and sectors[0].tag:
                coins = await client.get_sector_coin_trade_list(sectors[0].tag, trade_type=1)
                assert len(coins) > 0
                for c in coins:
                    assert c.symbol
                    assert c.vs_token_id
        finally:
            await client.close()
