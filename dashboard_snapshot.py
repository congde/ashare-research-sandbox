from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from config.env import load_env  # noqa: E402
from dashboard.refresh import refresh_all  # noqa: E402


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Refresh dashboard snapshots for offline use.")
    parser.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "live", "offline"],
        help="Force data mode during refresh (default: auto, tries live APIs first).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch payloads without writing snapshot files.",
    )
    args = parser.parse_args()
    load_env()
    result = refresh_all(save=not args.dry_run, data_mode=args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
