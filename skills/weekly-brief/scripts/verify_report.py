from pathlib import Path
import sys


REQUIRED_HEADINGS = (
    "## This week",
    "## Outcomes",
    "## Blockers",
    "## Next week",
    "## Unknowns",
)

PLACEHOLDER_MARKERS = ("TBD", "(fill in)", "TODO", "待补充")


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

    if len(text.strip()) < 120:
        errors.append("report is too short to be a usable weekly brief")

    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_report.py PATH_TO_REPORT")
        return 2

    report_path = Path(sys.argv[1])
    if not report_path.is_file():
        print(f"report not found: {report_path}")
        return 2

    errors = verify(report_path)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"valid weekly brief: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
