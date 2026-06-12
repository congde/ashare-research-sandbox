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


TASKS = {
    "setup": setup,
    "verify": lambda: python_task("verify.py"),
    "snapshot": lambda: python_task("dashboard_snapshot.py"),
    "courseware-check": lambda: python_task("scripts/verify_courseware.py"),
    "lab-10": lambda: python_task("verify.py"),
}


def check() -> None:
    for task in ("verify", "courseware-check"):
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
