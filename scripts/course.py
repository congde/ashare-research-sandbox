"""Cross-platform task runner for the course repository."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
MIN_PYTHON = (3, 11)
MANAGED_PYTHON_VERSION = (3, 11, 9)
MANAGED_PYTHON = ROOT / ".python" / "python-3.11.9" / (
    "python.exe" if os.name == "nt" else "bin/python3.11"
)


def require_supported_python() -> None:
    if sys.version_info < MIN_PYTHON:
        version = ".".join(str(part) for part in MIN_PYTHON)
        current = ".".join(str(part) for part in sys.version_info[:3])
        raise SystemExit(
            f"Python {version}+ is required; current interpreter is Python {current}."
        )


def venv_executable(name: str) -> Path:
    directory = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return VENV / directory / f"{name}{suffix}"


def run(
    command: list[str],
    *,
    cwd: str | Path = ROOT,
    env: dict[str, str] | None = None,
) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def setup_python() -> Path:
    if MANAGED_PYTHON.is_file():
        return MANAGED_PYTHON
    require_supported_python()
    return Path(sys.executable)


def npm_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("NPM_CONFIG_CACHE", str(ROOT / ".npm-cache"))
    return env


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
    base_python = setup_python()
    venv_python = venv_executable("python")
    if not venv_python.is_file():
        run([str(base_python), "-m", "venv", str(VENV)])
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
        env = npm_env()
        if (web_dir / "package-lock.json").is_file():
            run([npm, "ci"], cwd=web_dir, env=env)
        else:
            run([npm, "install"], cwd=web_dir, env=env)
        run([npm, "run", "build"], cwd=web_dir, env=env)
    print("setup complete")


def python_task(script: str, *args: str) -> None:
    env = os.environ.copy()
    src_path = str(ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing else os.pathsep.join([src_path, existing])
    run([str(require_venv("python")), script, *args], env=env)


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
    python_task("scripts/generate_chapter13_figures.py")
    python_task("scripts/generate_chapter14_figures.py")
    python_task("scripts/generate_chapter15_figures.py")
    python_task("scripts/generate_chapter16_figures.py")
    python_task("scripts/generate_chapter17_figures.py")
    python_task("scripts/generate_chapter18_figures.py")
    python_task("scripts/generate_chapter19_figures.py")
    python_task("scripts/generate_chapter20_figures.py")
    python_task("scripts/generate_chapter21_figures.py")
    python_task("scripts/generate_chapter21_25_figures.py")
    python_task("scripts/generate_chapter26_32_figures.py")
    python_task("scripts/generate_chapter33_35_figures.py")
    python_task("scripts/generate_supplementary_diagrams.py")


TASKS = {
    "setup": setup,
    "verify": lambda: python_task("verify.py"),
    "implementation-matrix": lambda: python_task("scripts/chapter_implementation_matrix.py"),
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
    for task in ("verify", "implementation-matrix", "vendor-drift", "asset-audit", "courseware-check"):
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
