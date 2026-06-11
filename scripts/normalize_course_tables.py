"""Normalize numbered table captions in publishable course chapters."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CHAPTER = re.compile(r"^(0[0-9]|1[0-9]|20)-")
TABLE_ROW = re.compile(r"^\|.*\|\s*$")
TABLE_SEPARATOR = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
TABLE_CAPTION = re.compile(r"^\*\*表\s*(\d+)-(\d+)[　 ]+(.+?)\*\*\s*$")
GENERATED_INTRO = re.compile(r"^表 \d+-\d+ 把“.+”涉及的字段放在一起，便于后续示例逐项对照。$")


def table_title(header: str) -> str:
    cells = [cell.strip() for cell in header.strip().strip("|").split("|")]
    if len(cells) == 2:
        return f"{cells[0]}与{cells[1]}对照"
    if len(cells) == 3:
        return f"{cells[0]}、{cells[1]}与{cells[2]}对照"
    return "关键字段与判断依据"


def normalize(path: Path, chapter_number: int) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    cleaned: list[str] = []
    in_fence = False
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
            cleaned.append(line)
            continue
        if in_fence and (TABLE_CAPTION.match(line) or GENERATED_INTRO.match(line)):
            continue
        cleaned.append(line)
    lines = cleaned

    output: list[str] = []
    table_number = 0
    index = 0
    in_fence = False

    while index < len(lines):
        if lines[index].startswith("```"):
            in_fence = not in_fence
            output.append(lines[index])
            index += 1
            continue
        if (
            not in_fence
            and
            index + 1 < len(lines)
            and TABLE_ROW.match(lines[index])
            and TABLE_SEPARATOR.match(lines[index + 1])
        ):
            table_number += 1
            table_lines = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and TABLE_ROW.match(lines[index]):
                table_lines.append(lines[index])
                index += 1

            blanks: list[str] = []
            while index < len(lines) and not lines[index].strip():
                blanks.append(lines[index])
                index += 1

            title = table_title(table_lines[0])
            if index < len(lines) and (match := TABLE_CAPTION.match(lines[index])):
                title = match.group(3).rstrip("。")
                index += 1

            output.extend(table_lines)
            output.append("")
            output.append(f"**表 {chapter_number}-{table_number}　{title}**")
            if index < len(lines) and lines[index].strip():
                output.append("")
            continue

        if TABLE_CAPTION.match(lines[index]):
            index += 1
            continue

        output.append(lines[index])
        index += 1

    lines = output
    output = []
    index = 0
    in_fence = False
    while index < len(lines):
        if lines[index].startswith("```"):
            in_fence = not in_fence
            output.append(lines[index])
            index += 1
            continue
        if (
            not in_fence
            and
            index + 1 < len(lines)
            and TABLE_ROW.match(lines[index])
            and TABLE_SEPARATOR.match(lines[index + 1])
        ):
            previous = len(output) - 1
            while previous >= 0 and not output[previous].strip():
                previous -= 1
            needs_intro = previous < 0 or re.match(
                r"^(?:#|!\[|\*\*图|\*\*表|```|\|)",
                output[previous],
            )

            cursor = index + 2
            while cursor < len(lines) and TABLE_ROW.match(lines[cursor]):
                cursor += 1
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            caption = TABLE_CAPTION.match(lines[cursor]) if cursor < len(lines) else None
            if needs_intro and caption:
                if output and output[-1].strip():
                    output.append("")
                output.append(
                    f"表 {chapter_number}-{caption.group(2)} "
                    f"把“{caption.group(3)}”涉及的字段放在一起，"
                    "便于后续示例逐项对照。"
                )
                output.append("")

        output.append(lines[index])
        index += 1

    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    for path in sorted((ROOT / "docs/v2").glob("*.md")):
        match = CHAPTER.match(path.name)
        if match and "修订对照" not in path.name:
            normalize(path, int(match.group(1)))
    print("normalized table captions for chapters 00-20")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
