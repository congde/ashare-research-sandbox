from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from config.env import load_env  # noqa: E402
from dashboard.fixture_builder import (  # noqa: E402
    rebuild_incomplete_fixtures,
    refresh_manifest_from_disk,
    sync_all_fixtures_from_snapshots,
)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build or sync dashboard teaching fixtures.")
    parser.add_argument(
        "--sync-all",
        action="store_true",
        help="Copy all complete snapshots into data/dashboard/*.json fixtures.",
    )
    args = parser.parse_args()

    load_env()
    derived = rebuild_incomplete_fixtures()
    synced = sync_all_fixtures_from_snapshots() if args.sync_all else []
    manifest = refresh_manifest_from_disk()
    payload = {"ok": True, "derived": derived, "synced": synced, "manifest": manifest}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
