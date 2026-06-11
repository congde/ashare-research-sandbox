#!/usr/bin/env python3
"""Export draw.io pages to PNG for course assets.

Tries draw.io Desktop CLI first; falls back to a minimal Pillow renderer for
simple box-and-arrow diagrams used in supplementary chapter figures.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "docs" / "v2" / "assets"

DRAWIO_CANDIDATES = [
    Path(r"C:\Program Files\draw.io\draw.io.exe"),
    Path(r"C:\Program Files\draw.io\Draw.io.exe"),
    Path("/Applications/draw.io.app/Contents/MacOS/draw.io"),
    Path("/usr/bin/drawio"),
    Path("/usr/local/bin/drawio"),
]


def find_drawio() -> Path | None:
    for candidate in DRAWIO_CANDIDATES:
        if candidate.is_file():
            return candidate
    return shutil.which("drawio") and Path(shutil.which("drawio"))  # type: ignore[arg-type]


def page_index(drawio: Path, page_name: str | None) -> str | None:
    if page_name is None:
        return None
    tree = ET.parse(drawio)
    for index, diagram in enumerate(tree.getroot().findall("diagram")):
        if diagram.get("name") == page_name:
            return str(index)
    return None


def export_with_drawio(drawio: Path, page: str | None, output: Path, width: int) -> bool:
    cli = find_drawio()
    if not cli:
        return False
    cmd = [
        str(cli),
        "--export",
        "--format",
        "png",
        "--border",
        "10",
        "--width",
        str(width),
        "--output",
        str(output),
    ]
    if page:
        cmd.extend(["--page-index", page])
    cmd.append(str(drawio))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return False
    return output.is_file()


def parse_boxes(root: ET.Element) -> list[tuple[str, str, int, int, int, int]]:
    boxes: list[tuple[str, str, int, int, int, int]] = []
    for cell in root.iter("mxCell"):
        if cell.get("edge") == "1":
            continue
        value = cell.get("value") or ""
        text = html.unescape(re.sub(r"<[^>]+>", "", value)).strip()
        if not text or len(text) > 80:
            continue
        geom = cell.find("mxGeometry")
        if geom is None:
            continue
        try:
            x, y, w, h = (
                int(float(geom.get("x", 0))),
                int(float(geom.get("y", 0))),
                int(float(geom.get("width", 0))),
                int(float(geom.get("height", 0))),
            )
        except ValueError:
            continue
        if w < 80 or h < 40:
            continue
        boxes.append((cell.get("id", ""), text, x, y, w, h))
    boxes.sort(key=lambda item: (item[3], item[2]))
    return boxes


def fallback_render(drawio: Path, output: Path, page_name: str | None) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not installed; cannot fallback-render", file=sys.stderr)
        return False

    tree = ET.parse(drawio)
    diagrams = tree.getroot().findall("diagram")
    target = None
    for diagram in diagrams:
        if page_name is None or diagram.get("name") == page_name:
            target = diagram
            break
    if target is None:
        return False

    model = target.find("mxGraphModel")
    if model is None:
        return False
    root = model.find("root")
    if root is None:
        return False

    boxes = parse_boxes(root)
    if not boxes:
        return False

    width = 1440
    height = 810
    img = Image.new("RGB", (width, height), "#F7F8FB")
    draw = ImageDraw.Draw(img)
    font_candidates = (
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    )
    font_path = next((path for path in font_candidates if path.is_file()), None)
    if font_path:
        font = ImageFont.truetype(str(font_path), 22)
        title_font = ImageFont.truetype(str(font_path), 30)
    else:
        font = ImageFont.load_default()
        title_font = font

    title = page_name or drawio.stem
    draw.text((80, 40), title, fill="#101A33", font=title_font)

    box_by_id = {box[0]: box for box in boxes}
    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        source = box_by_id.get(cell.get("source", ""))
        target = box_by_id.get(cell.get("target", ""))
        if not source or not target:
            continue
        _, _, sx, sy, sw, sh = source
        _, _, tx, ty, tw, th = target
        draw.line(
            (sx + sw // 2, sy + sh // 2, tx + tw // 2, ty + th // 2),
            fill="#63738C",
            width=4,
        )

    colors = ["#2563EB", "#0891B2", "#0F9B8E", "#F59E0B", "#7C3AED"]
    for index, (_, text, x, y, w, h) in enumerate(boxes[:8]):
        color = colors[index % len(colors)]
        draw.rounded_rectangle((x, y, x + w, y + h), radius=12, outline=color, width=4, fill="#FFFFFF")
        draw.multiline_text((x + 16, y + 20), text, fill="#101A33", font=font, spacing=6)

    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Export draw.io pages to PNG")
    parser.add_argument("drawio", type=Path, help="Source .drawio file")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output PNG path")
    parser.add_argument("-p", "--page", help="Page name inside the drawio file")
    parser.add_argument("--width", type=int, default=1440)
    args = parser.parse_args()

    selected_page = page_index(args.drawio, args.page)
    if args.page and selected_page is None:
        print(f"draw.io page not found: {args.page}", file=sys.stderr)
        return 1
    if export_with_drawio(args.drawio, selected_page, args.output, args.width):
        print(f"exported via draw.io: {args.output}")
        return 0
    if fallback_render(args.drawio, args.output, args.page):
        print(f"exported via fallback renderer: {args.output}")
        return 0
    print("export failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
