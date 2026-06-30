"""Crop excessive empty margins from referenced course diagrams."""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageChops


ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "docs" / "v2"
ASSETS = V2 / "assets"
IMAGE_REF = re.compile(r"assets/([^)]+\.png)")


def referenced_images() -> set[str]:
    refs: set[str] = set()
    for path in V2.glob("[0-3][0-9]-*.md"):
        refs.update(IMAGE_REF.findall(path.read_text(encoding="utf-8")))
    return refs


def content_box(image: Image.Image) -> tuple[int, int, int, int] | None:
    rgb = image.convert("RGB")
    background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
    return ImageChops.difference(rgb, background).getbbox()


def compact(path: Path) -> bool:
    image = Image.open(path).convert("RGB")
    box = content_box(image)
    if box is None:
        return False

    left, top, right, bottom = box
    used_height = (bottom - top) / image.height
    if used_height >= 0.62:
        return False

    pad_x, pad_y = 36, 30
    crop = (
        max(0, left - pad_x),
        max(0, top - pad_y),
        min(image.width, right + pad_x),
        min(image.height, bottom + pad_y),
    )
    image.crop(crop).save(path)
    return True


def main() -> int:
    changed = 0
    for name in sorted(referenced_images()):
        if name.endswith(".drawio.png"):
            continue
        path = ASSETS / name
        if path.is_file() and compact(path):
            changed += 1
            print(f"compacted {path.relative_to(ROOT)}")
    print(f"done ({changed} diagrams compacted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
