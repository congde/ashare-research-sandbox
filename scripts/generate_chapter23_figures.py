"""Generate Chapter 23 publication figures."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import sys
from textwrap import fill
import xml.etree.ElementTree as ET

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research.report import build_report  # noqa: E402


BLUE = "#2563EB"
TEAL = "#0F9B8E"
ORANGE = "#F59E0B"
RED = "#DC2626"
PURPLE = "#7C3AED"
INK = "#111827"
MUTED = "#64748B"
GRID = "#E5E7EB"
PAPER = "#F7F9FC"


def _drawio_root(name: str, diagram_name: str = "图 23-1 证据路径与停止点") -> tuple[ET.ElementTree, ET.Element]:
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "modified": "2026-07-02T00:00:00.000Z",
            "agent": "web3-quant-sandbox",
            "version": "24.7.17",
            "type": "device",
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"id": name, "name": diagram_name})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1800",
            "dy": "900",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "1600",
            "pageHeight": "900",
            "background": PAPER,
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    return ET.ElementTree(mxfile), root


def _drawio_cell(
    root: ET.Element,
    cid: str,
    value: str,
    style: str,
    x: int,
    y: int,
    w: int,
    h: int,
) -> None:
    node = ET.SubElement(root, "mxCell", {"id": cid, "value": value, "style": style, "vertex": "1", "parent": "1"})
    ET.SubElement(node, "mxGeometry", {"x": str(x), "y": str(y), "width": str(w), "height": str(h), "as": "geometry"})


def _drawio_edge(root: ET.Element, cid: str, x1: int, y1: int, x2: int, y2: int, color: str = MUTED) -> None:
    node = ET.SubElement(
        root,
        "mxCell",
        {
            "id": cid,
            "value": "",
            "style": f"endArrow=block;html=1;rounded=0;strokeColor={color};strokeWidth=3;endFill=1;",
            "edge": "1",
            "parent": "1",
        },
    )
    geom = ET.SubElement(node, "mxGeometry", {"width": "50", "height": "50", "relative": "1", "as": "geometry"})
    ET.SubElement(geom, "mxPoint", {"x": str(x1), "y": str(y1), "as": "sourcePoint"})
    ET.SubElement(geom, "mxPoint", {"x": str(x2), "y": str(y2), "as": "targetPoint"})


def setup_matplotlib() -> None:
    plt.rcParams["font.sans-serif"] = [
        "SimHei",
        "Microsoft YaHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def route_rows() -> list[dict[str, str]]:
    app = read_text("src/web/src/App.tsx")
    layout = read_text("src/web/src/layouts/MainLayout.tsx")
    labels = dict(re.findall(r'\{\s*key:\s*"([^"]+)",\s*icon:\s*<[^>]+ />,\s*label:\s*"([^"]+)"', layout))
    routes = re.findall(r'<Route path="([^"]+)" element=\{<([^ />]+)', app)
    rows = []
    for path, component in routes:
        if path in {"*", "/", "/dashboard"}:
            continue
        rows.append(
            {
                "path": path,
                "label": labels.get(path, component),
                "component": component,
            }
        )
    order = ["/trading", "/radar", "/data-sources", "/backtests", "/risk", "/strategy", "/research", "/live-trading"]
    return sorted(rows, key=lambda row: order.index(row["path"]) if row["path"] in order else 99)


def api_groups() -> Counter[str]:
    api = read_text("src/web/src/api.ts")
    names = re.findall(r"export\s+(?:async\s+)?function\s+([A-Za-z0-9_]+)\(", api)
    counter: Counter[str] = Counter()
    for name in names:
        lower = name.lower()
        if "backtest" in lower:
            counter["backtest"] += 1
        elif any(key in lower for key in ["aipicks", "onchain", "sector", "dex", "tokenfund"]):
            counter["market_context"] += 1
        elif any(key in lower for key in ["market", "ticker", "kline"]):
            counter["market_data"] += 1
        elif any(key in lower for key in ["signal", "strategy", "factor"]):
            counter["signal_strategy"] += 1
        elif any(key in lower for key in ["source", "config"]):
            counter["source_status"] += 1
        else:
            counter["other"] += 1
    return counter


def save_research_ia_path() -> None:
    steps = [
        ("市场总览", "/trading", "L1 观察", "行情、恐贪、板块", "缺来源则降级"),
        ("机会雷达", "/radar", "L1 观察", "候选、排名、理由", "缺理由不入池"),
        ("数据源", "/data-sources", "L0/L1 来源", "模式、探针、失败", "ok=false 停止"),
        ("策略回测", "/backtests", "L2/L3 实验", "参数、成本、回撤", "缺成本暂停"),
        ("风控中心", "/risk", "L4 裁决", "规则、阻断、停止线", "命中即短路"),
        ("研究报告", "/research", "L5 结论", "引用、边界、反例", "不可写建议"),
    ]
    colors = [BLUE, TEAL, ORANGE, PURPLE, RED, "#334155"]
    fig, ax = plt.subplots(figsize=(13.6, 6.2), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.93, "研究路径按证据强度和停止条件组织，而不是按后端模块堆功能", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    ax.text(0.04, 0.87, "读图顺序：先确认来源，再验证假设，最后才允许写研究观察。任何节点缺关键字段，都只能降级或停止。", transform=ax.transAxes, fontsize=10.5, color=MUTED)
    x0 = 0.04
    width = 0.13
    gap = 0.025
    for i, ((title, path, level, evidence, gate), color) in enumerate(zip(steps, colors, strict=True)):
        x = x0 + i * (width + gap)
        ax.add_patch(Rectangle((x, 0.36), width, 0.40, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.add_patch(Rectangle((x, 0.72), width, 0.04, transform=ax.transAxes, facecolor=color, edgecolor=color, linewidth=0))
        ax.text(x + 0.012, 0.66, title, transform=ax.transAxes, fontsize=11.2, color=color, weight="bold")
        ax.text(x + 0.012, 0.59, path, transform=ax.transAxes, fontsize=9.4, color=INK)
        ax.text(x + 0.012, 0.52, level, transform=ax.transAxes, fontsize=9.6, color=INK, weight="bold")
        ax.text(x + 0.012, 0.46, evidence, transform=ax.transAxes, fontsize=8.9, color=INK)
        ax.text(x + 0.012, 0.40, gate, transform=ax.transAxes, fontsize=8.8, color=RED if "停" in gate or "短路" in gate else MUTED)
        if i < len(steps) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.006, 0.56), (x + width + gap - 0.006, 0.56), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=13, linewidth=1.7, color=MUTED))
    ax.add_patch(Rectangle((0.16, 0.18), 0.24, 0.10, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=GRID, linewidth=1.4))
    ax.text(0.18, 0.235, "辅助入口：/strategy", transform=ax.transAxes, fontsize=10.2, color=PURPLE, weight="bold")
    ax.text(0.18, 0.205, "先做 DSL 校验和 lookahead 检查，再进入实验", transform=ax.transAxes, fontsize=8.8, color=INK)
    ax.add_patch(Rectangle((0.58, 0.18), 0.25, 0.10, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=GRID, linewidth=1.4))
    ax.text(0.60, 0.235, "边界入口：/live-trading", transform=ax.transAxes, fontsize=10.2, color=RED, weight="bold")
    ax.text(0.60, 0.205, "只做教学模拟，不能替代研究结论或真实下单", transform=ax.transAxes, fontsize=8.8, color=INK)
    ax.text(
        0.04,
        0.08,
        "来源：src/web/src/App.tsx、MainLayout.tsx、api.ts 与 dashboard.api.sources_status()；L0-L5 对应本讲证据强度矩阵。",
        transform=ax.transAxes,
        fontsize=10.5,
        color=MUTED,
    )
    fig.savefig(OUT / "chapter-23-research-ia-path.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-23-research-ia-path.png")


def save_research_ia_path_drawio() -> None:
    tree, root = _drawio_root("chapter-23-research-ia-path")
    text_style = (
        "text;html=1;strokeColor=none;fillColor=none;align=left;"
        "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Microsoft YaHei;"
    )
    _drawio_cell(
        root,
        "title",
        "研究路径按证据强度和停止条件组织，而不是按后端模块堆功能",
        text_style + f"fontSize=28;fontColor={INK};fontStyle=1;",
        70,
        45,
        980,
        44,
    )
    _drawio_cell(
        root,
        "subtitle",
        "读图顺序：先确认来源，再验证假设，最后才允许写研究观察。任何节点缺关键字段，都只能降级或停止。",
        text_style + f"fontSize=16;fontColor={MUTED};",
        72,
        92,
        1120,
        34,
    )

    steps = [
        ("market", "市场总览", "/trading", "L1 观察", "行情、恐贪、板块", "缺来源则降级", BLUE),
        ("radar", "机会雷达", "/radar", "L1 观察", "候选、排名、理由", "缺理由不入池", TEAL),
        ("source", "数据源", "/data-sources", "L0/L1 来源", "模式、探针、失败", "ok=false 停止", ORANGE),
        ("backtest", "策略回测", "/backtests", "L2/L3 实验", "参数、成本、回撤", "缺成本暂停", PURPLE),
        ("risk", "风控中心", "/risk", "L4 裁决", "规则、阻断、停止线", "命中即短路", RED),
        ("report", "研究报告", "/research", "L5 结论", "引用、边界、反例", "不可写建议", "#334155"),
    ]
    card_w = 190
    card_h = 230
    x0 = 75
    gap = 35
    y = 210
    for index, (cid, title, path, level, evidence, gate, color) in enumerate(steps):
        x = x0 + index * (card_w + gap)
        style = (
            "rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;"
            f"strokeColor={color};strokeWidth=4;fontFamily=Microsoft YaHei;"
            f"align=left;verticalAlign=top;spacing=18;fontSize=16;fontColor={INK};"
        )
        _drawio_cell(root, cid, f"{title}\n{path}\n{level}\n{evidence}\n{gate}", style, x, y, card_w, card_h)
        _drawio_cell(root, f"{cid}_bar", "", f"rounded=0;whiteSpace=wrap;html=1;fillColor={color};strokeColor={color};", x, y, card_w, 24)
        if index < len(steps) - 1:
            _drawio_edge(root, f"edge_{cid}", x + card_w + 5, y + 115, x + card_w + gap - 5, y + 115)

    helper_style = (
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#E5E7EB;"
        "strokeWidth=3;fontFamily=Microsoft YaHei;align=left;verticalAlign=middle;spacing=18;"
    )
    _drawio_cell(
        root,
        "strategy",
        "辅助入口：/strategy\n先做 DSL 校验和 lookahead 检查，再进入实验",
        helper_style,
        260,
        505,
        370,
        86,
    )
    _drawio_cell(
        root,
        "live",
        "边界入口：/live-trading\n只做教学模拟，不能替代研究结论或真实下单",
        helper_style,
        900,
        505,
        395,
        86,
    )
    _drawio_cell(
        root,
        "source_note",
        "来源：src/web/src/App.tsx、MainLayout.tsx、api.ts 与 dashboard.api.sources_status()；L0-L5 对应本讲证据强度矩阵。",
        text_style + f"fontSize=15;fontColor={MUTED};",
        72,
        690,
        1260,
        38,
    )
    ET.indent(tree, space="  ")
    out = OUT / "chapter-23-research-ia-path.drawio"
    tree.write(out, encoding="unicode", xml_declaration=True)
    print(out)


def save_information_architecture_layers() -> None:
    groups = [
        (
            "研究入口",
            BLUE,
            [
                ("市场总览\n/trading", "行情 / 摘要 / 风险入口"),
                ("机会雷达\n/radar", "候选 / 理由 / 实验入口"),
                ("数据源\n/data-sources", "来源 / 失败 / 降级"),
            ],
        ),
        (
            "实验验证",
            PURPLE,
            [
                ("策略回测\n/backtests", "参数 / 成本 / 稳健性"),
                ("策略 DSL\n/strategy", "语法 / lookahead / 边界"),
            ],
        ),
        (
            "风险边界",
            RED,
            [
                ("风控中心\n/risk", "规则 / 拦截 / 停止线"),
                ("模拟交易\n/live-trading", "教学 / 模拟 / 无真实交易"),
            ],
        ),
        (
            "研究输出",
            TEAL,
            [
                ("市场情报\n/research", "引用 / 边界 / 不外推"),
            ],
        ),
    ]
    fig, ax = plt.subplots(figsize=(13.4, 7.2), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.94, "交易研究应用的信息架构图", transform=ax.transAxes, fontsize=15.5, color=INK, weight="bold")
    ax.text(
        0.04,
        0.885,
        "按常见 IA 画法，先画页面/内容的层级与分组，再在节点里标出用户必须看见的证据对象。",
        transform=ax.transAxes,
        fontsize=10.5,
        color=MUTED,
    )
    root_x, root_y, root_w, root_h = 0.36, 0.78, 0.28, 0.075
    ax.add_patch(Rectangle((root_x, root_y), root_w, root_h, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=INK, linewidth=2.2))
    ax.text(root_x + root_w / 2, root_y + root_h / 2, "Web3 Research Sandbox\n研究应用", transform=ax.transAxes, ha="center", va="center", fontsize=11.5, color=INK, weight="bold")

    group_y = 0.61
    group_w = 0.20
    group_h = 0.075
    group_gap = 0.035
    start_x = 0.05
    node_w = 0.17
    node_h = 0.13
    node_gap = 0.025
    for group_index, (group_title, color, pages) in enumerate(groups):
        gx = start_x + group_index * (group_w + group_gap)
        ax.add_patch(Rectangle((gx, group_y), group_w, group_h, transform=ax.transAxes, facecolor=color, edgecolor=color, linewidth=0))
        ax.text(gx + group_w / 2, group_y + group_h / 2, group_title, transform=ax.transAxes, ha="center", va="center", fontsize=11.5, color="#FFFFFF", weight="bold")
        ax.add_patch(FancyArrowPatch((root_x + root_w / 2, root_y), (gx + group_w / 2, group_y + group_h), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=10, linewidth=1.2, color=MUTED))
        for page_index, (page_title, evidence) in enumerate(pages):
            ny = group_y - (page_index + 1) * (node_h + node_gap)
            nx = gx + (group_w - node_w) / 2
            ax.add_patch(Rectangle((nx, ny), node_w, node_h, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=1.8))
            title, path = page_title.split("\n", 1)
            ax.text(
                nx + 0.012,
                ny + node_h - 0.030,
                f"{title}\n{path}\n{evidence}",
                transform=ax.transAxes,
                fontsize=8.2,
                color=INK,
                va="top",
                linespacing=1.2,
            )
            ax.add_patch(FancyArrowPatch((gx + group_w / 2, group_y), (nx + node_w / 2, ny + node_h), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=9, linewidth=1.0, color=MUTED))

    ax.add_patch(Rectangle((0.81, 0.15), 0.13, 0.18, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=RED, linewidth=1.8))
    ax.text(0.83, 0.29, "停止条件", transform=ax.transAxes, fontsize=10.5, color=RED, weight="bold")
    ax.text(0.83, 0.25, "缺来源\n缺成本\n接口失败\n风险阻断", transform=ax.transAxes, fontsize=8.9, color=INK, va="top", linespacing=1.3)
    ax.text(
        0.08,
        0.08,
        "读法：这是站点地图式 IA，而不是用户流。它回答“内容放在哪、页面之间怎么分组、每页承担哪类证据职责”。",
        transform=ax.transAxes,
        fontsize=10.2,
        color=MUTED,
    )
    fig.savefig(OUT / "chapter-23-information-architecture-layers.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-23-information-architecture-layers.png")


def save_information_architecture_layers_drawio() -> None:
    tree, root = _drawio_root("chapter-23-information-architecture-layers", "图 23-2 信息架构图")
    text_style = (
        "text;html=1;strokeColor=none;fillColor=none;align=left;"
        "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Microsoft YaHei;"
    )
    _drawio_cell(root, "title", "交易研究应用的信息架构图", text_style + f"fontSize=28;fontColor={INK};fontStyle=1;", 70, 45, 720, 44)
    _drawio_cell(
        root,
        "subtitle",
        "按常见 IA 画法，先画页面/内容的层级与分组，再在节点里标出必须看见的证据对象。",
        text_style + f"fontSize=16;fontColor={MUTED};",
        72,
        92,
        960,
        34,
    )
    _drawio_cell(root, "root", "Web3 Research Sandbox\n研究应用", f"rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={INK};strokeWidth=3;fontFamily=Microsoft YaHei;fontSize=18;fontColor={INK};align=center;verticalAlign=middle;", 560, 155, 360, 76)
    groups = [
        ("entry", "研究入口", BLUE, [("trading", "市场总览\n/trading\n行情背景 / 报告摘要 / 风险入口"), ("radar", "机会雷达\n/radar\n候选池 / 排名理由 / 进入实验"), ("sources", "数据源\n/data-sources\ndata_mode / ok-source-error / 降级说明")]),
        ("experiment", "实验验证", PURPLE, [("backtests", "策略回测\n/backtests\n参数成本 / 收益回撤 / WFO-PBO-CPCV"), ("strategy", "策略 DSL\n/strategy\n语法校验 / lookahead / 安全边界")]),
        ("risk", "风险边界", RED, [("risk_page", "风控中心\n/risk\n规则栈 / 拦截明细 / 停止线"), ("live", "模拟交易\n/live-trading\n教学模拟 / 无真实交易 / 边界文案")]),
        ("output", "研究输出", TEAL, [("research", "市场情报\n/research\n证据引用 / 结论边界 / 不可外推")]),
    ]
    gx0 = 80
    gy = 295
    gw = 260
    gh = 56
    ggap = 40
    nw = 220
    nh = 102
    ngap = 26
    for group_index, (gid, title, color, pages) in enumerate(groups):
        gx = gx0 + group_index * (gw + ggap)
        _drawio_cell(root, gid, title, f"rounded=0;whiteSpace=wrap;html=1;fillColor={color};strokeColor={color};fontFamily=Microsoft YaHei;fontSize=18;fontColor=#FFFFFF;fontStyle=1;align=center;verticalAlign=middle;", gx, gy, gw, gh)
        _drawio_edge(root, f"edge_root_{gid}", 740, 231, gx + gw // 2, gy)
        for page_index, (pid, value) in enumerate(pages):
            py = gy + gh + 38 + page_index * (nh + ngap)
            px = gx + (gw - nw) // 2
            _drawio_cell(root, pid, value, f"rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={color};strokeWidth=3;fontFamily=Microsoft YaHei;fontSize=15;fontColor={INK};align=left;verticalAlign=top;spacing=14;", px, py, nw, nh)
            _drawio_edge(root, f"edge_{gid}_{pid}", gx + gw // 2, gy + gh, px + nw // 2, py)
    _drawio_cell(
        root,
        "gate",
        "停止条件\n缺来源 / 缺成本\n接口失败 / 风控阻断",
        f"rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={RED};strokeWidth=3;fontFamily=Microsoft YaHei;fontSize=17;fontColor={INK};align=left;verticalAlign=middle;spacing=18;",
        1230,
        615,
        230,
        130,
    )
    _drawio_cell(
        root,
        "note",
        "读法：这是站点地图式 IA，而不是用户流。它回答“内容放在哪、页面之间怎么分组、每页承担哪类证据职责”。",
        text_style + f"fontSize=15;fontColor={MUTED};",
        90,
        795,
        1200,
        38,
    )
    ET.indent(tree, space="  ")
    out = OUT / "chapter-23-information-architecture-layers.drawio"
    tree.write(out, encoding="unicode", xml_declaration=True)
    print(out)


def save_route_inventory() -> None:
    rows = route_rows()
    fig, ax = plt.subplots(figsize=(11.5, 6.2), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.92, f"前端实际注册 {len(rows)} 个研究相关路由", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    col_x = [0.05, 0.25, 0.47, 0.72]
    col_w = [0.16, 0.18, 0.21, 0.21]
    headers = ["路由", "菜单标签", "组件", "证据职责"]
    duties = {
        "/trading": "入口摘要与跨页跳转",
        "/radar": "候选排序与理由",
        "/data-sources": "来源状态与离线边界",
        "/backtests": "实验参数与绩效证据",
        "/risk": "规则栈与阻断明细",
        "/strategy": "DSL 校验与安全边界",
        "/research": "情报归纳与结论边界",
        "/live-trading": "模拟执行，不是真实下单",
    }
    y0 = 0.81
    row_h = 0.075
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, row_h, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.01, y0 + row_h / 2, header, transform=ax.transAxes, va="center", fontsize=10.5, color="#FFFFFF", weight="bold")
    for i, row in enumerate(rows):
        y = y0 - (i + 1) * row_h
        fill_color = "#FFFFFF" if i % 2 == 0 else "#F8FAFC"
        values = [row["path"], row["label"], row["component"], duties.get(row["path"], "辅助入口")]
        for x, w, value in zip(col_x, col_w, values, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=fill_color, edgecolor=GRID))
            ax.text(x + 0.01, y + row_h / 2, fill(value, 24), transform=ax.transAxes, va="center", fontsize=9.5, color=INK)
    ax.text(0.05, 0.08, "出版要求：文档中出现的路由必须能在 App.tsx 中找到，菜单标签必须能在 MainLayout.tsx 中找到。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-23-route-inventory.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-23-route-inventory.png")


def save_api_evidence_bars() -> None:
    counter = api_groups()
    order = ["market_context", "market_data", "backtest", "signal_strategy", "source_status", "other"]
    labels = {
        "market_context": "市场背景",
        "market_data": "行情/K线",
        "backtest": "回测实验",
        "signal_strategy": "信号/策略",
        "source_status": "来源状态",
        "other": "其他",
    }
    values = [counter[key] for key in order]
    colors = [TEAL, BLUE, PURPLE, ORANGE, RED, "#64748B"]
    fig, ax = plt.subplots(figsize=(10.5, 5.4), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    bars = ax.bar([labels[key] for key in order], values, color=colors)
    ax.set_ylabel("fetch 封装数量")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, values, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.15, str(value), ha="center", va="bottom", fontsize=10, color=INK)
    ax.text(
        0.01,
        -0.18,
        "来源：src/web/src/api.ts；信息架构不是页面名清单，而是把行情、信号、回测、风险和来源状态分层。",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-23-api-evidence-bars.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-23-api-evidence-bars.png")


def save_page_evidence_matrix() -> None:
    pages = ["市场总览", "机会雷达", "数据源", "策略回测", "风控中心", "研究报告"]
    fields = ["来源", "更新时间", "候选理由", "参数", "风险状态", "失败信息"]
    coverage = [
        [1, 1, 0, 0, 1, 1],
        [1, 1, 1, 0, 0, 1],
        [1, 1, 0, 0, 0, 1],
        [1, 0, 0, 1, 1, 1],
        [1, 0, 0, 1, 1, 1],
        [1, 1, 1, 1, 1, 1],
    ]
    fig, ax = plt.subplots(figsize=(10.8, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.imshow(coverage, cmap=plt.matplotlib.colors.ListedColormap(["#E5E7EB", TEAL]), aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(len(fields)))
    ax.set_xticklabels(fields)
    ax.set_yticks(range(len(pages)))
    ax.set_yticklabels(pages)
    ax.set_xticks([x - 0.5 for x in range(1, len(fields))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(pages))], minor=True)
    ax.grid(which="minor", color="#FFFFFF", linewidth=2)
    ax.tick_params(which="minor", bottom=False, left=False)
    for y, row in enumerate(coverage):
        for x, value in enumerate(row):
            ax.text(x, y, "OK" if value else "", ha="center", va="center", fontsize=11, color="#FFFFFF" if value else MUTED, weight="bold")
    ax.text(
        0,
        -0.16,
        "矩阵用于设计验收：页面可以不展示所有字段，但导航切换后证据链不能断。",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-23-page-evidence-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-23-page-evidence-matrix.png")


def save_risk_boundary_card() -> None:
    report = build_report(short=3, long=7)
    checks = report["risk_checks"]
    runtime = next((item for item in checks if item["phase"] == "pre_trade"), None)
    warnings = report.get("warnings", [])
    rows = [
        ("研究入口", "/trading → /radar → /backtests → /risk", "允许继续分析"),
        ("模拟入口", "/live-trading", "必须标记教学/模拟"),
        ("风险阻断", f"{runtime['rule_id']} {runtime['count']}x" if runtime else "无运行期阻断", "不能隐藏"),
        ("结论边界", warnings[0] if warnings else "研究观察", "不能写成投资建议"),
    ]
    fig, ax = plt.subplots(figsize=(11.2, 5.2), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "研究应用的信息架构必须保留边界线", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    col_x = [0.05, 0.25, 0.62]
    col_w = [0.15, 0.31, 0.25]
    headers = ["检查", "真实对象", "页面处理"]
    y0 = 0.76
    row_h = 0.13
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.08, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.012, y0 + 0.04, header, transform=ax.transAxes, va="center", fontsize=10.8, color="#FFFFFF", weight="bold")
    for i, row in enumerate(rows):
        y = y0 - (i + 1) * row_h
        fill_color = "#FFFFFF" if i % 2 == 0 else "#F8FAFC"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=fill_color, edgecolor=GRID))
            ax.text(x + 0.012, y + row_h / 2, fill(str(value), 32), transform=ax.transAxes, va="center", fontsize=10, color=INK)
    ax.text(0.05, 0.08, "要点：页面可以支持模拟交易流程，但文案和路径必须持续提醒“教学沙箱、无真实交易”。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-23-risk-boundary-card.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-23-risk-boundary-card.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    setup_matplotlib()
    save_research_ia_path()
    save_research_ia_path_drawio()
    save_information_architecture_layers()
    save_information_architecture_layers_drawio()
    save_route_inventory()
    save_api_evidence_bars()
    save_page_evidence_matrix()
    save_risk_boundary_card()


if __name__ == "__main__":
    main()
