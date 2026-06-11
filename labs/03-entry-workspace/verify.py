from pathlib import Path
import re
import sys


REQUIRED_HEADINGS = (
    "## Task dependencies",
    "## Capability matrix",
    "## Chosen entry",
    "## Entry limitations",
    "## Workspace contract",
    "## Human approval gates",
)

WORKSPACE_HEADINGS = (
    "### Read before work",
    "### Allowed writes",
    "### Evidence and uncertainty",
    "### Verification",
    "### Forbidden actions",
)

REQUIRED_CAPABILITIES = ("read", "write", "verification", "official")
PLACEHOLDER_MARKERS = ("TBD", "(fill in)", "TODO", "待补充")
RESULT_PATTERN = re.compile(r"\b(passed|failed|not run)\b", re.IGNORECASE)
PATH_OR_COMMAND_PATTERN = re.compile(r"`[^`]+`")


def section_body(text: str, heading: str) -> str:
    if heading not in text:
        return ""
    body = text.split(heading, 1)[1]
    next_headings = [
        candidate
        for candidate in REQUIRED_HEADINGS + WORKSPACE_HEADINGS
        if candidate != heading and candidate in body
    ]
    positions = [body.index(candidate) for candidate in next_headings]
    if positions:
        body = body[: min(positions)]
    return body.strip()


def verify(decision_path: Path) -> list[str]:
    text = decision_path.read_text(encoding="utf-8")
    lower = text.lower()
    errors = [
        f"missing heading: {heading}"
        for heading in REQUIRED_HEADINGS + WORKSPACE_HEADINGS
        if heading not in text
    ]

    for marker in PLACEHOLDER_MARKERS:
        if marker in text:
            errors.append(f"decision still contains placeholder: {marker}")

    matrix = section_body(text, "## Capability matrix")
    rows = [line for line in matrix.splitlines() if line.strip().startswith("|")]
    data_rows = [line for line in rows if "---" not in line and "Capability" not in line]
    if len(data_rows) < 4:
        errors.append("capability matrix needs at least four data rows")
    if data_rows and any(not RESULT_PATTERN.search(row) for row in data_rows):
        errors.append("every capability row needs a passed, failed, or not run result")
    if data_rows and any(len([cell for cell in row.split("|") if cell.strip()]) < 6 for row in data_rows):
        errors.append("every capability row needs probe, result, evidence, and fallback")
    for capability in REQUIRED_CAPABILITIES:
        if capability not in matrix.lower():
            errors.append(f"capability matrix does not cover: {capability}")

    chosen = section_body(text, "## Chosen entry")
    if len(chosen) < 100:
        errors.append("chosen entry lacks a capability-based rationale")

    limitations = section_body(text, "## Entry limitations")
    if len(limitations) < 60:
        errors.append("entry limitations need an honest gap or constraint")

    workspace = "\n".join(section_body(text, heading) for heading in WORKSPACE_HEADINGS)
    if not PATH_OR_COMMAND_PATTERN.search(workspace):
        errors.append("workspace contract needs concrete paths or commands")
    workspace_lower = workspace.lower()
    for token in ("unknown", "verify"):
        if token not in workspace_lower:
            errors.append(f"workspace contract lacks a concrete {token} rule")

    approvals = section_body(text, "## Human approval gates")
    if len(approvals) < 60:
        errors.append("human approval gates need concrete decisions or actions")

    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    args = sys.argv[1:]

    if not args:
        starter = root / "labs/03-entry-workspace/starter/entry-decision.md"
        solution = root / "labs/03-entry-workspace/solution/entry-decision.md"
        if verify(starter):
            print("starter correctly fails entry-decision checks")
        else:
            print("ERROR: starter should fail entry-decision checks")
            return 1
        target = solution
    elif len(args) == 1:
        target = Path(args[0])
    else:
        print("usage: verify.py [PATH_TO_ENTRY_DECISION]")
        return 2

    if not target.is_file():
        print(f"entry decision not found: {target}")
        return 2

    errors = verify(target)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"valid entry decision: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
