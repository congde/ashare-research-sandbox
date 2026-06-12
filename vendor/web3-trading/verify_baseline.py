from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent


def main() -> int:
    required = [
        ROOT / "UPSTREAM.md",
        ROOT / "conf/default.yaml",
        ROOT / "src/backtest/metrics.py",
        ROOT / "src/backtest/engine.py",
        ROOT / "src/web/api/dashboard_api.py",
        ROOT / "src/web/api/dashboard_service.py",
        ROOT / "src/web/api/valuescan_service.py",
        ROOT / "src/web/api/dexscan_service.py",
        ROOT / "src/web/api/opportunity_scanner.py",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing web3-trading baseline files: {', '.join(missing)}")

    metrics = (ROOT / "src/backtest/metrics.py").read_text(encoding="utf-8")
    for symbol in ("compute_calmar", "compute_sharpe"):
        if symbol not in metrics:
            raise SystemExit(f"web3-trading metrics baseline missing {symbol}")

    print("web3-trading backtest and dashboard API baselines are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
