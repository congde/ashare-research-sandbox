from pathlib import Path
import re
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
PUBLISHABLE_CHAPTERS = tuple(
    chapter
    for chapter in sorted((ROOT / "docs/v2").glob("*.md"))
    if re.match(r"^(?:00|0[1-9]|[12][0-9]|3[0-5])-", chapter.name)
    and "修订对照" not in chapter.name
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
MARKDOWN_IMAGE = re.compile(r"^!\[[^\]]+\]\([^)]+\)\s*$", re.MULTILINE)
SVG_IMAGE = re.compile(r"^!\[[^\]]+\]\([^)]+\.svg(?:#[^)]+)?\)\s*$", re.MULTILINE)
FIGURE_CAPTION = re.compile(r"^\*\*图\s+(\d+)-(\d+)[　 ].+\*\*\s*$", re.MULTILINE)
CODE_CAPTION = re.compile(r"^\*\*代码\s+(\d+)-(\d+)[　 ].+\*\*\s*$", re.MULTILINE)
TABLE_HEADER = re.compile(r"^\|.*\|\s*$")
TABLE_SEPARATOR = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
TABLE_CAPTION = re.compile(r"^\*\*表\s+(\d+)-(\d+)[　 ].+\*\*\s*$")
REQUIRED_ENDINGS = ("本章总结", "课后题")
NON_PROSE = re.compile(r"^(?:#|!\[|\*\*图|\*\*表|```|\|)")
PART_HEADING = re.compile(r"^## 第[一二三四五六七]篇｜.+$", re.MULTILINE)
MODULE_HEADING = re.compile(r"^### .+$")
CHAPTER_ITEM = re.compile(r"^(\d+)\. .+$")
EXERCISE_ITEM = re.compile(r"^\d+\. \*\*.+?题(?:（[^）]+）)?：\*\*", re.MULTILINE)


def local_target(source: Path, raw_target: str) -> Optional[Path]:
    if raw_target.startswith(("http://", "https://", "#")):
        return None
    target = raw_target.split("#", 1)[0]
    return (source.parent / target).resolve()


def verify_catalog_structure(errors: list[str]) -> None:
    catalog = ROOT / "docs" / "出版课程章节清单.md"
    if not catalog.exists():
        errors.append("docs/出版课程章节清单.md is missing")
        return

    lines = catalog.read_text(encoding="utf-8").splitlines()
    parts: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in lines:
        if PART_HEADING.match(line):
            if current_title is not None:
                parts.append((current_title, current_lines))
            current_title = line
            current_lines = []
            continue
        if current_title is not None and line.startswith("## "):
            parts.append((current_title, current_lines))
            current_title = None
            current_lines = []
            continue
        if current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        parts.append((current_title, current_lines))

    if len(parts) != 7:
        errors.append(
            f"docs/出版课程章节清单.md must contain 7 primary part categories (found {len(parts)})"
        )

    seen_chapters: list[int] = []
    for title, part_lines in parts:
        module_indexes = [
            index for index, line in enumerate(part_lines) if MODULE_HEADING.match(line)
        ]
        if len(module_indexes) < 3:
            errors.append(f"{title} must contain at least 3 secondary module categories")
        first_chapter = next(
            (index for index, line in enumerate(part_lines) if CHAPTER_ITEM.match(line)),
            None,
        )
        if first_chapter is not None and (
            not module_indexes or first_chapter < module_indexes[0]
        ):
            errors.append(f"{title} has chapter items before the first secondary module")
        for position, module_index in enumerate(module_indexes):
            next_module = (
                module_indexes[position + 1]
                if position + 1 < len(module_indexes)
                else len(part_lines)
            )
            module_chapters = [
                int(match.group(1))
                for line in part_lines[module_index + 1 : next_module]
                if (match := CHAPTER_ITEM.match(line))
            ]
            if not module_chapters:
                errors.append(
                    f"{title} / {part_lines[module_index]} must contain at least one chapter"
                )
            seen_chapters.extend(module_chapters)

    if seen_chapters != list(range(1, 36)):
        errors.append(
            "docs/出版课程章节清单.md chapter numbers must be continuous from 1 to 35 "
            f"(found {seen_chapters})"
        )


def main() -> int:
    errors: list[str] = []
    chapter_paragraphs: dict[str, list[Path]] = {}

    verify_catalog_structure(errors)

    for chapter in PUBLISHABLE_CHAPTERS:
        if not chapter.is_file():
            errors.append(f"missing publishable chapter: {chapter.relative_to(ROOT)}")
            continue

        text = chapter.read_text(encoding="utf-8")
        if "写作状态**：大纲" in text or "写作状态**: 大纲" in text:
            continue
        chapter_match = re.match(r"^(\d+)-", chapter.name)
        chapter_number = int(chapter_match.group(1)) if chapter_match else None
        if re.match(r"^(?:0[1-9]|[12][0-9]|3[0-5])-", chapter.name):
            exercise_match = re.search(
                rf"^## (?:{chapter_number}\.\d+\s+)?课后题\s*$",
                text,
                re.MULTILINE,
            )
            if exercise_match:
                tail = text[exercise_match.end() :]
                next_heading = re.search(r"\n## ", tail)
                exercise_section = tail[: next_heading.start()] if next_heading else tail
                exercise_count = len(EXERCISE_ITEM.findall(exercise_section))
                if not 1 <= exercise_count <= 3:
                    errors.append(
                        f"{chapter.relative_to(ROOT)} needs 1 to 3 after-class questions "
                        f"(found {exercise_count})"
                    )
                if re.search(r"^### (?:理解题|判断题|实践题)\s*$", exercise_section, re.MULTILINE):
                    errors.append(
                        f"{chapter.relative_to(ROOT)} should use integrated after-class "
                        "questions instead of separate 理解题/判断题/实践题 sections"
                    )
            if not re.search(r"^### .+$", text, re.MULTILINE):
                errors.append(
                    f"{chapter.relative_to(ROOT)} needs at least one third-level heading"
                )

        if chapter_number is not None:
            image_count = len(MARKDOWN_IMAGE.findall(text))
            if SVG_IMAGE.search(text):
                errors.append(
                    f"{chapter.relative_to(ROOT)} uses SVG images; use PNG for Lark compatibility"
                )
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
            if 1 <= chapter_number <= 35 and image_count == 0:
                errors.append(
                    f"{chapter.relative_to(ROOT)} needs at least one numbered figure"
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
                if (
                    previous < 0
                    or NON_PROSE.match(lines[previous])
                    or f"图 {chapter_number}-" not in lines[previous]
                ):
                    errors.append(
                        f"{chapter.relative_to(ROOT)} figure near line {index + 1} "
                        "needs an introductory sentence that names its figure number"
                    )
                following = index + 1
                while following < len(lines) and not lines[following].strip():
                    following += 1
                if (
                    following >= len(lines)
                    or not re.match(
                        rf"^\*\*图\s+{chapter_number}-\d+[　 ].+\*\*\s*$",
                        lines[following],
                    )
                ):
                    errors.append(
                        f"{chapter.relative_to(ROOT)} figure near line {index + 1} "
                        "needs an adjacent numbered caption"
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
                if (
                    previous < 0
                    or NON_PROSE.match(lines[previous])
                    or f"表 {chapter_number}-" not in lines[previous]
                ):
                    errors.append(
                        f"{chapter.relative_to(ROOT)} table near line {index + 1} "
                        "needs an introductory sentence that names its table number"
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

            if 1 <= chapter_number <= 35:
                if not table_numbers:
                    errors.append(
                        f"{chapter.relative_to(ROOT)} needs at least one numbered table"
                    )
                code_numbers = [
                    (int(match.group(1)), int(match.group(2)))
                    for match in CODE_CAPTION.finditer(text)
                ]
                if not code_numbers:
                    errors.append(
                        f"{chapter.relative_to(ROOT)} needs at least one numbered code example"
                    )
                expected_codes = [
                    (chapter_number, number) for number in range(1, len(code_numbers) + 1)
                ]
                if code_numbers != expected_codes:
                    errors.append(
                        f"{chapter.relative_to(ROOT)} code captions must be continuous "
                        f"from 代码 {chapter_number}-1"
                    )
                for index, line in enumerate(lines):
                    if not re.match(
                        rf"^\*\*代码\s+{chapter_number}-\d+[　 ].+\*\*\s*$",
                        line,
                    ):
                        continue
                    previous = index - 1
                    while previous >= 0 and not lines[previous].strip():
                        previous -= 1
                    if previous < 0 or not lines[previous].startswith("```"):
                        errors.append(
                            f"{chapter.relative_to(ROOT)} code caption near line {index + 1} "
                            "must immediately follow a fenced code block"
                        )
                        continue
                    opener = previous - 1
                    while opener >= 0 and not lines[opener].startswith("```"):
                        opener -= 1
                    intro = opener - 1
                    while intro >= 0 and not lines[intro].strip():
                        intro -= 1
                    if (
                        opener < 0
                        or not re.match(r"^```(?:python|typescript|javascript|json|bash|powershell)\s*$", lines[opener])
                        or intro < 0
                        or NON_PROSE.match(lines[intro])
                        or f"代码 {chapter_number}-" not in lines[intro]
                    ):
                        errors.append(
                            f"{chapter.relative_to(ROOT)} code example near line {index + 1} "
                            "needs a language tag and an introductory sentence naming its code number"
                        )
                if not re.search(r"示例|案例|范例", text):
                    errors.append(
                        f"{chapter.relative_to(ROOT)} needs a worked example or case"
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

