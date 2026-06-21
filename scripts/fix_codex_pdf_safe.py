"""Apply only low-risk PDF text fixes (short, same-font substitutions)."""
from __future__ import annotations

import shutil
from pathlib import Path

import fitz

DESKTOP = Path(r"c:\Users\54461\Desktop")
BACKUP_SUFFIX = ".bak-before-errata-fix"

# Keep to near same-length substitutions; Chinese insertions often corrupt PDF fonts.
SAFE_REPLACEMENTS: list[tuple[str, str]] = [
    ("版 芯", "版 心"),
    ("活 号", "货 号"),
    ("取取代", "取代"),
    ("将续修正", "继续修正"),
    ("Codex Weba", "Codex Web"),
    ("git diff--check", "git diff --check"),
    ("AGENTS. md", "AGENTS.md"),
    ("表12-3", "表13-3"),
    ("髙噪声", "高噪声"),
]


def find_source() -> Path:
    return next(DESKTOP.glob(f"A20261559-Codex*PDF-6.18.pdf{BACKUP_SUFFIX}"))


def replace_on_page(page: fitz.Page, old: str, new: str) -> int:
    count = 0
    while True:
        hits = page.search_for(old)
        if not hits:
            break
        for rect in hits:
            page.add_redact_annot(rect, text=new, fill=False, cross_out=False)
            count += 1
        page.apply_redactions()
    return count


def main() -> None:
    source = find_source()
    doc = fitz.open(source)
    stats: dict[str, int] = {}
    for old, new in SAFE_REPLACEMENTS:
        total = 0
        for page in doc:
            total += replace_on_page(page, old, new)
        stats[old] = total

    output = DESKTOP / "A20261559-Codex快速入门-PDF-6.18-安全勘误.pdf"
    doc.save(output, garbage=4, deflate=True)
    doc.close()

    report = DESKTOP / "A20261559-Codex快速入门-安全勘误报告.txt"
    lines = [
        f"Source: {source}",
        f"Output: {output}",
        "",
        "Applied safe fixes only. Remaining items are in 勘误清单.md and must be edited in source.",
        "",
    ]
    for key, value in stats.items():
        lines.append(f"[{value}] {key}")
    report.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
