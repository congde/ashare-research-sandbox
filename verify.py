from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "src" / "web"


def npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def build_frontend() -> None:
    if not (WEB_DIR / "package.json").is_file():
        raise SystemExit("missing React frontend: src/web/package.json")
    npm = npm_command()
    if (WEB_DIR / "package-lock.json").is_file():
        subprocess.run([npm, "ci"], cwd=WEB_DIR, check=True)
    else:
        subprocess.run([npm, "install"], cwd=WEB_DIR, check=True)
    subprocess.run([npm, "run", "build"], cwd=WEB_DIR, check=True)


def main() -> int:
    build_frontend()
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
        ROOT / "src/web/static/index.html",
        ROOT / "vendor/web3-trading/UPSTREAM.md",
        ROOT / "vendor/web3-trading/verify_baseline.py",
        ROOT / "vendor/web3-trading/verify_frontend_baseline.py",
        ROOT / "vendor/ai-trading/UPSTREAM.md",
        ROOT / "vendor/ai-trading/verify_baseline.py",
        ROOT / "vendor/FUSION.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing project artifacts: {', '.join(missing)}")

    sys.path.insert(0, str(ROOT / "src"))
    from research.report import build_report

    report = build_report()
    encoded = json.dumps(report, ensure_ascii=False)
    for phrase in (
        "不构成投资建议",
        "不能执行交易",
        "maximum_drawdown_pct",
        "calmar_ratio",
        "sharpe_ratio",
        "risk_checks",
        "ai-trading/event-driven",
        "web3-trading",
        "ai-trading",
    ):
        if phrase not in encoded:
            raise SystemExit(f"report is missing required boundary or metric: {phrase}")

    subprocess.run(
        [sys.executable, str(ROOT / "vendor/web3-trading/verify_baseline.py")],
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "vendor/web3-trading/verify_frontend_baseline.py")],
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "vendor/ai-trading/verify_baseline.py")],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q"],
        check=True,
    )
    print("Web3 research sandbox is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
