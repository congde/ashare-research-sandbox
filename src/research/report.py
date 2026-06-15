from __future__ import annotations

from backtest.runner import load_prices, run_backtest
from paths import DATA_DIR
from research.summary import build_research_summary, load_company
from risk.config import DEFAULT_RULE_IDS
from risk.simulation import evaluate_backtest_risk


def build_report(short: int = 3, long: int = 7) -> dict:
    asset = load_company(DATA_DIR / "company.json")
    prices = load_prices(DATA_DIR / "prices.csv")
    backtest = run_backtest(prices, short=short, long=long)
    return {
        "research": build_research_summary(asset),
        "backtest": backtest,
        "risk_checks": evaluate_backtest_risk(backtest),
        "fusion": {
            "product_shape": "web3-trading",
            "dsl_and_risk": "ai-trading",
            "adapted_modules": [
                "web3-trading/backtest/metrics.py",
                "ai-trading/strategy_engine/backtest/engine.py",
                "ai-trading/strategy_engine/dsl",
                "ai-trading/strategy_engine/runtime/risk_manager.py",
            ],
            "risk_rules": list(DEFAULT_RULE_IDS),
        },
        "warnings": [
            "教学项目，不构成投资建议。",
            "仅使用虚构 Web3 资产与固定离线历史样本。",
            "项目不连接交易所账户，也不能执行交易。",
        ],
    }
