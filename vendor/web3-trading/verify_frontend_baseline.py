from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent


def main() -> int:
    required = [
        ROOT / "src/web/static/dashboard.js",
        ROOT / "src/web/static/dashboard.css",
        ROOT / "src/web/static/dashboard-vs.js",
        ROOT / "src/web/static/dashboard-dex.js",
        ROOT / "src/web/static/dashboard-data-sources.js",
        ROOT / "src/web/static/theme.js",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing web3-trading frontend baseline files: {', '.join(missing)}")

    dashboard = (ROOT / "src/web/static/dashboard.js").read_text(encoding="utf-8")
    if "opportunity" not in dashboard.lower():
        raise SystemExit("web3-trading dashboard.js baseline looks incomplete")

    print("web3-trading Jinja dashboard static baselines are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
