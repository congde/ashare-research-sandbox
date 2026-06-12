from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from research.report import build_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print the Web3 sandbox report as JSON or a short summary."
    )
    parser.add_argument("--short", type=int, default=3, help="Short MA window")
    parser.add_argument("--long", type=int, default=7, help="Long MA window")
    parser.add_argument(
        "--format",
        choices=("summary", "json"),
        default="summary",
        help="Output format",
    )
    args = parser.parse_args()

    try:
        report = build_report(short=args.short, long=args.long)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    research = report["research"]
    metrics = report["backtest"]["metrics"]
    print(research["company"])
    print("warnings:", " · ".join(report["warnings"]))
    print(
        "strategy_return_pct={strategy_return_pct}% "
        "buy_hold_return_pct={buy_hold_return_pct}% "
        "maximum_drawdown_pct={maximum_drawdown_pct}% "
        "trade_count={trade_count}".format(**metrics)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
