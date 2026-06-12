"""Example strategies in ``examples/strategies/`` MUST pass the
DSL validator. This guards against regressions where a tutorial
strategy accidentally drifts off the safe-list.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.strategy_engine.dsl import validate_strategy_code

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLES_DIR = REPO_ROOT / "examples" / "strategies"


@pytest.mark.parametrize(
    "example_file", sorted(EXAMPLES_DIR.glob("*.py")), ids=lambda p: p.name
)
def test_example_strategy_passes_dsl_validator(example_file: Path) -> None:
    code = example_file.read_text()
    result = validate_strategy_code(code)
    assert result.valid, (
        f"{example_file.name} failed DSL validation: "
        + ", ".join(f"L{e.line} {e.rule}" for e in result.errors)
    )
    assert result.ast_hash
