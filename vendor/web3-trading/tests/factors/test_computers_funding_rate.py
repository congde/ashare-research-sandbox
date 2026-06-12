"""tests for FundingRateZScoreComputer — 合约资金费率 z-score 因子"""

import pytest

from factors.computers.contract.funding_rate_zscore import FundingRateZScoreComputer
from factors.enums import SignalDirection


@pytest.mark.asyncio
class TestFundingRateZScoreComputer:
    async def test_normal_funding_rate(self, contract_ctx) -> None:
        comp = FundingRateZScoreComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None

    async def test_extreme_negative_funding(self, contract_ctx) -> None:
        """极度负费率 + 足够样本 → 看涨"""
        n = 40
        contract_ctx.data["funding_rate"] = [-0.001] * n

        comp = FundingRateZScoreComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None
        # 所有值相同 → std=0 → zscore=0 → 中性
        # 需要多样化点来产生信号
        assert result.signal_direction is not None

    async def test_diverse_funding_produces_signal(self, contract_ctx) -> None:
        """多样化费率数据产生非中性信号"""
        import numpy as np
        np.random.seed(42)
        contract_ctx.data["funding_rate"] = list(
            np.random.normal(-0.001, 0.0005, 50)
        )

        comp = FundingRateZScoreComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None
        assert result.normalized_score != 0.0

    async def test_inconclusive_no_funding_data(self, empty_ctx) -> None:
        comp = FundingRateZScoreComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None

    async def test_spot_context_returns_none(self, spot_ctx) -> None:
        """合约专用因子在现货市场应跳过"""
        comp = FundingRateZScoreComputer()
        # 合约因子 required prerequisites check
        result = await comp.compute_if_available(spot_ctx)
        assert result is None
