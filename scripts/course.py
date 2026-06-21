"""Cross-platform task runner for the course repository."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"


def venv_executable(name: str) -> Path:
    directory = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return VENV / directory / f"{name}{suffix}"


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def require_venv(name: str) -> Path:
    executable = venv_executable(name)
    if not executable.is_file():
        raise SystemExit(
            "Virtual environment is missing. Run:\n"
            "  Windows PowerShell: py scripts/course.py setup\n"
            "                      (use python instead of py if needed)\n"
            "  macOS/Linux:        make setup"
        )
    return executable


def setup() -> None:
    venv_python = venv_executable("python")
    if not venv_python.is_file():
        run([sys.executable, "-m", "venv", str(VENV)])
    else:
        print("virtual environment already exists; updating dependencies", flush=True)
    run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "-q",
            "-r",
            "requirements.txt",
        ]
    )
    web_dir = ROOT / "src" / "web"
    if (web_dir / "package.json").is_file():
        npm = "npm.cmd" if os.name == "nt" else "npm"
        if (web_dir / "package-lock.json").is_file():
            run([npm, "ci"], cwd=str(web_dir))
        else:
            run([npm, "install"], cwd=str(web_dir))
        run([npm, "run", "build"], cwd=str(web_dir))
    print("setup complete")


def python_task(script: str, *args: str) -> None:
    run([str(require_venv("python")), script, *args])


def save_offline_data() -> None:
    python_task("dashboard_snapshot.py", "--mode", "auto")
    python_task("scripts/build_dashboard_fixtures.py", "--sync-all")


def courseware_headings() -> None:
    python_task("scripts/restructure_chapter_headings.py")
    python_task("scripts/add_chapter_heading_transitions.py")


def print_figures() -> None:
    python_task("scripts/generate_qbot_teaching_plots.py")
    python_task("scripts/generate_chapter01_figures.py")
    python_task("scripts/generate_chapter03_figures.py")
    python_task("scripts/generate_chapter05_curve.py")
    python_task("scripts/generate_chapter05_10_figures.py")
    python_task("scripts/generate_chapter06_figures.py")
    python_task("scripts/generate_chapter06_curve.py")
    python_task("scripts/generate_chapter07_snapshot_curve.py")
    python_task("scripts/generate_chapter08_figures.py")
    python_task("scripts/generate_chapter09_figures.py")
    python_task("scripts/generate_chapter10_figures.py")
    python_task("scripts/generate_chapter11_figures.py")
    python_task("scripts/generate_chapter12_figures.py")
    python_task("scripts/generate_supplementary_diagrams.py")


TASKS = {
    "setup": setup,
    "verify": lambda: python_task("verify.py"),
    "snapshot": lambda: python_task("dashboard_snapshot.py"),
    "build-fixtures": lambda: python_task("scripts/build_dashboard_fixtures.py"),
    "sync-fixtures": lambda: python_task("scripts/build_dashboard_fixtures.py", "--sync-all"),
    "save-offline-data": save_offline_data,
    "courseware-check": lambda: python_task("scripts/verify_courseware.py"),
    "courseware-headings": courseware_headings,
    "asset-audit": lambda: python_task("scripts/audit_assets.py"),
    "vendor-drift": lambda: python_task("scripts/check_vendor_drift.py"),
    "teaching-plots": print_figures,
    "print-figures": print_figures,
    "lab-10": lambda: python_task("verify.py"),
}


def check() -> None:
    for task in ("verify", "vendor-drift", "asset-audit", "courseware-check"):
        print(f"==> {task}", flush=True)
        TASKS[task]()
    print("All repository checks passed.")


TASKS["check"] = check


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in TASKS:
        choices = " | ".join(TASKS)
        print(f"usage: {Path(sys.argv[0]).name} [{choices}]")
        return 2
    TASKS[sys.argv[1]]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
