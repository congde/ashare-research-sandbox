from pathlib import Path
import re
import sys


REQUIRED_HEADINGS = (
    "## Facts",
    "## Inferences",
    "## Recommendations",
    "## Unknowns",
)

PACKAGE_HEADINGS = (
    "## Research question map",
    "## Source cards",
    "## Claim ledger",
    "## Source review log",
    "## Handoff",
)

SOURCE_PATTERN = re.compile(r"https?://[^\s)>\]]+")
PLACEHOLDER_MARKERS = ("TBD", "(fill in)", "TODO", "待补充")
FACT_PATTERN = re.compile(r"^-\s+F\d+:", re.IGNORECASE)
INFERENCE_PATTERN = re.compile(r"^-\s+I\d+:", re.IGNORECASE)
RECOMMENDATION_PATTERN = re.compile(r"^-\s+R\d+:", re.IGNORECASE)
UNKNOWN_PATTERN = re.compile(r"^-\s+U\d+:", re.IGNORECASE)
FACT_REF_PATTERN = re.compile(r"\bF\d+\b", re.IGNORECASE)
INFERENCE_REF_PATTERN = re.compile(r"\bI\d+\b", re.IGNORECASE)
ID_PATTERN = re.compile(r"^-\s+([FIRU]\d+):", re.IGNORECASE)


def section_body(text: str, heading: str) -> str:
    if heading not in text:
        return ""
    body = text.split(heading, 1)[1]
    for other in REQUIRED_HEADINGS + PACKAGE_HEADINGS:
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
    if fact_lines and not all(FACT_PATTERN.search(line.strip()) for line in fact_lines):
        errors.append("every Facts bullet must use an F-number ID")
    fact_ids = {
        match.group(1).upper()
        for line in fact_lines
        if (match := ID_PATTERN.search(line.strip()))
    }
    if len(fact_ids) != len(fact_lines):
        errors.append("Fact IDs must be unique")

    inferences = section_body(text, "## Inferences")
    inference_lines = [
        line for line in inferences.splitlines() if line.strip().startswith("-")
    ]
    if not inference_lines:
        errors.append("Inferences section has no bullet items")
    if inference_lines and not all(
        INFERENCE_PATTERN.search(line.strip())
        and "Supports:" in line
        and FACT_REF_PATTERN.search(line.split("Supports:", 1)[-1])
        for line in inference_lines
    ):
        errors.append("every Inference must use an I-number ID and support F-number(s)")
    inference_ids = {
        match.group(1).upper()
        for line in inference_lines
        if (match := ID_PATTERN.search(line.strip()))
    }
    if len(inference_ids) != len(inference_lines):
        errors.append("Inference IDs must be unique")
    referenced_fact_ids = {
        reference.upper()
        for line in inference_lines
        if "Supports:" in line
        for reference in FACT_REF_PATTERN.findall(line.split("Supports:", 1)[-1])
    }
    missing_fact_ids = referenced_fact_ids - fact_ids
    if missing_fact_ids:
        errors.append(
            f"Inferences reference missing Fact IDs: {', '.join(sorted(missing_fact_ids))}"
        )

    recommendations = section_body(text, "## Recommendations")
    recommendation_lines = [
        line for line in recommendations.splitlines() if line.strip().startswith("-")
    ]
    if not recommendation_lines:
        errors.append("Recommendations section has no bullet items")
    if recommendation_lines and not all(
        RECOMMENDATION_PATTERN.search(line.strip())
        and "Supports:" in line
        and INFERENCE_REF_PATTERN.search(line.split("Supports:", 1)[-1])
        for line in recommendation_lines
    ):
        errors.append(
            "every Recommendation must use an R-number ID and support I-number(s)"
        )
    recommendation_ids = {
        match.group(1).upper()
        for line in recommendation_lines
        if (match := ID_PATTERN.search(line.strip()))
    }
    if len(recommendation_ids) != len(recommendation_lines):
        errors.append("Recommendation IDs must be unique")
    referenced_inference_ids = {
        reference.upper()
        for line in recommendation_lines
        if "Supports:" in line
        for reference in INFERENCE_REF_PATTERN.findall(line.split("Supports:", 1)[-1])
    }
    missing_inference_ids = referenced_inference_ids - inference_ids
    if missing_inference_ids:
        errors.append(
            "Recommendations reference missing Inference IDs: "
            + ", ".join(sorted(missing_inference_ids))
        )

    unknowns = section_body(text, "## Unknowns")
    normalized_unknowns = unknowns.strip().lower().removeprefix("- ").strip()
    if normalized_unknowns in {"none.", "none", "无", "没有"}:
        errors.append("Unknowns should list genuine open questions, not 'None'")
    unknown_lines = [
        line for line in unknowns.splitlines() if line.strip().startswith("-")
    ]
    if not unknown_lines:
        errors.append("Unknowns section has no bullet items")
    if unknown_lines and not all(
        UNKNOWN_PATTERN.search(line.strip())
        and "Impact:" in line
        and "Next check:" in line
        for line in unknown_lines
    ):
        errors.append(
            "every Unknown must use a U-number ID with Impact and Next check"
        )
    unknown_ids = {
        match.group(1).upper()
        for line in unknown_lines
        if (match := ID_PATTERN.search(line.strip()))
    }
    if len(unknown_ids) != len(unknown_lines):
        errors.append("Unknown IDs must be unique")

    return errors


def verify_package(package_path: Path) -> list[str]:
    text = package_path.read_text(encoding="utf-8")
    errors = [
        f"missing package heading: {heading}"
        for heading in PACKAGE_HEADINGS
        if heading not in text
    ]

    question_rows = [
        line
        for line in section_body(text, "## Research question map").splitlines()
        if line.strip().startswith("|") and "---" not in line and "| ID |" not in line
    ]
    if len(question_rows) < 3:
        errors.append("research question map needs at least three questions")

    source_cards = section_body(text, "## Source cards")
    for token in ("Supports:", "Does not support:", "Retrieved:"):
        if token not in source_cards:
            errors.append(f"source cards need {token}")

    ledger = section_body(text, "## Claim ledger").lower()
    for status in ("accepted", "rejected", "open"):
        if status not in ledger:
            errors.append(f"claim ledger needs a {status} claim")

    review_rows = [
        line
        for line in section_body(text, "## Source review log").splitlines()
        if line.strip().startswith("|")
        and "---" not in line
        and "| Fact ID |" not in line
    ]
    reviewed_rows = [line for line in review_rows if "not reviewed" not in line.lower()]
    if len(reviewed_rows) < 2:
        errors.append("source review log needs at least two reviewed Facts")

    handoff = section_body(text, "## Handoff")
    for token in (
        "Questions covered:",
        "Questions still open:",
        "Claims rejected or downgraded:",
        "Next action:",
    ):
        if token not in handoff:
            errors.append(f"handoff needs {token}")

    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    args = sys.argv[1:]

    if not args:
        starter = root / "labs/04-research/starter/research-report.md"
        solution = root / "labs/04-research/solution/research-report.md"
        package = root / "labs/04-research/solution/research-package.md"
        if verify(starter):
            print("starter correctly fails structural checks")
        else:
            print("ERROR: starter should fail structural checks")
            return 1
        target = solution
        package_target = package
    elif len(args) == 1:
        target = Path(args[0])
        package_target = None
    elif len(args) == 2:
        target = Path(args[0])
        package_target = Path(args[1])
    else:
        print("usage: verify.py [PATH_TO_REPORT] [PATH_TO_RESEARCH_PACKAGE]")
        return 2

    if not target.is_file():
        print(f"report not found: {target}")
        return 2

    errors = verify(target)
    if package_target is not None:
        if not package_target.is_file():
            print(f"research package not found: {package_target}")
            return 2
        errors.extend(verify_package(package_target))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"valid research report: {target}")
    if package_target is not None:
        print(f"valid research package: {package_target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
