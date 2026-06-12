# -*- coding: utf-8 -*-
"""测试数据质量校验。"""

import time

from unittest.mock import AsyncMock, patch

import pytest

from factors.validation import (
    CompletenessValidator,
    DataKeyReport,
    FreshnessValidator,
    QualityChecker,
    QualityLevel,
    QualityReport,
    QualityReportRecord,
    RangeValidator,
    store_quality_report,
)


class TestCompletenessValidator:
    def test_data_none(self) -> None:
        issues = CompletenessValidator().check("realtime_fund", None)
        assert len(issues) == 1
        assert issues[0].level == QualityLevel.FAIL
        assert "缺失" in issues[0].issue

    def test_data_empty_list(self) -> None:
        issues = CompletenessValidator().check("realtime_fund", [])
        assert len(issues) == 1
        assert issues[0].level == QualityLevel.WARN

    def test_data_empty_dict(self) -> None:
        issues = CompletenessValidator().check("realtime_fund", {})
        assert len(issues) == 1
        assert issues[0].level == QualityLevel.WARN

    def test_data_ok(self) -> None:
        issues = CompletenessValidator().check("realtime_fund", "some_data")
        assert len(issues) == 0


class TestFreshnessValidator:
    def test_fresh_data(self) -> None:
        v = FreshnessValidator({"test_key": 999999})
        now_ms = int(time.time() * 1000)
        issues = v.check("test_key", "data", now_ms)
        assert len(issues) == 0

    def test_stale_data(self) -> None:
        v = FreshnessValidator({"test_key": 0.001})  # 1ms threshold
        now_ms = int(time.time() * 1000)
        issues = v.check("test_key", "data", now_ms - 10_000)  # 10s old
        assert len(issues) >= 1
        assert any(i.level == QualityLevel.FAIL for i in issues)

    def test_unknown_key_no_issues(self) -> None:
        v = FreshnessValidator()
        issues = v.check("unknown_key", "data", 0)
        assert len(issues) == 0


class TestRangeValidator:
    def test_no_rules_for_key(self) -> None:
        issues = RangeValidator().check("unknown", "data")
        assert len(issues) == 0


class TestQualityChecker:
    def test_all_pass(self) -> None:
        checker = QualityChecker()
        data = {
            "realtime_fund": "valid_data",
            "token_flow": "valid_data",
        }
        report = checker.check(data, int(time.time() * 1000))
        assert report.overall == QualityLevel.PASS
        assert len(report.per_key) == 2

    def test_missing_data_causes_warn(self) -> None:
        checker = QualityChecker()
        data = {
            "realtime_fund": None,
            "token_flow": "valid_data",
        }
        report = checker.check(data, int(time.time() * 1000))
        assert report.overall in (QualityLevel.WARN, QualityLevel.FAIL)

    def test_summary_string(self) -> None:
        checker = QualityChecker()
        report = checker.check({"a": 1, "b": 2}, int(time.time() * 1000))
        assert "2 keys" in report.summary


class TestQualityReportModel:
    def test_report_construction(self) -> None:
        report = QualityReport(
            overall=QualityLevel.PASS,
            per_key={
                "a": DataKeyReport(key="a", status=QualityLevel.PASS, issues=[]),
            },
            summary="all good",
        )
        assert report.overall == QualityLevel.PASS
        assert report.summary == "all good"
        assert len(report.per_key) == 1


class TestQualityReportRecord:
    def test_record_fields(self) -> None:
        record = QualityReportRecord(
            symbol="BTC",
            vs_token_id="123",
            market_type="spot",
            overall="pass",
            summary="5 keys checked",
            per_key={},
            data_health={},
        )
        assert record.symbol == "BTC"
        assert record.overall == "pass"
        assert len(record.id) == 32

    def test_record_serializable(self) -> None:
        record = QualityReportRecord(
            symbol="ETH",
            market_type="contract",
            overall="warn",
            summary="3 keys checked, 1 failed",
            per_key={"realtime_fund": {"status": "fail", "issues": []}},
            data_health={"realtime_fund": {"status": "degraded", "success_rate": 0.8}},
        )
        d = record.model_dump()
        assert d["symbol"] == "ETH"
        assert d["overall"] == "warn"
        assert "realtime_fund" in d["per_key"]
        assert "realtime_fund" in d["data_health"]


class TestStoreQualityReport:
    @pytest.mark.asyncio
    async def test_store_success(self) -> None:
        report = QualityReport(
            overall=QualityLevel.PASS,
            per_key={
                "realtime_fund": DataKeyReport(key="realtime_fund", status=QualityLevel.PASS, issues=[]),
            },
            summary="1 keys checked",
        )
        mock_append = AsyncMock()

        with patch("factors.local_store.append_quality_report", mock_append):
            record_id = await store_quality_report(
                report, symbol="BTC", vs_token_id="123", market_type="spot",
            )

        assert record_id is not None
        assert len(record_id) == 32
        mock_append.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_failure_returns_none(self) -> None:
        report = QualityReport(
            overall=QualityLevel.WARN,
            per_key={},
            summary="0 keys checked",
        )
        mock_append = AsyncMock(side_effect=RuntimeError("disk full"))

        with patch("factors.local_store.append_quality_report", mock_append):
            record_id = await store_quality_report(report, symbol="BTC")

        assert record_id is None
