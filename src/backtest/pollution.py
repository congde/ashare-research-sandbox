"""Strategy pollution checks for chapter 20 teaching demos."""

from __future__ import annotations

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
