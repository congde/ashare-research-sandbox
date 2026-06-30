"""Restricted Python DSL for user / LLM-generated strategies.

Per ADR-0007.
"""

from strategy_engine.dsl.lookahead import (
    LookaheadFinding,
    LookaheadReport,
    check_lookahead_bias,
)
from strategy_engine.dsl.loader import StrategyCompileError, compile_strategy
from strategy_engine.dsl.validator import (
    ValidationError,
    ValidationResult,
    validate_strategy_code,
)

__all__ = [
    "LookaheadFinding",
    "LookaheadReport",
    "StrategyCompileError",
    "ValidationError",
    "ValidationResult",
    "check_lookahead_bias",
    "compile_strategy",
    "validate_strategy_code",
]
