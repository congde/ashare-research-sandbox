from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from print_figure_config import PRINT_DPI, scale


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
DRAWIO_OUT = ROOT / "docs" / "v2" / "assets" / "chapter-03-readiness-switches.drawio"
WIDTH, HEIGHT = scale(1440), scale(810)


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), scale(size))
    return ImageFont.load_default()


def sb(*values: int) -> tuple[int, ...]:
    return tuple(scale(value) for value in values)


TITLE = font(46)
SUB = font(24)
BODY = font(26)
SMALL = font(21)
TINY = font(18)

BG = "#F7F8FB"
INK = "#102033"
MUTED = "#607086"
LINE = "#6B7A90"


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.multiline_textbbox((0, 0), text, font=fnt, spacing=6)
    return box[2] - box[0], box[3] - box[1]


def center_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    fnt: ImageFont.ImageFont,
    fill: str = INK,
) -> None:
    w, h = text_size(draw, text, fnt)
    x1, y1, x2, y2 = box
    draw.multiline_text(
        (x1 + (x2 - x1 - w) / 2, y1 + (y2 - y1 - h) / 2),
        text,
        font=fnt,
        fill=fill,
        spacing=6,
        align="center",
    )


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str,
    width: int = 4,
    radius: int = 18,
) -> None:
    draw.rounded_rectangle(box, radius=scale(radius), fill=fill, outline=outline, width=scale(width))


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: str = LINE,
    width: int = 5,
) -> None:
    draw.line([start, end], fill=color, width=scale(width))
    x1, y1 = start
    x2, y2 = end
    angle = math.atan2(y2 - y1, x2 - x1)
    length = scale(18)
    spread = 0.55
    points = [
        end,
        (x2 - length * math.cos(angle - spread), y2 - length * math.sin(angle - spread)),
        (x2 - length * math.cos(angle + spread), y2 - length * math.sin(angle + spread)),
    ]
    draw.polygon(points, fill=color)


def title(draw: ImageDraw.ImageDraw, heading: str, subtitle: str) -> None:
    draw.text(sb(70, 48), heading, font=TITLE, fill=INK)
    draw.text(sb(72, 108), subtitle, font=SUB, fill=MUTED)


def repository_map() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    title(draw, "第 3 讲仓库入口地图", "先定位入口，再运行命令；缺一类入口，就不能声称工作区可交接。")

    root_box = sb(485, 175, 955, 285)
    rounded(draw, root_box, "#FFFFFF", "#2563EB", width=5)
    center_text(draw, root_box, "仓库根目录\nD:\\work\\gitee\\\nashare-research-sandbox", SMALL)

    boxes = [
        (sb(70, 390, 330, 535), "课程验证入口\nscripts/course.py\nverify.py", "#E8F1FF", "#2563EB"),
        (sb(420, 390, 680, 535), "固定样本入口\ndata/prices.csv", "#E7F8F3", "#0F9B8E"),
        (sb(760, 390, 1020, 535), "报告命令入口\nreport_cli.py", "#FFF4DB", "#D97706"),
        (sb(1110, 390, 1370, 535), "就绪记录入口\ndocs/samples/\nworkspace-\nreadiness-record.md", "#F5ECFF", "#7C3AED"),
    ]

    for box, label, fill, stroke in boxes:
        rounded(draw, box, fill, stroke)
        center_text(draw, box, label, SMALL)
        arrow(draw, ((root_box[0] + root_box[2]) // 2, root_box[3]), ((box[0] + box[2]) // 2, box[1]))

    footer = sb(185, 645, 1255, 730)
    rounded(draw, footer, "#102033", "#102033", width=0, radius=16)
    center_text(draw, footer, "读图顺序：根目录 -> 样本 -> 命令 -> 输出 -> 记录。截图不能替代路径、解释器和原始结果。", SMALL, "#FFFFFF")
    image.save(OUT / "chapter-03-repository-map.png", dpi=(PRINT_DPI, PRINT_DPI))


def readiness_switches() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    title(draw, "工作区就绪四开关", "四项同时为真，才能写“工作区可交接”；任一项为假，就退回补记录。")

    boxes = [
        (sb(90, 240, 340, 390), "path_ok\n根目录、脚本、模板\n可定位", "#E8F1FF", "#2563EB"),
        (sb(420, 240, 670, 390), "sample_ok\n假设卡样本\n仍然存在", "#E7F8F3", "#0F9B8E"),
        (sb(750, 240, 1000, 390), "command_ok\n命令真实运行\n保留退出结果", "#FFF4DB", "#D97706"),
        (sb(1080, 240, 1330, 390), "limitation_ok\n离线路径与增强路径\n分开说明", "#F5ECFF", "#7C3AED"),
    ]

    for box, label, fill, stroke in boxes:
        rounded(draw, box, fill, stroke)
        center_text(draw, box, label, SMALL)

    y = scale(470)
    for index in range(len(boxes) - 1):
        arrow(draw, (boxes[index][0][2] + scale(25), scale(315)), (boxes[index + 1][0][0] - scale(25), scale(315)))
        draw.text((boxes[index][0][2] + scale(52), scale(285)), "and", font=TINY, fill=MUTED)

    decision = sb(360, 470, 1080, 580)
    rounded(draw, decision, "#FFFFFF", "#111827", width=5)
    center_text(
        draw,
        decision,
        "workspace_ready =\npath_ok and sample_ok and\ncommand_ok and limitation_ok",
        SMALL,
    )

    for box, _, _, _ in boxes:
        arrow(draw, ((box[0] + box[2]) // 2, box[3]), (scale(720), decision[1]))

    ok_box = sb(210, 650, 600, 730)
    fail_box = sb(840, 650, 1230, 730)
    rounded(draw, ok_box, "#E8F5E9", "#2E7D32")
    center_text(draw, ok_box, "四项都成立：\n工作区可交接", SMALL)
    rounded(draw, fail_box, "#FFEBEE", "#C62828")
    center_text(draw, fail_box, "任一项为假：\n工作区待修复", SMALL)
    arrow(draw, (ok_box[2], decision[3]), (scale(420), ok_box[1]), "#2E7D32")
    arrow(draw, (fail_box[0], decision[3]), (scale(1035), fail_box[1]), "#C62828")

    image.save(OUT / "chapter-03-readiness-switches.png", dpi=(PRINT_DPI, PRINT_DPI))


def add_cell(
    root: ET.Element,
    cell_id: str,
    value: str,
    style: str,
    x: int,
    y: int,
    w: int,
    h: int,
) -> None:
    cell = ET.SubElement(
        root,
        "mxCell",
        {
            "id": cell_id,
            "value": value,
            "style": style,
            "vertex": "1",
            "parent": "1",
        },
    )
    ET.SubElement(
        cell,
        "mxGeometry",
        {"x": str(x), "y": str(y), "width": str(w), "height": str(h), "as": "geometry"},
    )


def add_edge(
    root: ET.Element,
    edge_id: str,
    source: str,
    target: str,
    value: str = "",
    color: str = "#6B7A90",
) -> None:
    edge = ET.SubElement(
        root,
        "mxCell",
        {
            "id": edge_id,
            "value": value,
            "style": (
                "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
                f"jettySize=auto;html=1;endArrow=classic;strokeColor={color};"
                "strokeWidth=4;fontSize=16;fontColor=#607086;"
            ),
            "edge": "1",
            "parent": "1",
            "source": source,
            "target": target,
        },
    )
    ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})


def write_readiness_switches_drawio() -> None:
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "modified": "2026-06-19T00:00:00.000Z",
            "agent": "ashare-research-sandbox",
            "version": "24.7.17",
            "type": "device",
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"id": "chapter-03-readiness-switches", "name": "图 3-3 工作区就绪四开关"})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1440",
            "dy": "810",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": str(WIDTH),
            "pageHeight": str(HEIGHT),
            "background": BG,
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    text_style = "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;rounded=0;"
    add_cell(root, "title", "工作区就绪四开关", text_style + "fontSize=42;fontColor=#102033;fontStyle=1;", 70, 45, 650, 70)
    add_cell(
        root,
        "subtitle",
        "四项同时为真，才能写“工作区可交接”；任一项为假，就退回补记录。",
        text_style + "fontSize=22;fontColor=#607086;",
        72,
        105,
        950,
        40,
    )

    box_style = "rounded=1;whiteSpace=wrap;html=1;arcSize=10;fontSize=22;fontColor=#102033;strokeWidth=4;"
    add_cell(root, "path_ok", "path_ok<br>根目录、脚本、模板<br>可定位", box_style + "fillColor=#E8F1FF;strokeColor=#2563EB;", 90, 240, 250, 150)
    add_cell(root, "sample_ok", "sample_ok<br>假设卡样本<br>仍然存在", box_style + "fillColor=#E7F8F3;strokeColor=#0F9B8E;", 420, 240, 250, 150)
    add_cell(root, "command_ok", "command_ok<br>命令真实运行<br>保留退出结果", box_style + "fillColor=#FFF4DB;strokeColor=#D97706;", 750, 240, 250, 150)
    add_cell(root, "limitation_ok", "limitation_ok<br>离线路径与增强路径<br>分开说明", box_style + "fillColor=#F5ECFF;strokeColor=#7C3AED;", 1080, 240, 250, 150)

    add_cell(
        root,
        "formula",
        "workspace_ready =<br>path_ok and sample_ok and<br>command_ok and limitation_ok",
        box_style + "fillColor=#FFFFFF;strokeColor=#111827;",
        360,
        470,
        720,
        110,
    )
    add_cell(root, "ready", "四项都成立：<br>工作区可交接", box_style + "fillColor=#E8F5E9;strokeColor=#2E7D32;", 210, 650, 390, 80)
    add_cell(root, "repair", "任一项为假：<br>工作区待修复", box_style + "fillColor=#FFEBEE;strokeColor=#C62828;", 840, 650, 390, 80)

    add_edge(root, "e_path_sample", "path_ok", "sample_ok", "and")
    add_edge(root, "e_sample_command", "sample_ok", "command_ok", "and")
    add_edge(root, "e_command_limitation", "command_ok", "limitation_ok", "and")
    add_edge(root, "e_path_formula", "path_ok", "formula")
    add_edge(root, "e_sample_formula", "sample_ok", "formula")
    add_edge(root, "e_command_formula", "command_ok", "formula")
    add_edge(root, "e_limitation_formula", "limitation_ok", "formula")
    add_edge(root, "e_formula_ready", "formula", "ready", color="#2E7D32")
    add_edge(root, "e_formula_repair", "formula", "repair", color="#C62828")

    tree = ET.ElementTree(mxfile)
    ET.indent(tree, space="  ")
    DRAWIO_OUT.parent.mkdir(parents=True, exist_ok=True)
    tree.write(DRAWIO_OUT, encoding="unicode", xml_declaration=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    repository_map()
    readiness_switches()
    write_readiness_switches_drawio()


if __name__ == "__main__":
    main()
