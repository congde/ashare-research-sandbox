"""Cross-platform task runner for the course labs."""

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
    run([sys.executable, "-m", "venv", str(VENV)])
    run(
        [
            str(venv_executable("python")),
            "-m",
            "pip",
            "install",
            "-q",
            "-r",
            "requirements.txt",
        ]
    )
    print("setup complete")


def python_lab(script: str, *args: str) -> None:
    run([str(require_venv("python")), script, *args])


def lab_01() -> None:
    pytest = require_venv("pytest")
    starter = ROOT / "labs/01-first-ticket/starter"
    solution = ROOT / "labs/01-first-ticket/solution"

    print("==> Confirm the starter fails for the intended reason", flush=True)
    starter_env = os.environ.copy()
    starter_env["PYTHONPATH"] = str(starter)
    result = subprocess.run(
        [str(pytest), str(starter / "test_todo.py"), "-q"],
        cwd=ROOT,
        env=starter_env,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    if result.returncode == 0:
        raise SystemExit("Starter unexpectedly passed.")
    if "restore checkout" not in output:
        print(output)
        raise SystemExit("Starter failed for an unexpected reason.")

    print("==> Confirm the minimal solution passes", flush=True)
    solution_env = os.environ.copy()
    solution_env["PYTHONPATH"] = str(solution)
    run([str(pytest), str(solution / "test_todo.py"), "-q"], env=solution_env)
    print("Lab 01 fixture is valid.")


TASKS = {
    "setup": setup,
    "lab-00": lambda: python_lab("labs/00-assistant-brief/verify.py"),
    "lab-03": lambda: python_lab("labs/03-entry-workspace/verify.py"),
    "lab-04": lambda: python_lab("labs/04-research/verify.py"),
    "lab-06": lambda: python_lab("labs/06-planning-handoff/verify.py"),
    "lab-09": lambda: python_lab(
        "skills/weekly-brief/scripts/verify_report.py",
        "labs/09-weekly-brief-skill/sample-report.md",
    ),
    "lab-01": lab_01,
    "lab-16": lambda: python_lab(
        "skills/repo-readiness/scripts/verify_report.py",
        "labs/16-repo-readiness-skill/sample-report.md",
    ),
    "courseware-check": lambda: python_lab("scripts/verify_courseware.py"),
}


def check() -> None:
    for task in ("lab-00", "lab-03", "lab-04", "lab-06", "lab-09", "lab-01", "lab-16", "courseware-check"):
        print(f"==> {task}", flush=True)
        TASKS[task]()
    print("All courseware checks passed.")


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
