from pathlib import Path
import re
import sys


REQUIRED_HEADINGS = (
    "## Facts",
    "## Inferences",
    "## Recommendations",
    "## Unknowns",
)

SOURCE_PATTERN = re.compile(r"https?://[^\s)>\]]+")
PLACEHOLDER_MARKERS = ("TBD", "(fill in)", "TODO", "待补充")


def section_body(text: str, heading: str) -> str:
    if heading not in text:
        return ""
    body = text.split(heading, 1)[1]
    for other in REQUIRED_HEADINGS:
        if other != heading and other in body:
            body = body.split(other, 1)[0]
    return body.strip()


def verify(report_path: Path) -> list[str]:
    text = report_path.read_text(encoding="utf-8")
    errors = [
        f"missing heading: {heading}"
        for heading in REQUIRED_HEADINGS
        if heading not in text
    ]

    for marker in PLACEHOLDER_MARKERS:
        if marker in text:
            errors.append(f"report still contains placeholder: {marker}")

    facts = section_body(text, "## Facts")
    if facts and not SOURCE_PATTERN.search(facts):
        errors.append("Facts section has no source URL")

    fact_lines = [line for line in facts.splitlines() if line.strip().startswith("-")]
    if facts and not fact_lines:
        errors.append("Facts section has no bullet items")

    if facts and fact_lines and not all(SOURCE_PATTERN.search(line) for line in fact_lines):
        errors.append("every Facts bullet must cite a source URL")

    unknowns = section_body(text, "## Unknowns")
    if unknowns.strip().lower() in {"none.", "none", "无", "没有"}:
        errors.append("Unknowns should list genuine open questions, not 'None'")

    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    args = sys.argv[1:]

    if not args:
        starter = root / "labs/04-research/starter/research-report.md"
        solution = root / "labs/04-research/solution/research-report.md"
        if verify(starter):
            print("starter correctly fails structural checks")
        else:
            print("ERROR: starter should fail structural checks")
            return 1
        target = solution
    elif len(args) == 1:
        target = Path(args[0])
    else:
        print("usage: verify.py [PATH_TO_REPORT]")
        return 2

    if not target.is_file():
        print(f"report not found: {target}")
        return 2

    errors = verify(target)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"valid research report: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
