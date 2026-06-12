# -*- coding: utf-8 -*-
"""Reporter 单元测试。"""

from factors.backtest.models import BacktestReport, EvalMetrics
from factors.backtest.reporter import Reporter


class TestReporter:
    def test_generate_empty_report(self) -> None:
        report = BacktestReport()
        reporter = Reporter()
        output = reporter.generate(report)
        assert "# 因子回测报告" in output
        assert "暂无因子数据" in output

    def test_generate_with_metrics(self) -> None:
        metrics = [
            EvalMetrics(
                factor_name="alpha", category="AI_COMPOSITE", horizon="4h",
                ic_mean=0.15, ic_std=0.08, ir=1.875, hit_rate=0.65,
                sample_count=30, signal_distribution={"bullish": 18, "bearish": 12},
            ),
            EvalMetrics(
                factor_name="fomo", category="AI_COMPOSITE", horizon="1h",
                ic_mean=-0.05, ic_std=0.10, ir=-0.5, hit_rate=0.45,
                sample_count=25, signal_distribution={"bullish": 10, "bearish": 15},
            ),
        ]
        report = BacktestReport(
            per_factor=metrics,
            top_factors_by_ic=["alpha", "fomo"],
            top_factors_by_ir=["alpha", "fomo"],
        )
        reporter = Reporter()
        output = reporter.generate(report)
        assert "alpha" in output
        assert "fomo" in output
        assert "0.1500" in output
        assert "65.00%" in output
        assert "AI_COMPOSITE" in output
        assert "因子绩效排名" in output

    def test_generate_includes_category_summary(self) -> None:
        metrics = [
            EvalMetrics(factor_name="a", category="FUND_FLOW", horizon="1h",
                        ic_mean=0.1, ic_std=0.05, ir=2.0, hit_rate=0.6, sample_count=20),
        ]
        report = BacktestReport(
            per_factor=metrics,
            per_category=[{"category": "FUND_FLOW", "factor_count": 1, "avg_ic_mean": 0.1, "avg_ir": 2.0, "avg_hit_rate": 0.6}],
        )
        reporter = Reporter()
        output = reporter.generate(report)
        assert "分类别汇总" in output
        assert "FUND_FLOW" in output
