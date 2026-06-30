"""Scan Codex PDF for known errata patterns."""
from __future__ import annotations

import re
from pathlib import Path

import fitz

PDF = Path(r"c:\Users\54461\Desktop\Codex快速入门-PDF-yuancongde-批注.pdf")

PATTERNS: list[tuple[str, str]] = [
    ("cover_typo", r"版\s*芯"),
    ("cover_typo", r"活\s*号"),
    ("typo", r"取取代"),
    ("typo", r"将续修正"),
    ("typo", r"Codex Weba"),
    ("typo", r"要注额外意"),
    ("typo", r"忽被视"),
    ("typo", r"异步评中"),
    ("typo", r"已经是够了"),
    ("typo", r"髙噪声"),
    ("typo", r"仍能保持体稳定"),
    ("typo", r"惊艳地对话"),
    ("typo", r"git diff--check"),
    ("typo", r"AGENTS\. md"),
    ("logic", r"从Codex 的任务地图"),
    ("logic", r"表12-3"),
    ("logic", r"张建飞"),
    ("logic", r"技术不够源"),
    ("logic", r"权限边界都那么清晰"),
    ("logic", r"配套仓库不是营销附件，本书内容生命周期"),
    ("logic", r"codex --worktree"),
    ("logic", r"领域应\s*用”的路径组织"),
    ("grammar", r"往往\s*[“\"]不理解逻辑"),
    ("corrupt", r"\?{3,}"),
    ("header", r"ᄫे"),
]


def main() -> None:
    doc = fitz.open(PDF)
    print(f"File: {PDF.name}")
    print(f"Pages: {doc.page_count}")
    print()

    found_any = False
    for label, pattern in PATTERNS:
        rx = re.compile(pattern)
        hits: list[str] = []
        for i, page in enumerate(doc):
            text = page.get_text()
            if rx.search(text):
                snippet = rx.search(text).group(0)  # type: ignore[union-attr]
                hits.append(f"p{i + 1}:{snippet[:40]}")
        if hits:
            found_any = True
            print(f"[{label}] {pattern}")
            for h in hits[:12]:
                print(f"  - {h}")
            if len(hits) > 12:
                print(f"  ... +{len(hits) - 12} more")
            print()

    # Positive checks
    good = []
    for term in ["读懂Codex 的任务地图", "表13-3", "袁从德", "而是本书内容生命周期", "继续修正", "Codex Web"]:
        pages = [i + 1 for i in range(doc.page_count) if term in doc[i].get_text()]
        if pages:
            good.append((term, len(pages)))
    if good:
        print("FIXED / PRESENT:")
        for term, count in good:
            print(f"  + {term} ({count} pages)")
        print()

    if not found_any:
        print("No known issue patterns found.")
    doc.close()


if __name__ == "__main__":
    main()
