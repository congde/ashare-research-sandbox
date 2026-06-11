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
SOURCE_CARD_PATTERN = re.compile(r"^###\s+(S\d+)\s*$", re.IGNORECASE | re.MULTILINE)


def section_body(text: str, heading: str) -> str:
    if heading not in text:
        return ""
    body = text.split(heading, 1)[1]
    for other in REQUIRED_HEADINGS + PACKAGE_HEADINGS:
        if other != heading and other in body:
            body = body.split(other, 1)[0]
    return body.strip()


def report_claim_ids(text: str) -> set[str]:
    return {
        match.group(1).upper()
        for line in text.splitlines()
        if (match := ID_PATTERN.search(line.strip()))
    }


def table_rows(text: str, heading: str, header: str) -> list[list[str]]:
    return [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section_body(text, heading).splitlines()
        if line.strip().startswith("|")
        and "---" not in line
        and header not in line
    ]


def source_cards_by_id(text: str) -> dict[str, str]:
    cards = {}
    source_cards = section_body(text, "## Source cards")
    matches = list(SOURCE_CARD_PATTERN.finditer(source_cards))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source_cards)
        cards[match.group(1).upper()] = source_cards[match.end() : end]
    return cards


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


def verify_traceability(report_path: Path, package_path: Path) -> list[str]:
    report_text = report_path.read_text(encoding="utf-8")
    package_text = package_path.read_text(encoding="utf-8")
    errors = []

    report_ids = report_claim_ids(report_text)
    ledger_rows = table_rows(package_text, "## Claim ledger", "| ID |")
    active_ledger_ids = {
        row[0].upper()
        for row in ledger_rows
        if len(row) >= 5 and row[4].lower() in {"accepted", "open"}
    }

    missing_from_ledger = report_ids - active_ledger_ids
    if missing_from_ledger:
        errors.append(
            "report claims missing from active claim ledger: "
            + ", ".join(sorted(missing_from_ledger))
        )

    missing_from_report = active_ledger_ids - report_ids
    if missing_from_report:
        errors.append(
            "active claim ledger entries missing from report: "
            + ", ".join(sorted(missing_from_report))
        )

    cards = source_cards_by_id(package_text)
    source_ids = set(cards)
    accepted_fact_rows = [
        row
        for row in ledger_rows
        if len(row) >= 5
        and row[0].upper().startswith("F")
        and row[4].lower() == "accepted"
    ]
    facts_without_source_cards = {
        row[0].upper()
        for row in accepted_fact_rows
        if not re.search(r"\bS\d+\b", row[3], re.IGNORECASE)
    }
    if facts_without_source_cards:
        errors.append(
            "accepted Facts must reference source cards: "
            + ", ".join(sorted(facts_without_source_cards))
        )
    missing_source_cards = {
        source_id.upper()
        for row in accepted_fact_rows
        for source_id in re.findall(r"\bS\d+\b", row[3], re.IGNORECASE)
        if source_id.upper() not in source_ids
    }
    if missing_source_cards:
        errors.append(
            "accepted Facts reference missing source cards: "
            + ", ".join(sorted(missing_source_cards))
        )

    facts = section_body(report_text, "## Facts")
    fact_urls = {
        match.group(1).upper(): SOURCE_PATTERN.findall(line)
        for line in facts.splitlines()
        if (match := ID_PATTERN.search(line.strip()))
    }
    for row in accepted_fact_rows:
        fact_id = row[0].upper()
        referenced_cards = [
            cards[source_id.upper()]
            for source_id in re.findall(r"\bS\d+\b", row[3], re.IGNORECASE)
            if source_id.upper() in cards
        ]
        card_urls = {
            url
            for card in referenced_cards
            for url in SOURCE_PATTERN.findall(card)
        }
        if card_urls and not card_urls.intersection(fact_urls.get(fact_id, [])):
            errors.append(f"{fact_id} report URL does not match its source card")

    review_rows = table_rows(package_text, "## Source review log", "| Fact ID |")
    reviewed_fact_ids = {
        row[0].upper()
        for row in review_rows
        if len(row) >= 2 and "not reviewed" not in row[1].lower()
    }
    pricing_fact_ids = {
        row[0].upper()
        for row in accepted_fact_rows
        if any(
            "pricing" in card.lower()
            for source_id in re.findall(r"\bS\d+\b", row[3], re.IGNORECASE)
            if (card := cards.get(source_id.upper()))
        )
    }
    if pricing_fact_ids and not reviewed_fact_ids.intersection(pricing_fact_ids):
        errors.append("source review log needs at least one reviewed pricing Fact")

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
        errors.extend(verify_traceability(target, package_target))
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
