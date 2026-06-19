#!/usr/bin/env python3
"""Generate supplementary chapter flowchart PNGs and draw.io source pages."""

from __future__ import annotations

import copy
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from print_figure_config import PRINT_DPI, scale

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "v2" / "assets"
DRAWIO_OUT = ASSETS / "chapters-03-20-supplementary.drawio"

WIDTH, HEIGHT = 1440, 810
BG = "#F7F8FB"
TITLE_COLOR = "#101A33"
SUB_COLOR = "#596983"
ARROW = "#63738C"

BOX_STYLES = {
    "step": ("#FFFFFF", "#2563EB"),
    "step2": ("#FFFFFF", "#0891B2"),
    "step3": ("#FFFFFF", "#0F9B8E"),
    "warn": ("#FFFFFF", "#F59E0B"),
    "ok": ("#E8F5E9", "#2E7D32"),
    "fail": ("#FFEBEE", "#C62828"),
    "decision": ("#F5F5F5", "#616161"),
}

STYLE_TO_DRAWIO = {
    "step": "#2563EB",
    "step2": "#0891B2",
    "step3": "#0F9B8E",
    "warn": "#F59E0B",
    "ok": "#2E7D32",
    "fail": "#C62828",
    "decision": "#616161",
}


def _font_candidates() -> list[Path]:
    windir = Path("C:/Windows/Fonts")
    names = [
        "msyh.ttc",
        "msyhbd.ttc",
        "simhei.ttf",
        "simsun.ttc",
        "arial.ttf",
    ]
    paths = [windir / name for name in names if (windir / name).is_file()]
    paths.append(Path("arial.ttf"))
    return paths


def _load_font(size: int):
    for path in _font_candidates():
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def scale_diagram_spec(source: dict) -> dict:
    spec = copy.deepcopy(source)
    if canvas := spec.get("canvas"):
        spec["canvas"] = (scale(canvas[0]), scale(canvas[1]))
    if title_xy := spec.get("title_xy"):
        spec["title_xy"] = (scale(title_xy[0]), scale(title_xy[1]))
    if subtitle_xy := spec.get("subtitle_xy"):
        spec["subtitle_xy"] = (scale(subtitle_xy[0]), scale(subtitle_xy[1]))
    if footer_box := spec.get("footer_box"):
        spec["footer_box"] = tuple(scale(value) for value in footer_box)
    if footer_text_xy := spec.get("footer_text_xy"):
        spec["footer_text_xy"] = (scale(footer_text_xy[0]), scale(footer_text_xy[1]))
    for node in spec.get("nodes", []):
        x, y, w, h = node["box"]
        node["box"] = (scale(x), scale(y), scale(w), scale(h))
    for edge in spec.get("edges", []):
        if edge["kind"] == "h":
            x1, y, x2 = edge["coords"]
            edge["coords"] = (scale(x1), scale(y), scale(x2))
        else:
            x, y1, y2 = edge["coords"]
            edge["coords"] = (scale(x), scale(y1), scale(y2))
    return spec


def load_fonts() -> tuple:
    return _load_font(scale(34)), _load_font(scale(20)), _load_font(scale(22)), _load_font(scale(18))


def compact_spec(source: dict) -> dict:
    """Fit the shared diagram layout around its actual teaching content."""
    spec = copy.deepcopy(source)
    if spec.get("compact") is False or not spec.get("nodes"):
        return spec

    nodes = spec["nodes"]
    shift_y = 175 - min(node["box"][1] for node in nodes)
    for node in nodes:
        x, y, w, h = node["box"]
        node["box"] = (x, y + shift_y, w, h)

    for edge in spec.get("edges", []):
        if edge["kind"] == "h":
            x1, y, x2 = edge["coords"]
            edge["coords"] = (x1, y + shift_y, x2)
        else:
            x, y1, y2 = edge["coords"]
            edge["coords"] = (x, y1 + shift_y, y2 + shift_y)

    max_right = max(node["box"][0] + node["box"][2] for node in nodes)
    max_bottom = max(node["box"][1] + node["box"][3] for node in nodes)
    canvas_width = max(1080, min(WIDTH, max_right + 50))

    if spec.get("footer"):
        footer_width = min(840, canvas_width - 180)
        footer_left = (canvas_width - footer_width) // 2
        footer_top = max_bottom + 45
        spec["footer_box"] = (footer_left, footer_top, footer_left + footer_width, footer_top + 75)
        spec["footer_text_xy"] = (footer_left + 30, footer_top + 22)
        canvas_height = footer_top + 115
    else:
        canvas_height = max_bottom + 60

    spec["canvas"] = (canvas_width, canvas_height)
    spec["title_xy"] = (60, 35)
    spec["subtitle_xy"] = (60, 82)
    return spec


def wrap(text: str, width: int = 10) -> str:
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        width = min(width, 8)
    return "\n".join(textwrap.wrap(text, width=width))


def draw_box(
    draw: ImageDraw.ImageDraw,
    xywh: tuple[int, int, int, int],
    text: str,
    style: str,
    font,
    radius: int = 14,
) -> None:
    x, y, w, h = xywh
    fill, stroke = BOX_STYLES[style]
    if style == "decision":
        cx, cy = x + w // 2, y + h // 2
        pts = [(cx, y), (x + w, cy), (cx, y + h), (x, cy)]
        draw.polygon(pts, fill=fill, outline=stroke, width=4)
    else:
        draw.rounded_rectangle((x, y, x + w, y + h), radius=radius, outline=stroke, width=4, fill=fill)
    bbox = draw.multiline_textbbox((0, 0), wrap(text), font=font, spacing=6, align="center")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.multiline_text(
        (x + (w - tw) // 2, y + (h - th) // 2),
        wrap(text),
        fill=TITLE_COLOR,
        font=font,
        spacing=6,
        align="center",
    )


def arrow_h(draw, x1, y, x2, label: str | None = None, font=None) -> None:
    draw.line((x1, y, x2, y), fill=ARROW, width=4)
    draw.polygon([(x2, y), (x2 - 12, y - 7), (x2 - 12, y + 7)], fill=ARROW)
    if label and font:
        draw.text(((x1 + x2) // 2 - 10, y - 28), label, fill=SUB_COLOR, font=font)


def arrow_v(draw, x, y1, y2, label: str | None = None, font=None) -> None:
    draw.line((x, y1, x, y2), fill=ARROW, width=4)
    draw.polygon([(x, y2), (x - 7, y2 - 12), (x + 7, y2 - 12)], fill=ARROW)
    if label and font:
        draw.text((x + 12, (y1 + y2) // 2 - 10), label, fill=SUB_COLOR, font=font)


def render_diagram(spec: dict, output: Path) -> None:
    spec = scale_diagram_spec(compact_spec(spec))
    title_font, sub_font, body_font, small_font = load_fonts()
    width, height = spec.get("canvas", (WIDTH, HEIGHT))
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    title_xy = spec.get("title_xy", (80, 48))
    subtitle_xy = spec.get("subtitle_xy", (80, 98))
    draw.text(title_xy, spec["title"], fill=TITLE_COLOR, font=title_font)
    draw.text(subtitle_xy, spec.get("subtitle", ""), fill=SUB_COLOR, font=sub_font)

    for node in spec["nodes"]:
        draw_box(draw, node["box"], node["text"], node["style"], body_font)
    for edge in spec.get("edges", []):
        label = edge.get("label")
        if edge["kind"] == "h":
            x1, y, x2 = edge["coords"]
            arrow_h(draw, x1, y, x2, label, small_font)
        else:
            x, y1, y2 = edge["coords"]
            arrow_v(draw, x, y1, y2, label, small_font)
    if foot := spec.get("footer"):
        footer_box = spec.get("footer_box", (300, 690, 1140, 770))
        footer_text_xy = spec.get("footer_text_xy", (330, 712))
        draw.rounded_rectangle(footer_box, radius=12, fill="#101A33")
        draw.text(footer_text_xy, foot, fill="#FFFFFF", font=body_font)

    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, dpi=(PRINT_DPI, PRINT_DPI))


def h_edges(*pairs: tuple[int, int, int], labels: dict[int, str] | None = None) -> list[dict]:
    labels = labels or {}
    return [
        {"kind": "h", "coords": pair, "label": labels.get(i)}
        for i, pair in enumerate(pairs)
    ]


def lane(
    x: int,
    y: int,
    w: int,
    h: int,
    texts: list[str],
    styles: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    styles = styles or ["step", "step2", "step3", "warn", "ok"] * 3
    gap = 20
    nodes = []
    edges = []
    cx = x
    for i, text in enumerate(texts):
        style = styles[i % len(styles)]
        nodes.append({"box": (cx, y, w, h), "text": text, "style": style})
        if i > 0:
            prev = nodes[i - 1]["box"]
            edges.append({"kind": "h", "coords": (prev[0] + prev[2], y + h // 2, cx)})
        cx += w + gap
    return nodes, edges


DIAGRAMS: dict[str, dict] = {
    "chapter-01-idea-layers.png": {
        "title": "从愿望到可执行任务的层次",
        "subtitle": "每一层往下收，都要有人确认——不能靠 Codex 猜",
        "page": "图1-1 愿望到任务",
        "canvas": (1080, 520),
        "title_xy": (60, 35),
        "subtitle_xy": (60, 82),
        "nodes": [
            {"box": (40, 180, 160, 110), "text": "愿望\n「做个研究工具」", "style": "step"},
            {"box": (230, 180, 160, 110), "text": "用户问题\n为谁、什么场景？", "style": "step2"},
            {"box": (420, 180, 160, 110), "text": "方案偏好\nWeb3 / 页面 / 回测", "style": "step3"},
            {"box": (610, 180, 160, 110), "text": "功能清单\n来源卡、指标…", "style": "warn"},
            {"box": (800, 180, 180, 110), "text": "可委托任务\n用户+边界+验收", "style": "ok"},
        ],
        "edges": h_edges((200, 235, 225), (390, 235, 415), (580, 235, 605), (770, 235, 795)),
        "footer": "在愿望层就写代码，等于把最窄层的形状交给模型猜。",
        "footer_box": (180, 365, 900, 440),
        "footer_text_xy": (210, 387),
    },
    "chapter-01-assumption-chain.png": {
        "title": "猜题链：未确认假设的级联影响",
        "subtitle": "链条顶端改假设成本低，实现末端才发现错了代价高",
        "page": "图1-2 猜题链",
        "nodes": [
            {"box": (40, 310, 170, 100), "text": "用户未确认", "style": "step"},
            {"box": (240, 310, 170, 100), "text": "数据来源被猜", "style": "step2"},
            {"box": (440, 310, 170, 100), "text": "功能范围膨胀", "style": "step3"},
            {"box": (640, 310, 170, 100), "text": "权限越界", "style": "warn"},
            {"box": (840, 310, 170, 100), "text": "验收无法通过", "style": "fail"},
            {"box": (1040, 310, 170, 100), "text": "推倒重来", "style": "fail"},
        ],
        "edges": h_edges((210, 360, 235), (410, 360, 435), (610, 360, 635), (810, 360, 835), (1010, 360, 1035)),
        "footer": "一条未确认的假设，会级联影响数据、功能、权限与验收。",
    },
    "chapter-02-brief-conversion.png": {
        "title": "从自然请求到可委托 Brief",
        "subtitle": "每一次填写都在减少一种猜测",
        "page": "图2-1 Brief 转换",
        "nodes": [
            {"box": (30, 310, 150, 100), "text": "自然语言请求", "style": "step"},
            {"box": (210, 310, 130, 100), "text": "决策目标", "style": "step2"},
            {"box": (370, 310, 120, 100), "text": "用户", "style": "step3"},
            {"box": (520, 310, 120, 100), "text": "边界", "style": "warn"},
            {"box": (670, 310, 140, 100), "text": "Done when", "style": "step2"},
            {"box": (840, 310, 140, 100), "text": "开放问题", "style": "step3"},
            {"box": (1010, 310, 150, 100), "text": "可委托 Brief", "style": "ok"},
        ],
        "edges": h_edges((180, 360, 205), (340, 360, 365), (490, 360, 515), (640, 360, 665), (810, 360, 835), (980, 360, 1005)),
        "footer": "Brief 不是更长提示词，而是可执行、可验收、可接手的任务合同。",
    },
    "chapter-02-brief-contract.png": {
        "title": "Brief 五要素互相约束",
        "subtitle": "缺一项，任务就会在对话中漂移",
        "page": "图2-2 Brief 合同",
        "nodes": [
            {"box": (120, 280, 200, 100), "text": "目标\n服务什么决定？", "style": "step"},
            {"box": (400, 280, 200, 100), "text": "用户\n为谁服务？", "style": "step2"},
            {"box": (680, 280, 200, 100), "text": "边界\n做什么/不做什么", "style": "step3"},
            {"box": (120, 480, 200, 100), "text": "完成标准\n怎样算 Done", "style": "warn"},
            {"box": (680, 480, 200, 100), "text": "开放问题\n未知与停止", "style": "fail"},
        ],
        "edges": [
            {"kind": "h", "coords": (320, 330, 395)},
            {"kind": "h", "coords": (600, 330, 675)},
            {"kind": "v", "coords": (220, 380, 475)},
            {"kind": "v", "coords": (780, 380, 475)},
        ],
        "footer": "五要素共同限制范围膨胀、证据缺失与权限越界。",
    },
    "chapter-03-evidence-ladder.png": {
        "title": "证明责任阶梯",
        "subtitle": "每一层升级都需要承担新的证明义务",
        "page": "图3-1 证明阶梯",
        "nodes": [
            {"box": (80, 310, 150, 100), "text": "来源", "style": "step"},
            {"box": (260, 310, 150, 100), "text": "事实 Facts", "style": "step2"},
            {"box": (440, 310, 150, 100), "text": "推断 Inferences", "style": "step3"},
            {"box": (620, 310, 150, 100), "text": "建议 Recommendations", "style": "warn"},
            {"box": (800, 310, 150, 100), "text": "产品决定", "style": "ok"},
            {"box": (980, 310, 170, 100), "text": "人工签字", "style": "ok"},
        ],
        "edges": h_edges((230, 360, 255), (410, 360, 435), (590, 360, 615), (770, 360, 795), (950, 360, 975)),
        "footer": "跳过中间层，就是把推断写成事实。",
    },
    "chapter-03-acceptance-gates.png": {
        "title": "调研验收三道门",
        "subtitle": "停止与通过同等重要",
        "page": "图3-2 验收门",
        "nodes": [
            {"box": (80, 310, 180, 100), "text": "调研产出", "style": "step"},
            {"box": (300, 310, 170, 100), "text": "证据足够？", "style": "decision"},
            {"box": (520, 250, 180, 100), "text": "通过→下一阶段", "style": "ok"},
            {"box": (520, 420, 180, 100), "text": "拒绝→修订", "style": "fail"},
            {"box": (520, 560, 180, 100), "text": "停止→不再投入", "style": "fail"},
            {"box": (760, 250, 200, 100), "text": "记录 Unknowns", "style": "warn"},
        ],
        "edges": h_edges((260, 360, 295), (700, 300, 755))
        + [{"kind": "h", "coords": (470, 300, 515), "label": "是"}, {"kind": "v", "coords": (385, 410, 415), "label": "否"}, {"kind": "v", "coords": (385, 470, 555), "label": "触发停止线"}],
        "footer": "及时停止错误方向，比产出长报告更有价值。",
    },
    "chapter-04-context-layers.png": {
        "title": "上下文包六层分级",
        "subtitle": "每项材料服务验收合同中的明确条款",
        "page": "图4-1 资料分级",
        "nodes": [
            {"box": (40, 280, 200, 90), "text": "正式任务\nBrief/验收", "style": "step"},
            {"box": (270, 280, 200, 90), "text": "事实样本\ndata/", "style": "step2"},
            {"box": (500, 280, 200, 90), "text": "规则\nAGENTS.md", "style": "step3"},
            {"box": (730, 280, 200, 90), "text": "只读上游\nvendor/", "style": "warn"},
            {"box": (270, 430, 200, 90), "text": "背景参考\n文档链接", "style": "step2"},
            {"box": (500, 430, 200, 90), "text": "禁止进入\n密钥/账户", "style": "fail"},
        ],
        "edges": h_edges((240, 325, 265), (470, 325, 495), (700, 325, 725)),
        "footer": "无法映射到验收条件的材料，不应进入工作区。",
    },
    "chapter-04-context-mapping.png": {
        "title": "从验收条件反推资料",
        "subtitle": "无法映射的标准可能不可执行",
        "page": "图4-2 资料映射",
        "nodes": [
            {"box": (80, 310, 200, 100), "text": "验收：Facts 有来源", "style": "step"},
            {"box": (320, 310, 200, 100), "text": "→ research-report\n+ data/", "style": "ok"},
            {"box": (560, 310, 200, 100), "text": "验收：策略可复现", "style": "step2"},
            {"box": (800, 310, 200, 100), "text": "→ src/ + verify", "style": "ok"},
            {"box": (1040, 310, 200, 100), "text": "无映射？", "style": "decision"},
        ],
        "edges": h_edges((280, 360, 315), (520, 360, 555), (760, 360, 795), (1000, 360, 1035)),
        "footer": "先写验收条款，再决定读哪些文件——不是反过来。",
    },
    "chapter-05-entry-decision.png": {
        "title": "任务能力到入口选择",
        "subtitle": "入口 = 能力 + 风险，不是个人习惯",
        "page": "图5-1 入口决策",
        "nodes": [
            {"box": (60, 310, 170, 100), "text": "列出能力需求", "style": "step"},
            {"box": (260, 310, 170, 100), "text": "只需概念评审？", "style": "decision"},
            {"box": (260, 480, 170, 100), "text": "对话入口", "style": "ok"},
            {"box": (480, 310, 170, 100), "text": "需读写仓库？", "style": "decision"},
            {"box": (480, 480, 170, 100), "text": "工作区入口", "style": "ok"},
            {"box": (700, 310, 170, 100), "text": "需跑 verify？", "style": "decision"},
            {"box": (700, 480, 170, 100), "text": "终端入口", "style": "ok"},
            {"box": (920, 310, 170, 100), "text": "需验 UI？", "style": "decision"},
            {"box": (920, 480, 170, 100), "text": "浏览器入口", "style": "ok"},
        ],
        "edges": [
            {"kind": "h", "coords": (230, 360, 255)},
            {"kind": "v", "coords": (345, 410, 475), "label": "是"},
            {"kind": "h", "coords": (430, 360, 475), "label": "否"},
            {"kind": "v", "coords": (565, 410, 475), "label": "是"},
            {"kind": "h", "coords": (650, 360, 695), "label": "否"},
            {"kind": "v", "coords": (785, 410, 475), "label": "是"},
            {"kind": "h", "coords": (870, 360, 915), "label": "否"},
        ],
        "footer": "审查 Brief 与改代码并 verify，往往需要不同入口组合。",
    },
    "chapter-05-workspace-boundary.png": {
        "title": "受控工作区边界",
        "subtitle": "规则写在文件里，证据留在命令输出里",
        "page": "图5-2 工作区",
        "nodes": [
            {"box": (60, 310, 160, 100), "text": "AGENTS.md\n规则", "style": "step"},
            {"box": (250, 310, 160, 100), "text": "Brief\n任务", "style": "step2"},
            {"box": (440, 310, 160, 100), "text": "src/\n可写", "style": "step3"},
            {"box": (630, 310, 160, 100), "text": "vendor/\n只读", "style": "warn"},
            {"box": (820, 310, 160, 100), "text": "verify\n证据", "style": "ok"},
            {"box": (1010, 310, 160, 100), "text": "Handoff\n接手", "style": "ok"},
        ],
        "edges": h_edges((220, 360, 245), (410, 360, 435), (600, 360, 625), (790, 360, 815), (980, 360, 1005)),
        "footer": "新会话、Automation 与人都应读到同一套边界。",
    },
    "chapter-06-claim-flow.png": {
        "title": "主张流转：F/I/R/U",
        "subtitle": "箭头只能向上游走，不能反向升级证据",
        "page": "图6-1 主张流转",
        "nodes": [
            {"box": (80, 310, 180, 100), "text": "Facts\n可复查事实", "style": "step"},
            {"box": (320, 310, 180, 100), "text": "Inferences\n标明 Supports", "style": "step2"},
            {"box": (560, 310, 180, 100), "text": "Recommendations\n行动边界", "style": "step3"},
            {"box": (800, 310, 180, 100), "text": "人工 Go/Revise", "style": "ok"},
            {"box": (320, 480, 180, 100), "text": "Unknowns\n缺信息停止", "style": "fail"},
        ],
        "edges": h_edges((260, 360, 315), (500, 360, 555), (740, 360, 795))
        + [{"kind": "v", "coords": (170, 410, 475)}],
        "footer": "建议伪装成事实，是调研报告最常见的语义污染。",
    },
    "chapter-06-research-rounds.png": {
        "title": "分轮调研阻止证据升级",
        "subtitle": "一步生成最终报告，最容易一次性污染全文",
        "page": "图6-2 分轮调研",
        "nodes": [
            {"box": (60, 310, 200, 100), "text": "第1轮：Facts\n只确认事实", "style": "step"},
            {"box": (300, 310, 200, 100), "text": "第2轮：Inferences\n回连 F", "style": "step2"},
            {"box": (540, 310, 220, 100), "text": "第3轮：R + Unknowns", "style": "step3"},
            {"box": (800, 310, 180, 100), "text": "证据审查", "style": "warn"},
            {"box": (1020, 310, 180, 100), "text": "决策包", "style": "ok"},
        ],
        "edges": h_edges((260, 360, 295), (500, 360, 535), (760, 360, 795), (980, 360, 1015)),
        "footer": "第一轮就写建议，应拒绝并要求先完成 F 列表。",
    },
    "chapter-07-decision-path.png": {
        "title": "从证据到方向决定",
        "subtitle": "调研的终点是决定，不是报告",
        "page": "图7-1 方向决定",
        "nodes": [
            {"box": (60, 310, 170, 100), "text": "主张台账", "style": "step"},
            {"box": (260, 310, 170, 100), "text": "对照 Brief", "style": "step2"},
            {"box": (460, 310, 170, 100), "text": "三种方向？", "style": "decision"},
            {"box": (660, 250, 130, 100), "text": "Go", "style": "ok"},
            {"box": (660, 380, 130, 100), "text": "Revise", "style": "warn"},
            {"box": (660, 510, 130, 100), "text": "No-Go", "style": "fail"},
            {"box": (830, 310, 200, 100), "text": "决策记录\n+ 停止线", "style": "ok"},
        ],
        "edges": h_edges((230, 360, 255), (430, 360, 455), (790, 360, 825))
        + [{"kind": "h", "coords": (590, 300, 655), "label": "选向"}, {"kind": "v", "coords": (545, 410, 505), "label": "R"}, {"kind": "v", "coords": (545, 410, 375), "label": "G"}],
        "footer": "默认 Go 等于把风险留到实现末端。",
    },
    "chapter-07-reversible-decision.png": {
        "title": "可撤销的方向决定",
        "subtitle": "附带复核日期与触发条件，而不是一次性盖章",
        "page": "图7-2 可撤销决定",
        "nodes": [
            {"box": (80, 310, 180, 100), "text": "Go 决定", "style": "ok"},
            {"box": (300, 310, 180, 100), "text": "写入停止线", "style": "warn"},
            {"box": (520, 310, 180, 100), "text": "触发条件出现？", "style": "decision"},
            {"box": (740, 250, 180, 100), "text": "继续执行", "style": "ok"},
            {"box": (740, 420, 180, 100), "text": "Revise/No-Go", "style": "fail"},
            {"box": (980, 310, 180, 100), "text": "更新决策记录", "style": "step3"},
        ],
        "edges": h_edges((260, 360, 295), (480, 360, 515), (920, 360, 975))
        + [{"kind": "h", "coords": (700, 300, 735), "label": "否"}, {"kind": "v", "coords": (610, 410, 415), "label": "是"}],
        "footer": "若必须 live 才能验收，应重新进入调研与审批。",
    },
    "chapter-08-stakeholders.png": {
        "title": "四类相关角色",
        "subtitle": "验收对齐使用者，边界由风险承担者批准",
        "page": "图8-1 相关角色",
        "nodes": [
            {"box": (80, 280, 200, 110), "text": "提出需求者\n「做个工具」", "style": "step"},
            {"box": (320, 280, 200, 110), "text": "实际使用者\n读来源/跑回测", "style": "step2"},
            {"box": (560, 280, 200, 110), "text": "风险承担者\n合规/误导", "style": "warn"},
            {"box": (800, 280, 200, 110), "text": "方向决策者\nGo/Revise", "style": "ok"},
        ],
        "edges": h_edges((280, 335, 315), (520, 335, 555), (760, 335, 795)),
        "footer": "提出者的功能愿望不能自动等于使用者的问题。",
    },
    "chapter-08-user-convergence.png": {
        "title": "从调研证据收敛核心用户",
        "subtitle": "排除交易建议场景，锁定学习研究方法的学习者",
        "page": "图8-2 用户收敛",
        "nodes": [
            {"box": (60, 310, 170, 100), "text": "F2 可复查流程", "style": "step"},
            {"box": (260, 310, 190, 100), "text": "排除荐股场景", "style": "step2"},
            {"box": (480, 310, 200, 100), "text": "锁定学习者", "style": "step3"},
            {"box": (710, 310, 180, 100), "text": "写入 Brief/PRD", "style": "ok"},
            {"box": (930, 310, 170, 100), "text": "验收对齐", "style": "ok"},
        ],
        "edges": h_edges((230, 360, 255), (450, 360, 475), (680, 360, 705), (890, 360, 925)),
        "footer": "「所有人都能用」等于还没有用户。",
    },
    "chapter-09-problem-funnel.png": {
        "title": "从功能请求到真实问题",
        "subtitle": "先问为什么，再问做什么功能",
        "page": "图9-1 问题漏斗",
        "nodes": [
            {"box": (80, 310, 180, 100), "text": "功能请求\n「要回测页」", "style": "step"},
            {"box": (300, 310, 180, 100), "text": "用户想完成什么？", "style": "step2"},
            {"box": (520, 310, 180, 100), "text": "什么在阻碍？", "style": "step3"},
            {"box": (740, 310, 180, 100), "text": "真实用户问题", "style": "ok"},
            {"box": (960, 310, 170, 100), "text": "PRD 问题陈述", "style": "ok"},
        ],
        "edges": h_edges((260, 360, 295), (480, 360, 515), (700, 360, 735), (920, 360, 955)),
        "footer": "功能清单是方案，不是问题定义。",
    },
    "chapter-09-problem-structure.png": {
        "title": "问题定义四要素",
        "subtitle": "任务、阻碍、期望结果与失败风险",
        "page": "图9-2 问题结构",
        "nodes": [
            {"box": (120, 280, 220, 110), "text": "任务\n用户要完成什么", "style": "step"},
            {"box": (400, 280, 220, 110), "text": "阻碍\n现在卡在哪里", "style": "step2"},
            {"box": (680, 280, 220, 110), "text": "结果\n怎样算更好", "style": "step3"},
            {"box": (400, 480, 220, 110), "text": "风险\n误解后果", "style": "fail"},
        ],
        "edges": [
            {"kind": "h", "coords": (340, 335, 395)},
            {"kind": "h", "coords": (620, 335, 675)},
            {"kind": "v", "coords": (510, 390, 475)},
        ],
        "footer": "没有风险描述的问题定义，容易滑向功能堆叠。",
    },
    "chapter-10-solution-space.png": {
        "title": "从问题到候选方案",
        "subtitle": "先展开再收敛，避免爱上第一个想法",
        "page": "图10-1 方案空间",
        "nodes": [
            {"box": (60, 310, 160, 100), "text": "问题定义", "style": "step"},
            {"box": (250, 250, 130, 100), "text": "方案 A", "style": "step2"},
            {"box": (250, 370, 130, 100), "text": "方案 B", "style": "step2"},
            {"box": (250, 490, 130, 100), "text": "方案 C", "style": "step3"},
            {"box": (430, 310, 180, 100), "text": "统一维度比较", "style": "warn"},
            {"box": (650, 310, 180, 100), "text": "选定方向", "style": "ok"},
            {"box": (870, 310, 180, 100), "text": "写入 PRD", "style": "ok"},
        ],
        "edges": h_edges((410, 360, 425), (610, 360, 645), (830, 360, 865)),
        "footer": "比较的是 tradeoff，不是口号。",
    },
    "chapter-10-tradeoff-triangle.png": {
        "title": "方案选择三角",
        "subtitle": "价值、风险与可验证性必须同时看",
        "page": "图10-2 权衡三角",
        "nodes": [
            {"box": (320, 250, 200, 100), "text": "用户/教学价值", "style": "step"},
            {"box": (120, 480, 200, 100), "text": "风险与合规", "style": "fail"},
            {"box": (520, 480, 200, 100), "text": "可验证性\nverify/样本", "style": "ok"},
            {"box": (320, 480, 200, 100), "text": "第一版选择", "style": "warn"},
        ],
        "edges": [
            {"kind": "v", "coords": (420, 350, 475)},
            {"kind": "h", "coords": (220, 530, 315)},
            {"kind": "h", "coords": (520, 530, 615)},
        ],
        "footer": "live 交易往往价值高但风险与可验证性差。",
    },
    "chapter-11-mvp-loop.png": {
        "title": "最小完整用户闭环",
        "subtitle": "MVP 是闭环，不是功能残片",
        "page": "图11-1 MVP 闭环",
        "nodes": [
            {"box": (40, 310, 150, 100), "text": "打开资产页", "style": "step"},
            {"box": (220, 310, 150, 100), "text": "读来源卡", "style": "step2"},
            {"box": (400, 310, 150, 100), "text": "设参数", "style": "step3"},
            {"box": (580, 310, 150, 100), "text": "跑回测", "style": "warn"},
            {"box": (760, 310, 150, 100), "text": "看指标", "style": "step2"},
            {"box": (940, 310, 170, 100), "text": "解释限制", "style": "ok"},
        ],
        "edges": h_edges((190, 360, 215), (370, 360, 395), (550, 360, 575), (730, 360, 755), (910, 360, 935)),
        "footer": "缺「解释限制」一环，就不是课程 MVP。",
    },
    "chapter-11-scope-boundary.png": {
        "title": "第一版范围边界",
        "subtitle": "非目标是护栏，不是「以后不做」",
        "page": "图11-2 范围边界",
        "nodes": [
            {"box": (80, 280, 220, 110), "text": "In scope\n固定样本竖切", "style": "ok"},
            {"box": (360, 280, 220, 110), "text": "Out of scope\nlive/交易", "style": "fail"},
            {"box": (640, 280, 220, 110), "text": "需审批扩展\nDashboard live", "style": "warn"},
            {"box": (920, 280, 200, 110), "text": "Prohibited\n荐股/密钥", "style": "fail"},
        ],
        "edges": h_edges((300, 335, 355), (580, 335, 635), (860, 335, 915)),
        "footer": "实现与用户测试期间，非目标防止范围膨胀。",
    },
    "chapter-12-prd-review.png": {
        "title": "PRD 审查闭环",
        "subtitle": "Codex 提发现，人做产品决定",
        "page": "图12-1 PRD 审查",
        "nodes": [
            {"box": (80, 310, 170, 100), "text": "prd.md", "style": "step"},
            {"box": (290, 310, 170, 100), "text": "Codex 审查", "style": "step2"},
            {"box": (500, 310, 170, 100), "text": "发现清单", "style": "step3"},
            {"box": (710, 310, 170, 100), "text": "人批准/拒绝", "style": "warn"},
            {"box": (920, 310, 170, 100), "text": "修订 PRD", "style": "ok"},
        ],
        "edges": h_edges((250, 360, 285), (460, 360, 495), (670, 360, 705), (880, 360, 915)),
        "footer": "审查不是替你做 Go/No-Go。",
    },
    "chapter-12-stress-test.png": {
        "title": "PRD 压力测试",
        "subtitle": "正常路径 + 边界滥用 + 停止线",
        "page": "图12-2 压力测试",
        "nodes": [
            {"box": (80, 310, 180, 100), "text": "核心用户路径", "style": "step"},
            {"box": (300, 310, 180, 100), "text": "边界场景", "style": "warn"},
            {"box": (520, 310, 180, 100), "text": "滥用/越界？", "style": "decision"},
            {"box": (740, 250, 180, 100), "text": "PRD 仍成立", "style": "ok"},
            {"box": (740, 420, 180, 100), "text": "补禁止项/停止", "style": "fail"},
        ],
        "edges": h_edges((260, 360, 295), (480, 360, 515))
        + [{"kind": "h", "coords": (700, 300, 735), "label": "否"}, {"kind": "v", "coords": (610, 410, 415), "label": "是"}],
        "footer": "「用户想要 live」是压力测试，不是默认需求。",
    },
    "chapter-13-slice-vs-module.png": {
        "title": "模块切分 vs 用户竖切",
        "subtitle": "忙碌不等于用户能完成任务",
        "page": "图13-1 竖切对照",
        "nodes": [
            {"box": (60, 250, 200, 90), "text": "横向：API 层", "style": "step"},
            {"box": (60, 360, 200, 90), "text": "横向：前端层", "style": "step2"},
            {"box": (60, 470, 200, 90), "text": "横向：联调", "style": "step3"},
            {"box": (320, 310, 220, 110), "text": "竖切：data→\nresearch→web", "style": "ok"},
            {"box": (580, 310, 200, 110), "text": "用户可见结果", "style": "ok"},
            {"box": (820, 310, 200, 110), "text": "verify 证据", "style": "ok"},
        ],
        "edges": h_edges((540, 360, 575), (780, 360, 815)),
        "footer": "第一刀问：学习者离可验收证据更近了吗？",
    },
    "chapter-13-user-loop.png": {
        "title": "主案例用户闭环",
        "subtitle": "从虚构资产页到解释限制",
        "page": "图13-2 用户闭环",
        "nodes": [
            {"box": (40, 310, 150, 100), "text": "起点\n/trading", "style": "step"},
            {"box": (220, 310, 150, 100), "text": "读摘要", "style": "step2"},
            {"box": (400, 310, 150, 100), "text": "调窗口", "style": "step3"},
            {"box": (580, 310, 150, 100), "text": "触发回测", "style": "warn"},
            {"box": (760, 310, 150, 100), "text": "看 warnings", "style": "step2"},
            {"box": (940, 310, 170, 100), "text": "可验收完成", "style": "ok"},
        ],
        "edges": h_edges((190, 360, 215), (370, 360, 395), (550, 360, 575), (730, 360, 755), (910, 360, 935)),
        "footer": "竖切写入 plan.md 第一条里程碑。",
    },
    "chapter-00-delivery-chain.png": {
        "title": "从模糊想法到 Playbook 的交付链",
        "subtitle": "进度写在仓库文件里，而不是聊天记录里",
        "page": "图0-1 全课交付链",
        "nodes": [
            {"box": (40, 310, 150, 100), "text": "模糊想法", "style": "step"},
            {"box": (220, 310, 150, 100), "text": "调研决策", "style": "step2"},
            {"box": (400, 310, 150, 100), "text": "产品合同", "style": "step3"},
            {"box": (580, 310, 150, 100), "text": "竖切实现", "style": "warn"},
            {"box": (760, 310, 150, 100), "text": "验证固化", "style": "step2"},
            {"box": (940, 310, 170, 100), "text": "Playbook", "style": "ok"},
        ],
        "edges": h_edges((190, 360, 215), (370, 360, 395), (550, 360, 575), (730, 360, 755), (910, 360, 935)),
        "footer": "四篇三十三讲：调研 → 产品 → 实现 → 验证与复用。",
    },
    "chapter-32-delivery-bundle.png": {
        "title": "毕业交付包证据分层",
        "subtitle": "事实、产品、实现与验证分目录存放，避免互相污染",
        "page": "图32-2 交付包证据",
        "nodes": [
            {"box": (60, 280, 200, 110), "text": "事实与来源\nresearch-report", "style": "step"},
            {"box": (300, 280, 200, 110), "text": "产品边界\nprd / plan", "style": "step2"},
            {"box": (540, 280, 200, 110), "text": "实现产物\ncode / deliverable", "style": "step3"},
            {"box": (780, 280, 200, 110), "text": "验证记录\nverify / tests", "style": "warn"},
            {"box": (1020, 280, 200, 110), "text": "Handoff\n下一位入口", "style": "ok"},
        ],
        "edges": h_edges((260, 335, 295), (500, 335, 535), (740, 335, 775), (980, 335, 1015)),
        "footer": "每种证据对应独立文件，审查时不必混读代码与推断。",
    },
    "chapter-02-design-loop.png": {
        "title": "验收设计闭环",
        "subtitle": "从用途与风险出发，落到可执行检查与失败动作",
        "page": "图2-3 验收设计闭环",
        "nodes": [
            {"box": (80, 300, 200, 110), "text": "任务用途", "style": "step"},
            {"box": (320, 300, 200, 110), "text": "主要风险", "style": "step2"},
            {"box": (560, 300, 200, 110), "text": "定义证据", "style": "step3"},
            {"box": (800, 300, 170, 110), "text": "证据足够？", "style": "decision"},
            {"box": (1020, 300, 200, 110), "text": "验收矩阵", "style": "ok"},
            {"box": (800, 480, 220, 100), "text": "补充检查或降级", "style": "fail"},
        ],
        "edges": h_edges((280, 355, 315), (520, 355, 555), (760, 355, 795), (970, 355, 1015))
        + [{"kind": "v", "coords": (885, 410, 475), "label": "否"}, {"kind": "h", "coords": (970, 355, 1015), "label": "是"}],
        "footer": "验收标准应在开工前设计，而不是交付后补写。",
    },
    "chapter-03-capability-decision.png": {
        "title": "入口能力决策",
        "subtitle": "按任务依赖选择入口，而不是按习惯",
        "page": "图3-1 入口能力决策",
        "nodes": [
            {"box": (80, 310, 190, 100), "text": "读懂 Brief", "style": "step"},
            {"box": (310, 310, 190, 100), "text": "列出能力需求", "style": "step2"},
            {"box": (540, 310, 190, 100), "text": "入口可满足？", "style": "decision"},
            {"box": (770, 250, 220, 100), "text": "写工作区说明", "style": "ok"},
            {"box": (770, 420, 220, 100), "text": "停止或降级", "style": "fail"},
            {"box": (1040, 250, 240, 100), "text": "执行并留证据", "style": "warn"},
        ],
        "edges": h_edges((270, 360, 305), (500, 360, 535), (990, 300, 1035))
        + [{"kind": "h", "coords": (730, 300, 765), "label": "是"}, {"kind": "v", "coords": (635, 410, 415), "label": "否"}],
        "footer": "正确入口决定 Codex 能看见什么、能做什么。",
    },
    "chapter-04-claim-ledger.png": {
        "title": "主张台账流程",
        "subtitle": "先证明每句话站得住，再写正式报告",
        "page": "图4-1 主张台账流程",
        "nodes": [
            {"box": (60, 310, 160, 100), "text": "研究问题", "style": "step"},
            {"box": (250, 310, 160, 100), "text": "来源候选", "style": "step2"},
            {"box": (440, 310, 160, 100), "text": "证据摘录", "style": "step3"},
            {"box": (630, 310, 180, 100), "text": "最小主张", "style": "warn"},
            {"box": (850, 250, 180, 100), "text": "形成推断", "style": "ok"},
            {"box": (850, 400, 180, 100), "text": "进入 Unknowns", "style": "fail"},
            {"box": (1070, 250, 180, 100), "text": "形成建议", "style": "ok"},
        ],
        "edges": h_edges((220, 360, 245), (410, 360, 435), (600, 360, 625), (810, 360, 845), (1030, 300, 1065))
        + [{"kind": "h", "coords": (810, 300, 845), "label": "支持"}, {"kind": "v", "coords": (720, 410, 395), "label": "不足"}],
        "footer": "结论必须能够沿证据链回到来源。",
    },
    "chapter-05-publish-pipeline.png": {
        "title": "可发版流水线",
        "subtitle": "分层转换，避免为连贯而补事实",
        "page": "图5-1 可发版流水线",
        "nodes": [
            {"box": (50, 310, 150, 100), "text": "原始素材", "style": "step"},
            {"box": (230, 310, 150, 100), "text": "事实与未知", "style": "step2"},
            {"box": (410, 310, 150, 100), "text": "受众结构", "style": "step3"},
            {"box": (590, 310, 130, 100), "text": "草稿", "style": "warn"},
            {"box": (750, 310, 150, 100), "text": "事实审查", "style": "step"},
            {"box": (930, 310, 150, 100), "text": "承诺风险审查", "style": "step2"},
            {"box": (1110, 310, 140, 100), "text": "可发版", "style": "ok"},
        ],
        "edges": h_edges((200, 360, 225), (380, 360, 405), (560, 360, 585), (720, 360, 745), (900, 360, 925), (1080, 360, 1105)),
        "footer": "写完只是草稿，可发布需要多重审查。",
    },
    "chapter-06-evidence-gates.png": {
        "title": "证据门推进流程",
        "subtitle": "计划阶段以证据结束，而不是以忙碌结束",
        "page": "图6-2 证据门推进",
        "nodes": [
            {"box": (80, 310, 170, 100), "text": "目标", "style": "step"},
            {"box": (290, 310, 200, 100), "text": "列出最大不确定性", "style": "step2"},
            {"box": (530, 310, 200, 100), "text": "设计最小验证动作", "style": "step3"},
            {"box": (770, 310, 170, 100), "text": "证据足够？", "style": "decision"},
            {"box": (990, 250, 200, 100), "text": "进入下一里程碑", "style": "ok"},
            {"box": (990, 420, 200, 100), "text": "停止/退回/补证", "style": "fail"},
            {"box": (1230, 250, 150, 100), "text": "更新 Handoff", "style": "warn"},
        ],
        "edges": h_edges((250, 360, 285), (490, 360, 525), (730, 360, 765), (1190, 300, 1225))
        + [{"kind": "h", "coords": (940, 300, 985), "label": "是"}, {"kind": "v", "coords": (855, 410, 415), "label": "否"}],
        "footer": "长任务需要检查点，不能只在终点验收。",
    },
    "chapter-06-plan-anatomy.png": {
        "title": "可执行计划四个支点",
        "subtitle": "计划不仅说明做什么，也说明何时推进、何时停止、怎样接手",
        "page": "图6-1 可执行计划四个支点",
        "nodes": [
            {"box": (80, 300, 260, 130), "text": "Brief 与范围\n支持什么决定？", "style": "step"},
            {"box": (400, 300, 260, 130), "text": "证据门\n拿到什么才推进？", "style": "step2"},
            {"box": (720, 300, 260, 130), "text": "停止与回滚\n触发线与恢复动作", "style": "fail"},
            {"box": (1040, 300, 260, 130), "text": "Handoff\n下一步与未决项", "style": "warn"},
        ],
        "edges": h_edges((340, 365, 395), (660, 365, 715), (980, 365, 1035)),
        "footer": "缺少任一支点，计划都可能在执行中失控或无法接手。",
    },
    "chapter-07-mcp-audit.png": {
        "title": "MCP 调用审计时序",
        "subtitle": "每次调用都要回答目的、范围、结果与后果",
        "page": "图7-2 MCP 审计",
        "nodes": [
            {"box": (60, 310, 180, 100), "text": "人给出任务与权限边界", "style": "step"},
            {"box": (280, 310, 180, 100), "text": "Codex 判断是否需要调用", "style": "step2"},
            {"box": (500, 310, 160, 100), "text": "MCP 最小范围请求", "style": "step3"},
            {"box": (700, 310, 160, 100), "text": "返回结果或错误", "style": "warn"},
            {"box": (900, 250, 200, 100), "text": "区分工具事实与推断", "style": "ok"},
            {"box": (900, 420, 200, 100), "text": "输出 Unknowns 与降级", "style": "fail"},
            {"box": (1140, 250, 220, 100), "text": "交付结果与审计记录", "style": "ok"},
        ],
        "edges": h_edges((240, 360, 275), (460, 360, 495), (660, 360, 695), (860, 360, 895), (1100, 300, 1135))
        + [{"kind": "v", "coords": (800, 410, 415), "label": "失败"}],
        "footer": "工具有权限，不等于当前任务获得了使用全部权限的授权。",
    },
    "chapter-08-browser-state-machine.png": {
        "title": "浏览器流程状态机",
        "subtitle": "记录动作前状态、动作与动作后状态",
        "page": "图8-2 浏览器状态机",
        "nodes": [
            {"box": (80, 310, 150, 100), "text": "首页已加载", "style": "step"},
            {"box": (270, 310, 150, 100), "text": "打开提交页", "style": "step2"},
            {"box": (460, 310, 150, 100), "text": "提交空表单", "style": "step3"},
            {"box": (650, 250, 180, 100), "text": "显示必填提示", "style": "ok"},
            {"box": (650, 420, 180, 100), "text": "补充必填字段", "style": "warn"},
            {"box": (870, 310, 180, 100), "text": "提交合法表单", "style": "step3"},
            {"box": (1090, 310, 150, 100), "text": "成功状态", "style": "ok"},
        ],
        "edges": h_edges((230, 360, 265), (420, 360, 455), (830, 360, 865), (1050, 360, 1085))
        + [{"kind": "v", "coords": (740, 410, 360), "label": "返回"}, {"kind": "h", "coords": (610, 300, 645)}],
        "footer": "可见操作也必须能够复现和检查。",
    },
    "chapter-09-skill-extraction.png": {
        "title": "从真实轨迹提炼 Skill",
        "subtitle": "稳定重复才值得封装，情境判断留给人",
        "page": "图9-2 Skill 提炼",
        "nodes": [
            {"box": (60, 310, 170, 100), "text": "真实任务轨迹 x3", "style": "step"},
            {"box": (270, 310, 170, 100), "text": "找稳定输入与步骤", "style": "step2"},
            {"box": (480, 310, 190, 100), "text": "定义适用/不适用", "style": "step3"},
            {"box": (710, 310, 170, 100), "text": "加入模板与验证", "style": "warn"},
            {"box": (920, 310, 170, 100), "text": "试跑三类样本", "style": "step3"},
            {"box": (1130, 310, 150, 100), "text": "结果稳定？", "style": "decision"},
            {"box": (1130, 480, 150, 100), "text": "收窄场景重做", "style": "fail"},
            {"box": (1310, 310, 110, 100), "text": "发布 Skill", "style": "ok"},
        ],
        "edges": h_edges((230, 360, 265), (440, 360, 475), (670, 360, 705), (880, 360, 915), (1090, 360, 1125))
        + [{"kind": "h", "coords": (1280, 360, 1305), "label": "是"}, {"kind": "v", "coords": (1205, 410, 475), "label": "否"}],
        "footer": "不是每次成功都值得封装，稳定重复才值得。",
    },
    "chapter-10-automation-envelope.png": {
        "title": "自动化权限包络线",
        "subtitle": "先定义最多允许做到哪里，再定义何时运行",
        "page": "图10-2 自动化包络",
        "nodes": [
            {"box": (60, 310, 140, 100), "text": "触发", "style": "step"},
            {"box": (240, 310, 150, 100), "text": "只读收集", "style": "step2"},
            {"box": (430, 310, 150, 100), "text": "生成草稿", "style": "step3"},
            {"box": (620, 310, 150, 100), "text": "自动验证", "style": "warn"},
            {"box": (810, 310, 150, 100), "text": "人工审批？", "style": "decision"},
            {"box": (1000, 250, 180, 100), "text": "发布/写入/发送", "style": "ok"},
            {"box": (1000, 420, 180, 100), "text": "记录原因并停止", "style": "fail"},
        ],
        "edges": h_edges((200, 360, 235), (390, 360, 425), (580, 360, 615), (770, 360, 805))
        + [{"kind": "h", "coords": (960, 300, 995), "label": "通过"}, {"kind": "v", "coords": (885, 410, 415), "label": "拒绝/失败"}],
        "footer": "只有触发器没有停止条件的，不是完整自动化。",
    },
    "chapter-11-data-pipeline.png": {
        "title": "数据处理三段流水线",
        "subtitle": "先剖析、再转换、最后对账与复算",
        "page": "图11-2 数据流水线",
        "nodes": [
            {"box": (60, 310, 150, 100), "text": "原始输入", "style": "step"},
            {"box": (250, 310, 150, 100), "text": "只读剖析", "style": "step2"},
            {"box": (440, 310, 170, 100), "text": "结构质量可接受？", "style": "decision"},
            {"box": (650, 250, 150, 100), "text": "转换到新输出", "style": "ok"},
            {"box": (650, 420, 150, 100), "text": "异常清单/停止", "style": "fail"},
            {"box": (840, 310, 130, 100), "text": "总量对账", "style": "step3"},
            {"box": (1010, 310, 130, 100), "text": "样本复算", "style": "warn"},
            {"box": (1180, 310, 150, 100), "text": "交付与记录", "style": "ok"},
        ],
        "edges": h_edges((210, 360, 245), (390, 360, 435), (800, 360, 835), (970, 360, 1005), (1140, 360, 1175))
        + [{"kind": "h", "coords": (610, 300, 645), "label": "是"}, {"kind": "v", "coords": (525, 410, 415), "label": "否"}],
        "footer": "数据处理要留下从输入到输出的可复查轨迹。",
    },
    "chapter-12-rules-compile.png": {
        "title": "把规则编译成执行清单",
        "subtitle": "护栏要能改变实际行为，而不是复述愿望",
        "page": "图12-2 规则编译",
        "nodes": [
            {"box": (120, 280, 220, 100), "text": "AGENTS.md / README / 配置", "style": "step"},
            {"box": (400, 280, 180, 100), "text": "提取约束", "style": "step2"},
            {"box": (620, 200, 180, 90), "text": "开工前检查", "style": "step3"},
            {"box": (620, 310, 180, 90), "text": "写入与权限边界", "style": "warn"},
            {"box": (620, 420, 180, 90), "text": "结束前验证", "style": "step3"},
            {"box": (860, 310, 200, 100), "text": "形成执行计划", "style": "ok"},
            {"box": (1100, 310, 200, 100), "text": "遇阻力仍遵守护栏", "style": "ok"},
        ],
        "edges": [
            {"kind": "h", "coords": (340, 330, 395)},
            {"kind": "h", "coords": (580, 245, 615)},
            {"kind": "h", "coords": (580, 355, 615)},
            {"kind": "h", "coords": (580, 465, 615)},
            {"kind": "h", "coords": (800, 360, 855)},
            {"kind": "h", "coords": (1060, 360, 1095)},
        ],
        "footer": "护栏不是阻止执行，而是限制错误影响范围。",
    },
    "chapter-13-recon-loop.png": {
        "title": "假设驱动的勘察循环",
        "subtitle": "先交地图，再交代码",
        "page": "图13-2 勘察循环",
        "nodes": [
            {"box": (60, 310, 160, 100), "text": "目标行为", "style": "step"},
            {"box": (260, 310, 160, 100), "text": "提出入口假设", "style": "step2"},
            {"box": (460, 310, 180, 100), "text": "搜索符号/命令/测试", "style": "step3"},
            {"box": (680, 310, 170, 100), "text": "阅读高信号文件", "style": "warn"},
            {"box": (890, 310, 170, 100), "text": "证据支持假设？", "style": "decision"},
            {"box": (890, 480, 170, 100), "text": "调整假设", "style": "fail"},
            {"box": (1100, 250, 200, 100), "text": "记录调用链与影响面", "style": "ok"},
            {"box": (1100, 400, 200, 100), "text": "形成修改候选", "style": "warn"},
        ],
        "edges": h_edges((220, 360, 255), (420, 360, 455), (640, 360, 675), (850, 360, 885))
        + [{"kind": "v", "coords": (975, 410, 475), "label": "否"}, {"kind": "h", "coords": (1060, 300, 1095), "label": "是"}],
        "footer": "进入陌生代码库，先交地图，再交代码。",
    },
    "chapter-14-red-green.png": {
        "title": "先红后绿的热修复闭环",
        "subtitle": "热修复追求最小、可证、可回退",
        "page": "图14-2 红绿闭环",
        "nodes": [
            {"box": (60, 310, 150, 100), "text": "复现失败", "style": "step"},
            {"box": (250, 310, 190, 100), "text": "失败符合 ticket？", "style": "decision"},
            {"box": (480, 420, 180, 100), "text": "停止并重新诊断", "style": "fail"},
            {"box": (480, 250, 150, 100), "text": "定位最小根因", "style": "step2"},
            {"box": (670, 250, 150, 100), "text": "最小修改", "style": "step3"},
            {"box": (860, 250, 150, 100), "text": "目标测试通过", "style": "ok"},
            {"box": (1050, 250, 200, 100), "text": "检查差异与剩余风险", "style": "warn"},
        ],
        "edges": [
            {"kind": "h", "coords": (210, 360, 245)},
            {"kind": "h", "coords": (440, 300, 475), "label": "是"},
            {"kind": "v", "coords": (345, 410, 415), "label": "否"},
            {"kind": "h", "coords": (630, 300, 665)},
            {"kind": "h", "coords": (820, 300, 855)},
            {"kind": "h", "coords": (1010, 300, 1045)},
        ],
        "footer": "没有先红，绿色通过不能证明修复了目标问题。",
    },
    "chapter-15-vertical-slice.png": {
        "title": "可审查竖切",
        "subtitle": "每个阶段交付有限但完整的行为",
        "page": "图15-2 竖切交付",
        "nodes": [
            {"box": (120, 220, 300, 90), "text": "竖切1：最小输入→核心逻辑→可见输出→测试", "style": "step"},
            {"box": (120, 340, 300, 90), "text": "竖切2：边界输入→异常处理→用户反馈→测试", "style": "step2"},
            {"box": (120, 460, 300, 90), "text": "竖切3：用户入口→端到端路径→测试", "style": "step3"},
            {"box": (500, 310, 220, 110), "text": "每阶段可独立验证与回滚", "style": "decision"},
            {"box": (780, 250, 240, 100), "text": "更新 Handoff 与下一目标", "style": "ok"},
            {"box": (780, 400, 240, 100), "text": "停止/缩小范围/回滚", "style": "fail"},
            {"box": (1060, 250, 220, 100), "text": "进入下一竖切", "style": "warn"},
        ],
        "edges": [
            {"kind": "v", "coords": (270, 310, 335)},
            {"kind": "v", "coords": (270, 430, 455)},
            {"kind": "h", "coords": (420, 355, 495)},
            {"kind": "h", "coords": (720, 300, 775), "label": "通过"},
            {"kind": "v", "coords": (610, 420, 395), "label": "失败"},
            {"kind": "h", "coords": (1020, 300, 1055)},
        ],
        "footer": "长任务需要检查点，不能只在终点验收。",
    },
    "chapter-16-review-priority.png": {
        "title": "按风险优先级做 Review",
        "subtitle": "有限时间里先查最可能伤人的问题",
        "page": "图16-2 Review 优先级",
        "nodes": [
            {"box": (200, 250, 240, 90), "text": "P0 安全/数据/权限", "style": "fail"},
            {"box": (500, 250, 240, 90), "text": "P1 行为契约与边界", "style": "warn"},
            {"box": (800, 250, 240, 90), "text": "P2 可维护性与测试", "style": "step2"},
            {"box": (1100, 250, 200, 90), "text": "P3 风格与命名", "style": "step"},
            {"box": (500, 420, 400, 90), "text": "输出分级 findings + 证据 + 建议动作", "style": "ok"},
            {"box": (500, 550, 400, 90), "text": "拒绝时写清信任受损点与复盘", "style": "step3"},
        ],
        "edges": [
            {"kind": "h", "coords": (440, 295, 495)},
            {"kind": "h", "coords": (740, 295, 795)},
            {"kind": "h", "coords": (1040, 295, 1095)},
            {"kind": "v", "coords": (700, 340, 415)},
            {"kind": "v", "coords": (700, 510, 545)},
        ],
        "footer": "审查不是挑错，而是建立可被团队接受的交付。",
    },
    "chapter-17-parallel-deps.png": {
        "title": "并行任务依赖与所有权",
        "subtitle": "并行提升速度，也放大协调和集成风险",
        "page": "图17-2 并行依赖",
        "nodes": [
            {"box": (60, 310, 150, 100), "text": "拆分工作", "style": "step"},
            {"box": (250, 310, 150, 100), "text": "划分所有权", "style": "step2"},
            {"box": (440, 310, 150, 100), "text": "隔离分支/Worktree", "style": "step3"},
            {"box": (630, 310, 130, 100), "text": "运行 CI", "style": "warn"},
            {"box": (800, 310, 170, 100), "text": "失败可分类？", "style": "decision"},
            {"box": (800, 480, 170, 100), "text": "升级/人工介入", "style": "fail"},
            {"box": (1010, 250, 150, 100), "text": "修复并复跑", "style": "ok"},
            {"box": (1010, 400, 150, 100), "text": "合并与集成验证", "style": "warn"},
            {"box": (1200, 310, 150, 100), "text": "更新 Handoff", "style": "ok"},
        ],
        "edges": h_edges((210, 360, 245), (400, 360, 435), (590, 360, 625), (760, 360, 795), (1160, 360, 1195))
        + [{"kind": "v", "coords": (885, 410, 475), "label": "否"}, {"kind": "h", "coords": (970, 300, 1005), "label": "是"}],
        "footer": "并行之前先划分所有权，而不是先开四个线程。",
    },
    "chapter-18-eval-loop.png": {
        "title": "评测改进循环",
        "subtitle": "可靠性需要被测量，而不是只靠感觉",
        "page": "图18-2 评测循环",
        "nodes": [
            {"box": (80, 310, 170, 100), "text": "收集 Trace", "style": "step"},
            {"box": (290, 310, 170, 100), "text": "定义 Rubric", "style": "step2"},
            {"box": (500, 310, 150, 100), "text": "运行 Eval", "style": "step3"},
            {"box": (690, 310, 170, 100), "text": "分数可解释？", "style": "decision"},
            {"box": (690, 480, 170, 100), "text": "修订 Rubric/样本", "style": "fail"},
            {"box": (900, 250, 180, 100), "text": "改进 Brief/Skill/护栏", "style": "ok"},
            {"box": (900, 400, 180, 100), "text": "复跑对照组", "style": "warn"},
            {"box": (1120, 310, 180, 100), "text": "记录版本与结论", "style": "ok"},
        ],
        "edges": h_edges((250, 360, 285), (460, 360, 495), (650, 360, 685), (1080, 360, 1115))
        + [{"kind": "v", "coords": (775, 410, 475), "label": "否"}, {"kind": "h", "coords": (860, 300, 895), "label": "是"}],
        "footer": "从一次成功到可重复改进，需要轨迹、标准与评测。",
    },
    "chapter-19-delivery-bundle.png": {
        "title": "毕业交付包流转",
        "subtitle": "不同证据最终汇入同一个可审查交付包",
        "page": "图19-2 交付包流转",
        "nodes": [
            {"box": (80, 310, 150, 100), "text": "调研与来源", "style": "step"},
            {"box": (270, 310, 150, 100), "text": "实现与验证", "style": "step2"},
            {"box": (460, 310, 150, 100), "text": "文档与说明", "style": "step3"},
            {"box": (650, 310, 150, 100), "text": "Handoff 交接", "style": "warn"},
            {"box": (840, 310, 170, 100), "text": "阶段闸门通过？", "style": "decision"},
            {"box": (840, 480, 170, 100), "text": "退回补证据", "style": "fail"},
            {"box": (1050, 310, 200, 100), "text": "毕业交付包", "style": "ok"},
            {"box": (1280, 310, 120, 100), "text": "答辩验收", "style": "ok"},
        ],
        "edges": h_edges((230, 360, 265), (420, 360, 455), (610, 360, 645), (800, 360, 835), (1250, 360, 1275))
        + [{"kind": "v", "coords": (925, 410, 475), "label": "否"}, {"kind": "h", "coords": (1010, 360, 1045), "label": "是"}],
        "footer": "综合交付要求不同证据最终汇入同一个交付包。",
    },
    "chapter-20-checkpoint-loop.png": {
        "title": "委托、验收与检查点闭环",
        "subtitle": "长任务切成可审查片段，每段结束留下证据再前进",
        "page": "图20-1 检查点闭环",
        "nodes": [
            {"box": (30, 310, 140, 100), "text": "写清任务", "style": "step"},
            {"box": (200, 310, 120, 100), "text": "选入口", "style": "step2"},
            {"box": (350, 310, 140, 100), "text": "委托执行", "style": "step3"},
            {"box": (520, 310, 130, 100), "text": "审查 Diff", "style": "warn"},
            {"box": (680, 310, 140, 100), "text": "验收证据", "style": "step2"},
            {"box": (850, 310, 150, 100), "text": "证据足够？", "style": "decision"},
            {"box": (850, 480, 150, 100), "text": "暂停/纠偏", "style": "fail"},
            {"box": (1040, 310, 170, 100), "text": "交接下一位", "style": "ok"},
        ],
        "edges": h_edges((170, 360, 195), (320, 360, 345), (490, 360, 515), (650, 360, 675), (820, 360, 845))
        + [{"kind": "h", "coords": (1000, 360, 1035), "label": "是"}, {"kind": "v", "coords": (925, 410, 475), "label": "否"}],
        "footer": "写清任务 → 选入口 → 委托 → 验收 → 交接；缺证据不进入下一步。",
    },
    "chapter-20-scope-drift.png": {
        "title": "范围漂移路径",
        "subtitle": "每一跳都有合理借口，累积结果却偏离产品边界",
        "page": "图20-2 范围漂移",
        "nodes": [
            {"box": (80, 310, 170, 100), "text": "本段小优化", "style": "step"},
            {"box": (290, 310, 190, 100), "text": "顺便接 live 数据", "style": "step2"},
            {"box": (520, 310, 190, 100), "text": "反正都要做交易", "style": "warn"},
            {"box": (750, 310, 170, 100), "text": "偏离 PRD？", "style": "decision"},
            {"box": (750, 480, 170, 100), "text": "检查点暂停", "style": "fail"},
            {"box": (970, 310, 210, 100), "text": "缩小 Brief 重做", "style": "ok"},
        ],
        "edges": h_edges((250, 360, 285), (480, 360, 515), (710, 360, 745))
        + [{"kind": "h", "coords": (920, 360, 965), "label": "是"}, {"kind": "v", "coords": (835, 410, 475), "label": "否"}],
        "footer": "在范围漂移最便宜的时候纠偏，而不是等最终回复再收拾。",
    },
    "chapter-20-playbook-ladder.png": {
        "title": "Playbook 推广阶梯",
        "subtitle": "推广不是复制提示词，而是复制经过验证的工作方式",
        "page": "图20-2 推广阶梯",
        "nodes": [
            {"box": (100, 310, 180, 100), "text": "个人实践", "style": "step"},
            {"box": (330, 310, 180, 100), "text": "沉淀 Playbook", "style": "step2"},
            {"box": (560, 310, 180, 100), "text": "小组试点", "style": "step3"},
            {"box": (790, 310, 180, 100), "text": "评测与责任确认", "style": "warn"},
            {"box": (1020, 310, 180, 100), "text": "团队采用？", "style": "decision"},
            {"box": (1020, 480, 180, 100), "text": "继续试点或拒绝", "style": "fail"},
            {"box": (1240, 310, 150, 100), "text": "持续治理", "style": "ok"},
        ],
        "edges": h_edges((280, 360, 325), (510, 360, 555), (740, 360, 785), (970, 360, 1015))
        + [{"kind": "h", "coords": (1200, 360, 1235), "label": "是"}, {"kind": "v", "coords": (1110, 410, 475), "label": "否"}],
        "footer": "工作手册要指导判断，而不是堆规则。",
    },
}


def build_drawio_page(page_id: str, page_name: str, spec: dict) -> ET.Element:
    spec = compact_spec(spec)
    page_width, page_height = spec.get("canvas", (WIDTH, HEIGHT))
    diagram = ET.Element("diagram", id=page_id, name=page_name)
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
            "pageWidth": str(page_width),
            "pageHeight": str(page_height),
            "background": BG,
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")

    title_cell = ET.SubElement(
        root,
        "mxCell",
        {
            "id": f"{page_id}-title",
            "value": spec["title"],
            "style": "text;html=1;strokeColor=none;fillColor=none;fontSize=36;fontColor=#101A33;fontStyle=1;align=left;",
            "vertex": "1",
            "parent": "1",
        },
    )
    title_x, title_y = spec.get("title_xy", (80, 55))
    ET.SubElement(title_cell, "mxGeometry", {"x": str(title_x), "y": str(title_y), "width": "1100", "height": "55", "as": "geometry"})

    sub_cell = ET.SubElement(
        root,
        "mxCell",
        {
            "id": f"{page_id}-sub",
            "value": spec.get("subtitle", ""),
            "style": "text;html=1;strokeColor=none;fillColor=none;fontSize=20;fontColor=#596983;align=left;",
            "vertex": "1",
            "parent": "1",
        },
    )
    sub_x, sub_y = spec.get("subtitle_xy", (80, 115))
    ET.SubElement(sub_cell, "mxGeometry", {"x": str(sub_x), "y": str(sub_y), "width": "1100", "height": "35", "as": "geometry"})

    for idx, node in enumerate(spec.get("nodes", [])):
        x, y, w, h = node["box"]
        stroke = STYLE_TO_DRAWIO.get(node["style"], "#2563EB")
        fill = "#E8F5E9" if node["style"] == "ok" else "#FFEBEE" if node["style"] == "fail" else "#FFFFFF"
        if node["style"] == "decision":
            shape = "rhombus;whiteSpace=wrap;html=1;"
        else:
            shape = "rounded=1;whiteSpace=wrap;html=1;"
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": f"{page_id}-n{idx}",
                "value": node["text"],
                "style": f"{shape}fillColor={fill};strokeColor={stroke};strokeWidth=3;fontColor=#101A33;fontSize=20;",
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(cell, "mxGeometry", {"x": str(x), "y": str(y), "width": str(w), "height": str(h), "as": "geometry"})

    for idx, edge in enumerate(spec.get("edges", [])):
        label = edge.get("label") or ""
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": f"{page_id}-e{idx}",
                "value": label,
                "style": "endArrow=classic;html=1;strokeColor=#63738C;strokeWidth=4;fontSize=16;fontColor=#596983;",
                "edge": "1",
                "parent": "1",
            },
        )
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})

    if foot := spec.get("footer"):
        footer_box = spec.get("footer_box", (300, 650, 1140, 735))
        fx1, fy1, fx2, fy2 = footer_box
        foot_cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": f"{page_id}-foot",
                "value": foot,
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#101A33;strokeColor=none;fontColor=#FFFFFF;fontSize=22;",
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            foot_cell,
            "mxGeometry",
            {
                "x": str(fx1),
                "y": str(fy1),
                "width": str(fx2 - fx1),
                "height": str(fy2 - fy1),
                "as": "geometry",
            },
        )

    return diagram


def write_drawio() -> None:
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "modified": "2026-06-10T00:00:00.000Z",
            "agent": "ashare-research-sandbox",
            "version": "24.7.17",
            "type": "device",
        },
    )
    for filename, spec in DIAGRAMS.items():
        page_id = filename.replace(".png", "").replace("chapter-", "supp-")
        mxfile.append(build_drawio_page(page_id, spec["page"], spec))
    tree = ET.ElementTree(mxfile)
    ET.indent(tree, space="  ")
    DRAWIO_OUT.parent.mkdir(parents=True, exist_ok=True)
    tree.write(DRAWIO_OUT, encoding="unicode", xml_declaration=True)


def main() -> int:
    for filename, spec in DIAGRAMS.items():
        render_diagram(spec, ASSETS / filename)
        print(f"wrote {filename}")
    write_drawio()
    print(f"wrote {DRAWIO_OUT.relative_to(ROOT)} ({len(DIAGRAMS)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
