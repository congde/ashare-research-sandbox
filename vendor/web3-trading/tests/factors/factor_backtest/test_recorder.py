# -*- coding: utf-8 -*-
"""DataRecorder 及模型单元测试。"""

import uuid

from factors.backtest.models import FactorSnapshot, SourceData
from factors.enums import MarketType


class TestFactorSnapshot:
    def test_id_is_uuid(self) -> None:
        snap = FactorSnapshot(
            symbol="BTC",
            vs_token_id="12345",
        )
        assert len(snap.id) == 32
        assert uuid.UUID(snap.id)

    def test_snapshot_defaults(self) -> None:
        snap = FactorSnapshot(
            symbol="ETH",
            vs_token_id="67890",
        )
        assert snap.market_type == MarketType.SPOT
        assert snap.factor_results == []
        assert snap.aggregate_score == 0.0
        assert snap.quality_report_id == ""
        assert snap.source_data_id == ""

    def test_snapshot_serialization_roundtrip(self) -> None:
        snap = FactorSnapshot(
            symbol="BTC",
            vs_token_id="1",
            quality_report_id="qr-001",
            source_data_id="sd-001",
            factor_results=[
                {
                    "factor_name": "spot_trade_inflow",
                    "normalized_score": 0.75,
                    "confidence": 0.85,
                },
                {
                    "factor_name": "deviation",
                    "normalized_score": -0.30,
                    "confidence": 0.65,
                },
            ],
            errors=[],
        )
        data = snap.model_dump()
        restored = FactorSnapshot(**data)
        assert restored.id == snap.id
        assert restored.quality_report_id == "qr-001"
        assert restored.source_data_id == "sd-001"
        assert len(restored.factor_results) == 2
        assert restored.factor_results[0]["factor_name"] == "spot_trade_inflow"


class TestSourceData:
    def test_source_data_construction(self) -> None:
        src = SourceData(
            symbol="BTC",
            vs_token_id="1",
            data={"kline": {"close": [1.0, 2.0, 3.0]}},
        )
        assert len(src.id) == 32
        assert src.data["kline"]["close"] == [1.0, 2.0, 3.0]

    def test_source_data_id_is_unique(self) -> None:
        src1 = SourceData(symbol="BTC", vs_token_id="1")
        src2 = SourceData(symbol="BTC", vs_token_id="1")
        assert src1.id != src2.id
