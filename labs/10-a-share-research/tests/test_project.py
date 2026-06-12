from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from a_share.backtest import load_prices, run_backtest  # noqa: E402
from a_share.report import build_report  # noqa: E402


def test_report_has_traceable_research_and_safety_boundary() -> None:
    report = build_report()
    assert report["research"]["facts"][0]["source_id"] == "S1"
    assert len(report["research"]["sources"]) >= 3
    assert any("不构成投资建议" in warning for warning in report["warnings"])
    assert any("不能执行交易" in warning for warning in report["warnings"])


def test_backtest_is_deterministic_and_reports_risk() -> None:
    report = build_report(short=3, long=7)
    metrics = report["backtest"]["metrics"]
    assert metrics["trade_count"] > 0
    assert metrics["final_equity"] > 0
    assert metrics["maximum_drawdown_pct"] <= 0
    assert len(report["backtest"]["curve"]) == 35


def test_invalid_windows_are_rejected() -> None:
    prices = load_prices(ROOT / "data/prices.csv")
    with pytest.raises(ValueError, match="short < long"):
        run_backtest(prices, short=7, long=3)


def test_research_report_exists() -> None:
    report_path = ROOT / "research-report.md"
    text = report_path.read_text(encoding="utf-8")
    assert "Facts" in text
    assert "web3-trading" in text

