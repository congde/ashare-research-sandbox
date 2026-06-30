"""Rename mis-cased market intel PNG to match chapter references."""
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "docs" / "v2" / "assets"
CANONICAL = "市场情报-K线分析.png"

for path in ASSETS.glob("*.png"):
    if path.name.lower() == CANONICAL.lower() and path.name != CANONICAL:
        target = ASSETS / CANONICAL
        if target.exists() and target != path:
            print(f"skip: {CANONICAL} already exists")
        else:
            path.rename(target)
            print(f"renamed {path.name!r} -> {CANONICAL!r}")
