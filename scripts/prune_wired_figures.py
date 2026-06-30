"""Remove bulk-wired supplementary figures from publishable courseware chapters."""

from __future__ import annotations

import re
from pathlib import Path

from generate_chapter_outlines import CHAPTERS

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "docs" / "v2"

BOILERPLATE = "下图说明本讲机制或案例如何推进，可与正文表格对照阅读。"
IMAGE_LINE = re.compile(r"^!\[[^\]]+\]\([^)]+\)\s*$")
FIGURE_CAPTION = re.compile(r"^\*\*图\s+(\d+)-(\d+)[　 ].+\*\*\s*$")
FIGURE_EXPLAIN = re.compile(r"^图\s+(\d+)-(\d+)(?:[　 ：:]|$)")
NON_PROSE = re.compile(r"^(?:#|!\[|\*\*图|\*\*表|```|\|)")
EXERCISES = re.compile(r"^## (?:\d+\.\d+\s+)?练习题\s*$")

OFFICIAL_FIGURE_COUNT = {chapter["num"]: len(chapter.get("figures", [])) for chapter in CHAPTERS}


def chapter_num(path: Path) -> int | None:
    match = re.match(r"^(\d+)-", path.name)
    return int(match.group(1)) if match else None


def is_figure_tail_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped == BOILERPLATE:
        return True
    if IMAGE_LINE.match(stripped):
        return True
    if FIGURE_CAPTION.match(stripped):
        return True
    if FIGURE_EXPLAIN.match(stripped):
        return True
    return False


def trim_exercise_tail(lines: list[str]) -> list[str]:
    start = None
    for index, line in enumerate(lines):
        if EXERCISES.match(line):
            start = index
    if start is None:
        return lines

    tail_start = len(lines)
    for index in range(len(lines) - 1, start, -1):
        if not is_figure_tail_line(lines[index]):
            tail_start = index + 1
            break
    else:
        tail_start = start + 1

    if tail_start < len(lines) and all(is_figure_tail_line(line) for line in lines[tail_start:]):
        return lines[:tail_start]
    return lines


def figure_block_end(lines: list[str], image_index: int) -> int:
    index = image_index + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines) and FIGURE_CAPTION.match(lines[index]):
        index += 1
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if FIGURE_EXPLAIN.match(stripped):
            index += 1
            continue
        break
    while index < len(lines) and not lines[index].strip():
        index += 1
    return index


def remove_boilerplate(lines: list[str]) -> list[str]:
    return [line for line in lines if line.strip() != BOILERPLATE]


def fix_missing_intros(lines: list[str], chapter_number: int) -> list[str]:
    in_fence = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            in_fence = not in_fence
            index += 1
            continue
        if in_fence or not IMAGE_LINE.match(line):
            index += 1
            continue

        previous = index - 1
        while previous >= 0 and not lines[previous].strip():
            previous -= 1
        if previous >= 0 and not NON_PROSE.match(lines[previous]):
            index += 1
            continue

        cursor = index + 1
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        if cursor >= len(lines) or not (caption := FIGURE_CAPTION.match(lines[cursor])):
            index += 1
            continue
        if int(caption.group(1)) != chapter_number:
            index += 1
            continue

        explain_index = cursor + 1
        while explain_index < len(lines) and not lines[explain_index].strip():
            explain_index += 1
        intro = None
        if explain_index < len(lines):
            explain_match = FIGURE_EXPLAIN.match(lines[explain_index])
            if explain_match and int(explain_match.group(1)) == chapter_number:
                intro = lines[explain_index].strip()
                if len(intro) > 120:
                    intro = intro[:117].rstrip("，；。、:： ") + "……"
        if intro is None:
            caption_text = caption_suffix(lines[cursor])
            intro = f"下图概括「{caption_text}」，可与正文表格对照阅读。"
        lines.insert(index, intro)
        index += 2
    return lines


def caption_suffix(line: str) -> str:
    for sep in ("　", " "):
        if sep in line:
            return line.split(sep, 1)[1].rstrip("*").strip("*").strip()
    return line.rstrip("*").strip("*").strip()


def explain_suffix(line: str, chapter_number: int, figure_index: int) -> str:
    prefix = f"图 {chapter_number}-{figure_index}"
    stripped = line.strip()
    if stripped.startswith(prefix):
        return stripped[len(prefix) :].lstrip("　 ").strip()
    return caption_suffix(line)


def renumber_figures(text: str, chapter_number: int) -> str:
    lines = text.splitlines()
    figure_index = 0
    out: list[str] = []
    for line in lines:
        if IMAGE_LINE.match(line):
            figure_index += 1
            out.append(line)
            continue
        match = FIGURE_CAPTION.match(line)
        if match and int(match.group(1)) == chapter_number:
            out.append(f"**图 {chapter_number}-{figure_index}　{caption_suffix(line)}**")
            continue
        explain_match = FIGURE_EXPLAIN.match(line)
        if explain_match and int(explain_match.group(1)) == chapter_number:
            suffix = explain_suffix(line, chapter_number, figure_index)
            out.append(f"图 {chapter_number}-{figure_index}　{suffix}")
            continue
        out.append(line)
    return "\n".join(out)


def prune_chapter(path: Path) -> bool:
    number = chapter_num(path)
    if number is None:
        return False

    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    lines = trim_exercise_tail(lines)
    lines = remove_boilerplate(lines)

    max_figures = OFFICIAL_FIGURE_COUNT.get(number)
    if max_figures is not None:
        kept = 0
        pruned: list[str] = []
        index = 0
        in_fence = False
        while index < len(lines):
            line = lines[index]
            if line.startswith("```"):
                in_fence = not in_fence
                pruned.append(line)
                index += 1
                continue
            if in_fence:
                pruned.append(line)
                index += 1
                continue
            if IMAGE_LINE.match(line):
                kept += 1
                if kept > max_figures:
                    index = figure_block_end(lines, index)
                    continue
            pruned.append(line)
            index += 1
        lines = pruned

    lines = fix_missing_intros(lines, number)
    text = renumber_figures("\n".join(lines), number)
    if text != original:
        path.write_text(text + "\n", encoding="utf-8")
        return True
    return False


def main() -> None:
    changed = 0
    for path in sorted(V2.glob("[0-9]*.md")):
        if prune_chapter(path):
            changed += 1
            print(f"pruned {path.name}")
    print(f"updated {changed} chapter files")


if __name__ == "__main__":
    main()
