from pathlib import Path
import sys


REQUIRED_HEADINGS = (
    "## Goal",
    "## Context",
    "## Constraints",
    "## Done when",
)

PLACEHOLDER_MARKERS = ("TBD", "(fill in)", "TODO", "待补充", "帮我看看")


def verify(report_path: Path) -> list[str]:
    text = report_path.read_text(encoding="utf-8")
    errors = [
        f"missing heading: {heading}"
        for heading in REQUIRED_HEADINGS
        if heading not in text
    ]

    for marker in PLACEHOLDER_MARKERS:
        if marker in text:
            errors.append(f"brief still contains placeholder: {marker}")

    done_when_section = ""
    if "## Done when" in text:
        done_when_section = text.split("## Done when", 1)[1]
        if "##" in done_when_section:
            done_when_section = done_when_section.split("##", 1)[0]

    if done_when_section.strip() and not any(
        token in done_when_section
        for token in ("- ", "1.", "verify", "验收", "check", "make ")
    ):
        errors.append("Done when lacks a checkable criterion")

    if len(text.strip()) < 120:
        errors.append("brief is too short to be delegatable")

    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    args = sys.argv[1:]

    if not args:
        starter = root / "labs/00-assistant-brief/starter/brief.md"
        solution = root / "labs/00-assistant-brief/solution/brief.md"
        if verify(starter):
            print("starter correctly fails structural checks")
        else:
            print("ERROR: starter should fail structural checks")
            return 1
        target = solution
    elif len(args) == 1:
        target = Path(args[0])
    else:
        print("usage: verify.py [PATH_TO_BRIEF]")
        return 2

    if not target.is_file():
        print(f"brief not found: {target}")
        return 2

    errors = verify(target)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"valid brief: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
