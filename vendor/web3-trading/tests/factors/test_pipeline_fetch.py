"""tests for FactorPipeline source data fetching — real API calls.

使用真实 ValueScanClient + KuCoinClient 测试 Pipeline 的数据拉取层。
需要 .env 中的 VS_OPEN_API_KEY / VS_OPEN_SECRET_KEY。
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from factors.config import PipelineConfig
from factors.enums import MarketType
from factors.models import DerivativesSnapshot, FundingRateData, KlineSnapshot, OpenInterestData
from factors.pipeline import FactorPipeline
from libs.kucoin_openapi import KuCoinClient

# ---------------------------------------------------------------------------
# .env loading
# ---------------------------------------------------------------------------

_ENV_LOADED = False


def _ensure_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
    _ENV_LOADED = True


def _make_vs_client() -> "ValueScanClient":
    from libs.valuescan.client import ValueScanClient

    _ensure_env()
    api_key = os.environ.get("VS_OPEN_API_KEY", "")
    secret_key = os.environ.get("VS_OPEN_SECRET_KEY", "")
    if not api_key or not secret_key:
        pytest.skip("ValueScan credentials not configured in .env")

    return ValueScanClient(
        api_key=api_key,
        secret_key=secret_key,
        base_url=os.environ.get("VS_OPEN_API_BASE_URL", "https://api-beta.valuescan.io/api"),
        timeout=20,
    )


def _make_kucoin_client() -> KuCoinClient:
    return KuCoinClient(timeout=15)


# ===================================================================
# _fetch_context — core data fetching
# ===================================================================

@pytest.mark.asyncio
class TestFetchContext:
    async def test_resolves_symbol_and_fetches_all_data(self) -> None:
        vs = _make_vs_client()
        kc = _make_kucoin_client()
        try:
            pipeline = FactorPipeline(vs, PipelineConfig.for_spot(), kucoin=kc)
            ctx = await pipeline._fetch_context("BTC")
            assert ctx is not None
            assert ctx.vs_token_id != ""
            assert ctx.symbol == "BTC"
            assert ctx.coin_key != ""
            assert ctx.current_price > 0
            assert ctx.market_type == MarketType.SPOT
        finally:
            await vs.close()
            await kc.close()

    async def test_data_keys_present(self) -> None:
        vs = _make_vs_client()
        try:
            pipeline = FactorPipeline(vs, PipelineConfig.for_spot(), kucoin=None)
            ctx = await pipeline._fetch_context("BTC")
            assert ctx is not None
            expected_keys = [
                "realtime_fund", "token_flow", "fund_snapshot",
                "market_cap_ratio", "whale_cost", "social_sentiment",
                "price_indicators", "large_transactions", "holder_list",
                "ai_chance", "ai_risk", "ai_funds",
            ]
            # AI coin keys may be None if BTC not currently in AI lists
            always_present = [
                "realtime_fund", "token_flow", "fund_snapshot",
                "market_cap_ratio", "whale_cost", "social_sentiment",
                "price_indicators",
            ]
            for key in expected_keys:
                assert key in ctx.data, f"Missing key: {key}"
            for key in always_present:
                assert ctx.data[key] is not None, f"Key {key} is None"
        finally:
            await vs.close()

    async def test_has_spot_true(self) -> None:
        vs = _make_vs_client()
        try:
            pipeline = FactorPipeline(vs, PipelineConfig.for_spot(), kucoin=None)
            ctx = await pipeline._fetch_context("BTC")
            assert ctx is not None
            assert ctx.has_spot is True
        finally:
            await vs.close()

    async def test_resolve_failure_returns_none(self) -> None:
        vs = _make_vs_client()
        try:
            pipeline = FactorPipeline(vs, PipelineConfig.for_spot(), kucoin=None)
            ctx = await pipeline._fetch_context("NONEXISTENT_TOKEN_XYZ999")
            assert ctx is None
        finally:
            await vs.close()


# ===================================================================
# _fetch_context — with KuCoin (K-line + derivatives)
# ===================================================================

@pytest.mark.asyncio
class TestFetchContextWithKuCoin:
    async def test_spot_gets_kline_snapshot(self) -> None:
        vs = _make_vs_client()
        kc = _make_kucoin_client()
        try:
            pipeline = FactorPipeline(vs, PipelineConfig.for_spot(), kucoin=kc)
            ctx = await pipeline._fetch_context("BTC")
            assert ctx is not None
            assert "kline" in ctx.data
            kline = ctx.data["kline"]
            assert isinstance(kline, KlineSnapshot)
            assert not kline.is_empty
            assert kline.tf_1h is not None
            assert kline.tf_1d is not None
        finally:
            await vs.close()
            await kc.close()

    async def test_contract_gets_kline_and_derivatives(self) -> None:
        vs = _make_vs_client()
        kc = _make_kucoin_client()
        try:
            pipeline = FactorPipeline(vs, PipelineConfig.for_contract(), kucoin=kc)
            ctx = await pipeline._fetch_context("BTC")
            assert ctx is not None
            assert "kline" in ctx.data
            assert "funding_rate" in ctx.data
            assert "open_interest" in ctx.data
            assert isinstance(ctx.data["funding_rate"], FundingRateData)
            assert isinstance(ctx.data["open_interest"], OpenInterestData)
            assert ctx.data["funding_rate"].current is not None
            assert ctx.data["open_interest"].current is not None
        finally:
            await vs.close()
            await kc.close()


# ===================================================================
# _extract_price
# ===================================================================

class TestExtractPrice:
    def test_empty_list_returns_zero(self) -> None:
        assert FactorPipeline._extract_price([]) == 0.0

    def test_none_returns_zero(self) -> None:
        assert FactorPipeline._extract_price(None) == 0.0

    @pytest.mark.asyncio
    async def test_extracts_valid_price_from_real_data(self) -> None:
        vs = _make_vs_client()
        try:
            pipeline = FactorPipeline(vs, PipelineConfig.for_spot(), kucoin=None)
            ctx = await pipeline._fetch_context("BTC")
            assert ctx is not None
            assert ctx.current_price > 0
        finally:
            await vs.close()


# ===================================================================
# _to_futures_symbol
# ===================================================================

class TestToFuturesSymbol:
    def test_btc_maps_to_xbt(self) -> None:
        assert FactorPipeline._to_futures_symbol("BTC") == "XBTUSDTM"

    def test_other_symbol(self) -> None:
        assert FactorPipeline._to_futures_symbol("ETH") == "ETHUSDTM"
        assert FactorPipeline._to_futures_symbol("SOL") == "SOLUSDTM"


# ===================================================================
# _fetch_kline_data
# ===================================================================

@pytest.mark.asyncio
class TestFetchKlineData:
    async def test_spot_returns_snapshot(self) -> None:
        kc = _make_kucoin_client()
        try:
            pipeline = FactorPipeline(None, PipelineConfig.for_spot(), kucoin=kc)  # type: ignore
            snapshot = await pipeline._fetch_kline_data("BTC", MarketType.SPOT)
            assert isinstance(snapshot, KlineSnapshot)
            assert not snapshot.is_empty
            assert snapshot.tf_1h is not None
            assert snapshot.tf_1d is not None
        finally:
            await kc.close()

    async def test_contract_returns_snapshot(self) -> None:
        kc = _make_kucoin_client()
        try:
            pipeline = FactorPipeline(None, PipelineConfig.for_contract(), kucoin=kc)  # type: ignore
            snapshot = await pipeline._fetch_kline_data("BTC", MarketType.CONTRACT)
            assert isinstance(snapshot, KlineSnapshot)
            assert not snapshot.is_empty
        finally:
            await kc.close()

    async def test_all_four_timeframes(self) -> None:
        kc = _make_kucoin_client()
        try:
            pipeline = FactorPipeline(None, PipelineConfig.for_spot(), kucoin=kc)  # type: ignore
            snapshot = await pipeline._fetch_kline_data("BTC", MarketType.SPOT)
            assert snapshot.tf_15m is not None
            assert snapshot.tf_1h is not None
            assert snapshot.tf_4h is not None
            assert snapshot.tf_1d is not None
        finally:
            await kc.close()


# ===================================================================
# _fetch_derivatives_data
# ===================================================================

@pytest.mark.asyncio
class TestFetchDerivativesData:
    async def test_returns_derivatives_snapshot(self) -> None:
        kc = _make_kucoin_client()
        try:
            pipeline = FactorPipeline(None, PipelineConfig.for_contract(), kucoin=kc)  # type: ignore
            snap = await pipeline._fetch_derivatives_data("BTC")
            assert isinstance(snap, DerivativesSnapshot)
            assert snap.funding_rate is not None
            assert snap.open_interest is not None
            assert len(snap.funding_rate.values) > 0
            assert snap.funding_rate.current is not None
            assert snap.open_interest.current is not None
        finally:
            await kc.close()


# ===================================================================
# compute_all — end-to-end (fetch + compute)
# ===================================================================

@pytest.mark.asyncio
class TestComputeAll:
    async def test_spot_pipeline_produces_bundle(self) -> None:
        vs = _make_vs_client()
        kc = _make_kucoin_client()
        try:
            pipeline = FactorPipeline(vs, PipelineConfig.for_spot(), kucoin=kc)
            bundle = await pipeline.compute_all("BTC")
            assert bundle.vs_token_id != ""
            assert bundle.symbol == "BTC"
            assert bundle.context is not None
            assert len(bundle.tier1_results) + len(bundle.tier2_results) > 0
        finally:
            await vs.close()
            await kc.close()

    async def test_contract_pipeline_produces_bundle(self) -> None:
        vs = _make_vs_client()
        kc = _make_kucoin_client()
        try:
            pipeline = FactorPipeline(vs, PipelineConfig.for_contract(), kucoin=kc)
            bundle = await pipeline.compute_all("BTC")
            assert bundle.vs_token_id != ""
            assert bundle.symbol == "BTC"
            assert bundle.context is not None
        finally:
            await vs.close()
            await kc.close()

    async def test_resolve_failure_returns_error_bundle(self) -> None:
        vs = _make_vs_client()
        try:
            pipeline = FactorPipeline(vs, PipelineConfig.for_spot(), kucoin=None)
            bundle = await pipeline.compute_all("NONEXISTENT_TOKEN_XYZ999")
            assert len(bundle.errors) > 0
            assert bundle.context is None
        finally:
            await vs.close()

    async def test_compute_single_factor(self) -> None:
        vs = _make_vs_client()
        try:
            pipeline = FactorPipeline(vs, PipelineConfig.for_spot(), kucoin=None)
            result = await pipeline.compute_single("BTC", "deviation")
            assert result is not None
            assert result.factor_name == "deviation"
        finally:
            await vs.close()

    async def test_compute_single_unknown_factor_returns_none(self) -> None:
        vs = _make_vs_client()
        try:
            pipeline = FactorPipeline(vs, PipelineConfig.for_spot(), kucoin=None)
            result = await pipeline.compute_single("BTC", "nonexistent_factor")
            assert result is None
        finally:
            await vs.close()
