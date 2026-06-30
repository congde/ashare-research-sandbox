"""Strategy pollution checks for chapter 20 teaching demos."""

from __future__ import annotations

import math
from typing import Any

from strategy_engine.dsl import check_lookahead_bias, validate_strategy_code

SAFE_CODE = "def on_tick(ctx, candle):\n    return None"

UNSAFE_IMPORT = "import os\n\ndef on_tick(ctx, candle):\n    return os.getcwd()"

LOOKAHEAD_CODE = (
    "def on_tick(ctx, candle):\n"
    "    df = ctx.dataframe\n"
    "    future_close = df['close'].shift(-5)\n"
    "    return None"
)


def _check(label: str, code: str) -> dict[str, Any]:
    validation = validate_strategy_code(code)
    lookahead = check_lookahead_bias(code)
    return {
        "label": label,
        "dsl_valid": validation.valid,
        "dsl_errors": [
            {"rule": item.rule, "message": item.message, "line": item.line}
            for item in validation.errors
        ],
        "lookahead_clean": lookahead.clean,
        "lookahead_findings": [
            {"rule": item.rule, "message": item.message, "line": item.line}
            for item in lookahead.findings
        ],
        "backtest_ready": validation.valid and lookahead.clean,
    }


def run_pollution_checks() -> dict[str, Any]:
    """Run the three canonical pollution cases referenced in chapter 20."""
    cases = [
        _check("safe_noop", SAFE_CODE),
        _check("unsafe_import", UNSAFE_IMPORT),
        _check("lookahead_shift", LOOKAHEAD_CODE),
    ]
    return {
        "ok": True,
        "cases": cases,
        "lesson": [
            "safe_noop：DSL 与前视检查都通过，但策略不产生交易。",
            "unsafe_import：DSL 以 denied_import 拒绝，代码不能进入沙箱。",
            "lookahead_shift：DSL 通过，但前视检查以 L002 拒绝 shift(-5)。",
            "安全执行 ≠ 回测没有作弊，两类检查必须分开看。",
        ],
    }


def run_lookahead_effect_demo() -> dict[str, Any]:
    """Compare a clean lagged rule with a deliberately polluted lookahead rule.

    The clean rule can only use the prior return to decide the next position.
    The polluted rule uses the current return sign before taking the position,
    which is exactly the kind of impossible timing that lookahead checks block.
    """
    returns = [
        round(0.006 * math.sin(index / 2.7) + 0.004 * math.cos(index / 5.1), 5)
        for index in range(1, 61)
    ]
    for index, shock in {8: -0.018, 17: 0.022, 29: -0.02, 42: 0.018, 53: -0.016}.items():
        returns[index] = round(returns[index] + shock, 5)

    clean_equity = 10_000.0
    polluted_equity = 10_000.0
    curve: list[dict[str, Any]] = [{"day": 0, "clean": clean_equity, "polluted": polluted_equity}]
    clean_positions: list[int] = []
    polluted_positions: list[int] = []

    for index, daily_return in enumerate(returns):
        previous_return = returns[index - 1] if index > 0 else 0.0
        clean_position = 1 if previous_return > 0 else 0
        polluted_position = 1 if daily_return > 0 else 0
        clean_positions.append(clean_position)
        polluted_positions.append(polluted_position)
        clean_equity *= 1 + clean_position * daily_return
        polluted_equity *= 1 + polluted_position * daily_return
        curve.append(
            {
                "day": index + 1,
                "clean": round(clean_equity, 2),
                "polluted": round(polluted_equity, 2),
                "return_pct": round(daily_return * 100, 3),
                "clean_position": clean_position,
                "polluted_position": polluted_position,
            }
        )

    return {
        "ok": True,
        "curve": curve,
        "summary": {
            "clean_final_equity": round(clean_equity, 2),
            "polluted_final_equity": round(polluted_equity, 2),
            "clean_return_pct": round(clean_equity / 10_000 - 1, 4) * 100,
            "polluted_return_pct": round(polluted_equity / 10_000 - 1, 4) * 100,
            "clean_trading_days": sum(clean_positions),
            "polluted_trading_days": sum(polluted_positions),
        },
        "lesson": (
            "polluted 使用当日收益方向决定当日仓位，曲线只说明前视污染会夸大效果，"
            "不代表任何可执行策略。"
        ),
    }
