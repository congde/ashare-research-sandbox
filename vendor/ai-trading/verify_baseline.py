from __future__ import annotations

import json
from pathlib import Path
import sys


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent


def main() -> int:
    required = [
        ROOT / "LICENSE",
        ROOT / "UPSTREAM.md",
        ROOT / "app/strategy_engine/dsl/validator.py",
        ROOT / "app/strategy_engine/backtest/engine.py",
        ROOT / "app/strategy_engine/runtime/risk_manager.py",
        ROOT / "app/services/research_agent.py",
        ROOT / "web/package.json",
        ROOT / "web/src/pages/trading/BacktestsPage.tsx",
        ROOT / "web/src/pages/research/ResearchPanel.tsx",
        ROOT / "web/src/quant-atelier/tokens.css",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing ai-trading baseline files: {', '.join(missing)}")

    sys.path.insert(0, str(ROOT))
    from app.strategy_engine.dsl.validator import validate_strategy_code

    safe = validate_strategy_code("def on_tick(ctx, candle):\n    return None")
    unsafe = validate_strategy_code(
        "import os\n\ndef on_tick(ctx, candle):\n    return os.getcwd()"
    )
    if not safe.valid or unsafe.valid:
        raise SystemExit("ai-trading restricted DSL validation failed")

    package = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
    if "react" not in package.get("dependencies", {}) or "build" not in package.get(
        "scripts", {}
    ):
        raise SystemExit("ai-trading frontend package is incomplete")

    print("ai-trading DSL, strategy-engine source, and React frontend are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
