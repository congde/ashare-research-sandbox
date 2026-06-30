"""Audit docs/v2/assets PNG usage in publishable chapters."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "v2" / "assets"
V2 = ROOT / "docs" / "v2"
PAT = re.compile(r"assets/([^\s\)\"']+\.png)")

sys.path.insert(0, str(ROOT / "scripts"))
from asset_chapter_map import ASSET_USAGE  # noqa: E402


def refs_in(paths: list[Path]) -> set[str]:
    out: set[str] = set()
    for md in paths:
        if not md.is_file():
            continue
        out.update(PAT.findall(md.read_text(encoding="utf-8")))
    return out


def companion_png(name: str) -> str | None:
    """Return sibling non-drawio name if this is an unreferenced drawio export."""
    if name.endswith(".drawio.png"):
        return name.replace(".drawio.png", ".png")
    return None


def is_satisfied_by_companion(name: str, pngs: set[str], refs: set[str]) -> bool:
    base = companion_png(name)
    return bool(base and base in pngs and base in refs)


def main() -> int:
    pngs = {p.name for p in ASSETS.glob("*.png") if p.is_file()}
    chapter_mds = list(V2.glob("[0-9]*.md"))
    chapter_refs = refs_in(chapter_mds)

    unmapped = sorted(p for p in pngs if p not in ASSET_USAGE)
    unused = sorted(
        p
        for p in pngs
        if p not in chapter_refs and not is_satisfied_by_companion(p, pngs, chapter_refs)
    )
    missing = sorted(r for r in chapter_refs if not (ASSETS / r).exists())
    mapped_not_used = sorted(
        p
        for p in ASSET_USAGE
        if p in pngs and p not in chapter_refs and not p.endswith(".drawio.png")
    )

    print(f"PNG files: {len(pngs)}")
    print(f"Referenced in publishable chapters: {len(chapter_refs)}")
    print(f"Mapped in asset_chapter_map: {len([p for p in ASSET_USAGE if p in pngs])}")
    print(f"Unused in chapters: {len(unused)}")
    print(f"Mapped but not yet referenced: {len(mapped_not_used)}")
    print(f"Unmapped PNG files: {len(unmapped)}")
    print(f"Missing references: {len(missing)}")

    if unmapped:
        print("\n=== UNMAPPED (add to asset_chapter_map.py) ===")
        for u in unmapped:
            print(f"  {u}")

    if mapped_not_used:
        print("\n=== MAPPED BUT NOT REFERENCED (run wire_assets.py) ===")
        for u in mapped_not_used:
            print(f"  {u}")

    if missing:
        print("\n=== MISSING FILES ===")
        for m in missing:
            print(f"  {m}")

    if unmapped or missing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
