"""Generate Chapter 23 publication figures."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import sys
from textwrap import fill

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dashboard.api import sources_status  # noqa: E402
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


def source_probe_rows() -> list[dict[str, str]]:
    payload = sources_status()
    rows = []
    for probe in payload.get("probes", []):
        rows.append(
            {
                "name": str(probe.get("name", "-")),
                "source": str(probe.get("source") or probe.get("error") or "-"),
                "ok": "OK" if probe.get("ok") else "FAIL",
            }
        )
    return rows


def save_research_ia_path() -> None:
    steps = [
        ("市场总览", "/trading", "行情、恐贪、板块\n给出研究背景"),
        ("机会雷达", "/radar", "候选、排名、理由\n形成研究队列"),
        ("数据源", "/data-sources", "来源、模式、失败\n确认证据可靠性"),
        ("策略回测", "/backtests", "收益、回撤、成本\n验证假设"),
        ("风控中心", "/risk", "规则、阻断、停止线\n决定是否暂停"),
        ("研究报告", "/research", "结论、引用、边界\n输出观察"),
    ]
    colors = [BLUE, TEAL, ORANGE, PURPLE, RED, "#334155"]
    fig, ax = plt.subplots(figsize=(13, 4.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "研究路径按决策链组织，而不是按后端模块堆功能", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    x0 = 0.04
    width = 0.13
    gap = 0.025
    for i, ((title, path, body), color) in enumerate(zip(steps, colors, strict=True)):
        x = x0 + i * (width + gap)
        ax.add_patch(Rectangle((x, 0.34), width, 0.38, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.text(x + 0.012, 0.64, title, transform=ax.transAxes, fontsize=11.5, color=color, weight="bold")
        ax.text(x + 0.012, 0.56, path, transform=ax.transAxes, fontsize=9.8, color=INK)
        ax.text(x + 0.012, 0.49, body, transform=ax.transAxes, fontsize=9.2, color=INK, va="top")
        if i < len(steps) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.006, 0.53), (x + width + gap - 0.006, 0.53), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=13, linewidth=1.7, color=MUTED))
    ax.text(
        0.04,
        0.14,
        "来源：src/web/src/App.tsx 与 MainLayout.tsx；/strategy 和 /live-trading 是辅助/边界入口，不能替代主研究路径。",
        transform=ax.transAxes,
        fontsize=10.5,
        color=MUTED,
    )
    fig.savefig(OUT / "chapter-23-research-ia-path.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-23-research-ia-path.png")


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


def save_source_status_matrix() -> None:
    rows = source_probe_rows()
    fig, ax = plt.subplots(figsize=(11.2, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    names = [row["name"] for row in rows]
    values = [1 if row["ok"] == "OK" else 0 for row in rows]
    colors = [TEAL if value else RED for value in values]
    ax.barh(names, [1] * len(rows), color=colors, height=0.6)
    ax.set_xlim(0, 1.2)
    ax.set_xticks([])
    ax.invert_yaxis()
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    for idx, row in enumerate(rows):
        ax.text(0.03, idx, row["ok"], va="center", ha="left", color="#FFFFFF", weight="bold", fontsize=10.5)
        ax.text(1.03, idx, row["source"], va="center", ha="left", color=INK, fontsize=10)
    ax.text(
        0.0,
        -0.16,
        "来源：dashboard.api.sources_status()；离线样本、直连 API、上游代理和失败状态都要在界面可见。",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-23-source-status-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-23-source-status-matrix.png")


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
    save_route_inventory()
    save_api_evidence_bars()
    save_source_status_matrix()
    save_page_evidence_matrix()
    save_risk_boundary_card()


if __name__ == "__main__":
    main()
