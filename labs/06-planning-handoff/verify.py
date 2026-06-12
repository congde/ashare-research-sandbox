from pathlib import Path
import re
import sys


PLAN_HEADINGS = (
    "## Goal and decision",
    "## Scope and non-scope",
    "## Unknowns",
    "## Evidence gates",
    "## Dependencies and ownership",
    "## Verification boundary",
    "## Forbidden actions",
)

HANDOFF_HEADINGS = (
    "## Current state",
    "## Evidence",
    "## Single next action",
    "## Stop and rollback",
    "## Missing information",
    "## Forbidden actions",
)

PLACEHOLDERS = ("TBD", "TODO", "(fill in)")


def section_body(text: str, heading: str, headings: tuple[str, ...]) -> str:
    if heading not in text:
        return ""
    body = text.split(heading, 1)[1]
    positions = [
        body.index(candidate)
        for candidate in headings
        if candidate != heading and candidate in body
    ]
    return body[: min(positions)].strip() if positions else body.strip()


def verify_plan(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    errors = [
        f"plan missing heading: {heading}" for heading in PLAN_HEADINGS if heading not in text
    ]
    for marker in PLACEHOLDERS:
        if marker in text:
            errors.append(f"plan still contains placeholder: {marker}")

    gates = section_body(text, "## Evidence gates", PLAN_HEADINGS)
    milestone_ids = set(re.findall(r"\bM[1-4]\b", gates, re.IGNORECASE))
    if len(milestone_ids) < 4:
        errors.append("evidence gates must cover M1-M4")
    for token in ("evidence", "entry", "pass", "stop", "owner"):
        if token not in gates.lower():
            errors.append(f"evidence gates lack {token}")

    if "non-scope" not in lower:
        errors.append("plan must state non-scope")
    if not re.search(r"\b(stop|return)\b", lower):
        errors.append("plan needs an observable stop or return rule")
    if "rollback" not in lower and "preserve source" not in lower:
        errors.append("plan needs a rollback or source-preservation rule")

    boundary = section_body(text, "## Verification boundary", PLAN_HEADINGS).lower()
    if not any(token in boundary for token in ("verify", "python", "make", "check")):
        errors.append("verification boundary needs a concrete command")
    if "does not prove" not in boundary:
        errors.append("verification boundary must state what the command does not prove")
    return errors


def verify_handoff(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    errors = [
        f"handoff missing heading: {heading}"
        for heading in HANDOFF_HEADINGS
        if heading not in text
    ]
    for marker in PLACEHOLDERS:
        if marker in text:
            errors.append(f"handoff still contains placeholder: {marker}")

    evidence = section_body(text, "## Evidence", HANDOFF_HEADINGS).lower()
    for status in ("passed", "failed", "not run"):
        if status not in evidence:
            errors.append(f"handoff evidence must distinguish {status}")

    next_action = section_body(text, "## Single next action", HANDOFF_HEADINGS)
    bullets = [line for line in next_action.splitlines() if line.strip().startswith("- ")]
    if len(bullets) != 1:
        errors.append("handoff must contain exactly one bullet under Single next action")

    stop = section_body(text, "## Stop and rollback", HANDOFF_HEADINGS).lower()
    if "stop" not in stop or "rollback" not in stop:
        errors.append("handoff must state both stop and rollback")
    if not re.search(r"\bA0[1-5]\b", text):
        errors.append("handoff must link status to concrete A01-A05 evidence IDs")
    if "do not" not in lower:
        errors.append("handoff needs explicit forbidden actions")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    args = sys.argv[1:]
    if not args:
        starter_plan = root / "labs/06-planning-handoff/starter/plan.md"
        starter_handoff = root / "labs/06-planning-handoff/starter/handoff.md"
        solution_plan = root / "labs/06-planning-handoff/solution/plan.md"
        solution_handoff = root / "labs/06-planning-handoff/solution/handoff.md"
        if verify_plan(starter_plan) and verify_handoff(starter_handoff):
            print("starter correctly fails planning and handoff checks")
        else:
            print("ERROR: starter should fail planning and handoff checks")
            return 1
        plan_path, handoff_path = solution_plan, solution_handoff
    elif len(args) == 2:
        plan_path, handoff_path = map(Path, args)
    else:
        print("usage: verify.py [PATH_TO_PLAN PATH_TO_HANDOFF]")
        return 2

    if not plan_path.is_file() or not handoff_path.is_file():
        print("plan or handoff file not found")
        return 2

    errors = verify_plan(plan_path) + verify_handoff(handoff_path)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"valid evidence-gated plan: {plan_path}")
    print(f"valid resumable handoff: {handoff_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
