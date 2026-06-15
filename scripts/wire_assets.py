"""Insert missing asset references into publishable chapters per asset_chapter_map."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from asset_chapter_map import ASSET_USAGE

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "docs" / "v2"
ASSETS = V2 / "assets"
IMAGE_LINE = re.compile(r"^!\[[^\]]+\]\(assets/([^)]+)\)\s*$")
FIGURE_CAPTION = re.compile(r"^\*\*图\s+(\d+)-(\d+)[　 ].+\*\*\s*$")
INSERT_BEFORE = re.compile(r"^## 本章总结\s*$")


def chapter_file(prefix: str) -> Path | None:
    matches = sorted(V2.glob(f"{prefix}*.md"))
    return matches[0] if matches else None


def existing_assets(text: str) -> set[str]:
    return set(re.findall(r"assets/([^\)\"']+\.png)", text))


def figure_count(text: str, chapter_num: int) -> int:
    nums = [
        int(m.group(2))
        for m in FIGURE_CAPTION.finditer(text)
        if int(m.group(1)) == chapter_num
    ]
    return max(nums) if nums else 0


def build_block(chapter_num: int, fig_num: int, filename: str, alt: str, caption: str) -> str:
    intro = (
        f"下图（图 {chapter_num}-{fig_num}）补充说明与本讲主线的关系，"
        f"便于与仓库其他章节插图对照阅读。"
    )
    return (
        f"\n{intro}\n\n"
        f"![{alt}](assets/{filename})\n\n"
        f"**图 {chapter_num}-{fig_num}　{caption}**\n\n"
        f"图 {chapter_num}-{fig_num} 与正文表格、示例配合使用；若与主图主题重复，"
        f"以主图（图 {chapter_num}-1、图 {chapter_num}-2）为验收优先。\n"
    )


def wire_chapter(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^(\d+)-", path.name)
    if not m:
        return False
    chapter_num = int(m.group(1))
    prefix = f"{chapter_num:02d}-"

    to_add: list[tuple[str, str, str, str]] = []
    present = existing_assets(text)
    for filename, (pfx, alt, caption) in ASSET_USAGE.items():
        if not pfx.startswith(prefix):
            continue
        if filename.endswith(".drawio.png"):
            continue
        if not (ASSETS / filename).exists():
            continue
        if filename in present:
            continue
        to_add.append((filename, alt, caption, pfx))

    if not to_add:
        return False

    # stable order: primary chapter assets first, then supplements
    to_add.sort(key=lambda x: (x[0].startswith(f"chapter-{chapter_num:02d}"), x[0]))

    fig_num = figure_count(text, chapter_num)
    blocks = []
    for filename, alt, caption, _ in to_add:
        fig_num += 1
        blocks.append(build_block(chapter_num, fig_num, filename, alt, caption))

    insertion = "".join(blocks)
    if INSERT_BEFORE.search(text):
        text = INSERT_BEFORE.sub(insertion + r"\g<0>", text, count=1)
    else:
        text = text.rstrip() + "\n" + insertion

    path.write_text(text, encoding="utf-8")
    print(f"wired {len(to_add)} assets into {path.name}")
    return True


def main() -> None:
    print(
        "wire_assets is disabled: supplementary figures are no longer auto-appended "
        "to chapter ends. Use scripts/prune_wired_figures.py to clean legacy inserts."
    )


if __name__ == "__main__":
    main()
