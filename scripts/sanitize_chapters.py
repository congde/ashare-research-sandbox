"""Remove editorial scaffolding from publishable chapter drafts."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "docs" / "v2"


def drop_metadata_block(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    if i < len(lines) and lines[i].startswith("# "):
        out.append(lines[i])
        i += 1
    while i < len(lines) and lines[i].startswith(">"):
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    out.extend(lines[i:])
    return "\n".join(out)


def remove_section(text: str, heading_prefix: str) -> str:
    pattern = re.compile(
        rf"^## {re.escape(heading_prefix)}.*$",
        re.M,
    )
    while True:
        match = pattern.search(text)
        if not match:
            break
        start = match.start()
        rest = text[match.end() :]
        next_heading = re.search(r"^## ", rest, re.M)
        end = match.end() + (next_heading.start() if next_heading else len(rest))
        text = text[:start].rstrip() + "\n\n" + text[end:].lstrip()
    return text


def remove_numbered_section(text: str, heading_text: str) -> str:
    pattern = re.compile(
        rf"^## \d+\.\d+\s+{re.escape(heading_text)}.*$",
        re.M,
    )
    while True:
        match = pattern.search(text)
        if not match:
            break
        start = match.start()
        rest = text[match.end() :]
        next_heading = re.search(r"^## ", rest, re.M)
        end = match.end() + (next_heading.start() if next_heading else len(rest))
        text = text[:start].rstrip() + "\n\n" + text[end:].lstrip()
    return text


def remove_any_heading_section(text: str, heading_text: str) -> str:
    pattern = re.compile(
        rf"^(?P<marks>##+) {re.escape(heading_text)}.*$",
        re.M,
    )
    while True:
        match = pattern.search(text)
        if not match:
            break
        marks = match.group("marks")
        level = len(marks)
        start = match.start()
        rest = text[match.end() :]
        next_heading = re.search(rf"^#{{2,{level}}} ", rest, re.M)
        end = match.end() + (next_heading.start() if next_heading else len(rest))
        text = text[:start].rstrip() + "\n\n" + text[end:].lstrip()
    return text


def remove_extended_reading(text: str) -> str:
    return remove_section(text, "延伸阅读")


def remove_editorial_scaffolding(text: str) -> str:
    text = remove_any_heading_section(text, "本章交付物")
    text = remove_numbered_section(text, "外部研究依据与阅读边界")
    text = remove_section(text, "外部研究依据与阅读边界")
    text = re.sub(r"^### 本章在全书中的位置\s*\n+", "", text, flags=re.M)
    text = text.replace("在全书中的位置", "在本书中的衔接")
    return text


def remove_deep_discussion(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    skip = False
    for line in lines:
        if re.match(r"^## 深化讨论", line):
            skip = True
            continue
        if skip:
            if re.match(r"^## ", line):
                skip = False
                out.append(line)
            continue
        out.append(line)
    return "\n".join(out)


def dedupe_trailing_sections(text: str) -> str:
    """Keep first 本章总结 / 练习题; drop later duplicates."""
    for title in ("本章总结", "过关任务", "练习题"):
        parts = re.split(rf"(^## {title}\s*$)", text, flags=re.M)
        if len(parts) <= 3:
            continue
        # parts: [before, heading, body, heading, body, ...]
        first = parts[0]
        kept = parts[1] + parts[2]
        rest = "".join(parts[3:])
        rest = re.sub(rf"^## {title}\s*$[\s\S]*?(?=^## |\Z)", "", rest, flags=re.M)
        text = first + kept + rest
    return text


def fix_old_lecture_headers(text: str) -> str:
    text = re.sub(r"^# 讲 \d+｜[^\n]+\n+", "", text, flags=re.M)
    text = re.sub(r"^### \d+\.\d+", lambda m: m.group(0), text)  # noop guard
    return text


def normalize_chapter_summary(text: str, num: int) -> str:
    text = re.sub(
        r"第一讲只训练一个动作",
        f"第 {num} 讲只训练一个动作",
        text,
    )
    text = re.sub(
        r"上一讲为全课主线的前序步骤。本讲继续推进固定离线 Web3 沙盒。\n\n",
        "",
        text,
    )
    return text


def sanitize_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    text = original
    text = drop_metadata_block(text)
    text = remove_extended_reading(text)
    text = remove_editorial_scaffolding(text)
    text = remove_deep_discussion(text)
    text = remove_section(text, "旧稿复用说明")
    text = remove_section(text, "完整示例（大纲）")
    text = remove_section(text, "图表配置")
    text = remove_section(text, "章节衔接")
    text = remove_section(text, "正文大纲")
    text = remove_section(text, "本讲要讲清的问题")
    text = fix_old_lecture_headers(text)
    text = dedupe_trailing_sections(text)
    m = re.match(r"^(\d+)-", path.name)
    if m:
        text = normalize_chapter_summary(text, int(m.group(1)))
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed = 0
    for path in sorted(V2.glob("*.md")):
        if path.name == "README.md":
            continue
        if sanitize_file(path):
            changed += 1
            print(f"sanitized {path.relative_to(ROOT)}")
    print(f"done ({changed} files changed)")


if __name__ == "__main__":
    main()
