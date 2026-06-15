from pathlib import Path
import re
root = Path(r"D:/work/gitee/ashare-research-sandbox")
assets = root / "docs/v2/assets"
pngs = sorted(p.name for p in assets.glob("*.png"))
pat = re.compile(r"assets/([^\)\"']+\.png)")
chapter_refs = set()
for md in (root / "docs/v2").glob("[0-9]*.md"):
    for m in pat.findall(md.read_text(encoding="utf-8")):
        chapter_refs.add(m)
unused = [p for p in pngs if p not in chapter_refs]
missing = [r for r in sorted(chapter_refs) if not (assets / r).exists()]
out = root / "outputs/asset-audit.txt"
out.parent.mkdir(exist_ok=True)
lines = [
    f"PNG files: {len(pngs)}",
    f"Referenced in chapters: {len(chapter_refs)}",
    f"Unused: {len(unused)}",
    "",
    "=== UNUSED ===",
    *unused,
    "",
    "=== MISSING ===",
    *missing,
]
out.write_text("\n".join(lines), encoding="utf-8")
print(out)
