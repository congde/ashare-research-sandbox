from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def main() -> int:
    required = [
        ROOT / "product-brief.md",
        ROOT / "research-report.md",
        ROOT / "prd.md",
        ROOT / "plan.md",
        ROOT / "user-test.md",
        ROOT / "eval-rubric.md",
        ROOT / "playbook.md",
        ROOT / "data/company.json",
        ROOT / "data/prices.csv",
        ROOT / "static/index.html",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing project artifacts: {', '.join(missing)}")

    sys.path.insert(0, str(ROOT))
    from a_share.report import build_report

    report = build_report()
    encoded = json.dumps(report, ensure_ascii=False)
    for phrase in ("不构成投资建议", "不能执行交易", "maximum_drawdown_pct"):
        if phrase not in encoded:
            raise SystemExit(f"report is missing required boundary or metric: {phrase}")

    subprocess.run(
        [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q"],
        check=True,
    )
    print("A-share research sandbox is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
