from pathlib import Path
import re
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
PUBLISHABLE_CHAPTERS = tuple(
    chapter
    for chapter in sorted((ROOT / "docs/v2").glob("*.md"))
    if re.match(r"^(?:00|0[1-9]|1[0-9]|20)-", chapter.name)
    and "修订对照" not in chapter.name
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
MARKDOWN_IMAGE = re.compile(r"^!\[[^\]]+\]\([^)]+\)\s*$", re.MULTILINE)
FIGURE_CAPTION = re.compile(r"^\*\*图\s+(\d+)-(\d+)[　 ].+\*\*\s*$", re.MULTILINE)
TABLE_HEADER = re.compile(r"^\|.*\|\s*$")
TABLE_SEPARATOR = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
TABLE_CAPTION = re.compile(r"^\*\*表\s+(\d+)-(\d+)[　 ].+\*\*\s*$")
REQUIRED_ENDINGS = ("本章总结", "练习题")
NON_PROSE = re.compile(r"^(?:#|!\[|\*\*图|\*\*表|```|\|)")


def local_target(source: Path, raw_target: str) -> Optional[Path]:
    if raw_target.startswith(("http://", "https://", "#")):
        return None
    target = raw_target.split("#", 1)[0]
    return (source.parent / target).resolve()


def main() -> int:
    errors: list[str] = []
    chapter_paragraphs: dict[str, list[Path]] = {}

    for chapter in PUBLISHABLE_CHAPTERS:
        if not chapter.is_file():
            errors.append(f"missing publishable chapter: {chapter.relative_to(ROOT)}")
            continue

        text = chapter.read_text(encoding="utf-8")
        chapter_match = re.match(r"^(\d+)-", chapter.name)
        chapter_number = int(chapter_match.group(1)) if chapter_match else None
        if re.match(r"^(?:0[5-9]|1[0-9]|20)-", chapter.name):
            for heading in REQUIRED_ENDINGS:
                if not re.search(
                    rf"^## (?:\d+\.\d+\s+)?{re.escape(heading)}\s*$",
                    text,
                    re.MULTILINE,
                ):
                    errors.append(
                        f"{chapter.relative_to(ROOT)} is missing required heading {heading}"
                    )

        if chapter_number is not None:
            image_count = len(MARKDOWN_IMAGE.findall(text))
            figure_numbers = [
                (int(match.group(1)), int(match.group(2)))
                for match in FIGURE_CAPTION.finditer(text)
            ]
            expected_figures = [
                (chapter_number, number) for number in range(1, image_count + 1)
            ]
            if figure_numbers != expected_figures:
                errors.append(
                    f"{chapter.relative_to(ROOT)} figure captions must be continuous "
                    f"from 图 {chapter_number}-1"
                )

            lines = text.splitlines()
            in_fence = False
            for index, line in enumerate(lines):
                if line.startswith("```"):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                if not re.match(r"^!\[[^\]]+\]\([^)]+\)\s*$", line):
                    continue
                previous = index - 1
                while previous >= 0 and not lines[previous].strip():
                    previous -= 1
                if previous < 0 or NON_PROSE.match(lines[previous]):
                    errors.append(
                        f"{chapter.relative_to(ROOT)} figure near line {index + 1} "
                        "needs an introductory sentence"
                    )

            table_numbers: list[tuple[int, int]] = []
            in_fence = False
            for index in range(len(lines) - 1):
                if lines[index].startswith("```"):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                if not (
                    TABLE_HEADER.match(lines[index])
                    and TABLE_SEPARATOR.match(lines[index + 1])
                ):
                    continue
                cursor = index + 2
                while cursor < len(lines) and TABLE_HEADER.match(lines[cursor]):
                    cursor += 1
                while cursor < len(lines) and not lines[cursor].strip():
                    cursor += 1
                if cursor >= len(lines) or not (match := TABLE_CAPTION.match(lines[cursor])):
                    errors.append(
                        f"{chapter.relative_to(ROOT)} table near line {index + 1} "
                        "needs a numbered caption"
                    )
                    continue
                previous = index - 1
                while previous >= 0 and not lines[previous].strip():
                    previous -= 1
                if previous < 0 or NON_PROSE.match(lines[previous]):
                    errors.append(
                        f"{chapter.relative_to(ROOT)} table near line {index + 1} "
                        "needs an introductory sentence"
                    )
                table_numbers.append((int(match.group(1)), int(match.group(2))))
            expected_tables = [
                (chapter_number, number) for number in range(1, len(table_numbers) + 1)
            ]
            if table_numbers != expected_tables:
                errors.append(
                    f"{chapter.relative_to(ROOT)} table captions must be continuous "
                    f"from 表 {chapter_number}-1"
                )

            if 4 <= chapter_number <= 20:
                if image_count < 2:
                    errors.append(
                        f"{chapter.relative_to(ROOT)} needs at least two teaching figures"
                    )
                if not table_numbers:
                    errors.append(
                        f"{chapter.relative_to(ROOT)} needs at least one numbered table"
                    )
                if not re.search(r"示例|案例|范例", text):
                    errors.append(
                        f"{chapter.relative_to(ROOT)} needs a worked example or case"
                    )
            if 4 <= chapter_number <= 19:
                opening = "\n".join(lines[:40])
                closing = "\n".join(lines[-100:])
                if not re.search(r"上一讲|第[一二三四五六七八九十]+讲|前几讲|前 \d+ 讲", opening):
                    errors.append(
                        f"{chapter.relative_to(ROOT)} opening must connect to prior learning"
                    )
                if "下一讲" not in closing:
                    errors.append(
                        f"{chapter.relative_to(ROOT)} ending must introduce the next chapter"
                    )

        prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        for paragraph in re.split(r"\n\s*\n", prose):
            normalized = re.sub(r"\s+", " ", paragraph).strip()
            if (
                len(normalized) >= 120
                and not normalized.startswith(("**图 ", "**表 ", "|", "#"))
            ):
                chapter_paragraphs.setdefault(normalized, []).append(chapter)

        for raw_target in MARKDOWN_LINK.findall(text):
            target = local_target(chapter, raw_target)
            if target is not None and not target.exists():
                errors.append(
                    f"{chapter.relative_to(ROOT)} links to missing {raw_target}"
                )

    for paragraph, chapters in chapter_paragraphs.items():
        unique_chapters = sorted(set(chapters))
        if len(unique_chapters) > 1:
            locations = ", ".join(str(path.relative_to(ROOT)) for path in unique_chapters)
            errors.append(f"duplicate teaching paragraph across chapters: {locations}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("publishable chapter structure and local links are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
