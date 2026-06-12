from __future__ import annotations

from pathlib import Path

from .backtest import load_prices, run_backtest
from .research import build_research_summary, load_company


ROOT = Path(__file__).resolve().parents[1]


def build_report(short: int = 3, long: int = 7) -> dict:
    company = load_company(ROOT / "data/company.json")
    prices = load_prices(ROOT / "data/prices.csv")
    return {
        "research": build_research_summary(company),
        "backtest": run_backtest(prices, short=short, long=long),
        "warnings": [
            "教学项目，不构成投资建议。",
            "仅使用虚构标的与固定历史样本。",
            "项目不连接证券账户，也不能执行交易。",
        ],
    }

