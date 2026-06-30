"""Generate Chapter 34 publication figures."""

from __future__ import annotations

from pathlib import Path
import sys
from textwrap import fill
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from backtest.research_path import run_research_path  # noqa: E402
from backtest.rolling.service import run_cpcv_service, run_robustness_audit  # noqa: E402


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


def path_payload() -> dict[str, Any]:
    return run_research_path(include_audit=True)


def save_research_path_contracts() -> None:
    steps = [
        ("信号", "signal\nscore / evidence"),
        ("策略", "strategy\nparams / rules"),
        ("回测", "trades\nequity / metrics"),
        ("审计", "DSR / PBO\nCPCV / trials"),
        ("风控", "risk_findings\nrule_id"),
        ("Web", "API payload\nvisible state"),
    ]
    colors = [BLUE, TEAL, ORANGE, PURPLE, RED, "#0891B2"]
    fig, ax = plt.subplots(figsize=(13.6, 4.9), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "贯通不是只看页面 200，而是每段合同字段能反查", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    width = 0.13
    gap = 0.026
    for i, ((title, body), color) in enumerate(zip(steps, colors, strict=True)):
        x = 0.04 + i * (width + gap)
        ax.add_patch(Rectangle((x, 0.34), width, 0.38, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.text(x + 0.012, 0.64, title, transform=ax.transAxes, fontsize=11, color=color, weight="bold")
        ax.text(x + 0.012, 0.54, body, transform=ax.transAxes, fontsize=8.7, color=INK, va="top")
        if i < len(steps) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.005, 0.53), (x + width + gap - 0.006, 0.53), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=13, linewidth=1.6, color=MUTED))
    ax.text(0.04, 0.15, "对应代码：backtest.research_path、backtest.rolling.service、risk.simulation、app.py API routes、src/web/src/api.ts。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-34-research-path-contracts.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-34-research-path-contracts.png")


def save_path_layer_status() -> None:
    payload = path_payload()
    steps = payload["path"]
    labels = [item["name"] for item in steps]
    categories = ["core" if item["step"] <= 6 else "audit" for item in steps]
    values = [1 if category == "core" else 0.75 for category in categories]
    colors = [TEAL if category == "core" else ORANGE for category in categories]
    fig, ax = plt.subplots(figsize=(12.6, 6.2), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.barh(labels, values, color=colors)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.15)
    ax.set_xlabel("合同覆盖")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(0.0, -0.12, "run_research_path(include_audit=True) 当前返回 10 个步骤；后 4 个步骤用于防止只看样本内结果。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-34-path-layer-status.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-34-path-layer-status.png")


def save_metric_consistency_chart() -> None:
    payload = path_payload()
    rows = [
        ("report", payload["report_summary"]["strategy_return_pct"], abs(payload["report_summary"]["maximum_drawdown_pct"])),
        ("rolling", payload["rolling_summary"]["total_return_pct"], abs(payload["rolling_summary"]["max_drawdown_pct"])),
        ("realistic", payload["realistic_cost_summary"]["total_return_pct"], 0),
    ]
    labels = [row[0] for row in rows]
    returns = [float(row[1] or 0) for row in rows]
    drawdowns = [float(row[2] or 0) for row in rows]
    fig, ax = plt.subplots(figsize=(11.8, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    x = list(range(len(rows)))
    ax.bar([i - 0.18 for i in x], returns, width=0.36, color=TEAL, label="return %")
    ax.bar([i + 0.18 for i in x], drawdowns, width=0.36, color=ORANGE, label="abs drawdown %")
    ax.axhline(0, color=GRID, linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    ax.text(0.0, -0.17, "页面展示的指标必须能反查到同一次 API payload；不同口径不能混写成单一结论。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-34-metric-consistency-chart.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-34-metric-consistency-chart.png")


def save_audit_stopline_dashboard() -> None:
    payload = path_payload()
    audit = payload["audit_summary"]
    robustness = run_robustness_audit(strategy_name="ma_crossover", limit=120)
    cpcv = run_cpcv_service(strategy_name="ma_crossover", limit=120)
    rows = [
        ("DSR", float(audit.get("dsr") or 0), "higher"),
        ("PBO", float((robustness.get("pbo") or {}).get("pbo") or 0), "lower"),
        ("stability", float(audit.get("stability_score") or 0), "higher"),
        ("CPCV p50", float((cpcv.get("cpcv") or {}).get("sharpe_p50") or 0), "higher"),
        ("trials", float(audit.get("num_trials") or 0), "record"),
    ]
    labels = [row[0] for row in rows]
    values = [row[1] for row in rows]
    colors = [TEAL, RED if values[1] > 0.5 else TEAL, ORANGE, BLUE, PURPLE]
    fig, ax = plt.subplots(figsize=(11.8, 5.7), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar(labels, values, color=colors)
    ax.axhline(0.5, color=RED, linestyle="--", linewidth=1.2, label="PBO stopline 0.5")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for i, value in enumerate(values):
        ax.text(i, value + max(values + [1]) * 0.03, f"{value:.2f}", ha="center", fontsize=9, color=INK)
    ax.legend(frameon=False)
    ax.text(0.0, -0.18, "PBO > 0.5、DSR 不显著或 trial 账本缺失，都应让研究路径进入复测或拒绝。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-34-audit-stopline-dashboard.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-34-audit-stopline-dashboard.png")


def save_api_route_map() -> None:
    rows = [
        ("/api/dashboard/signal-analysis", "signal", "logicFlow"),
        ("/api/dashboard/backtest", "backtest", "trades/equity"),
        ("/api/dashboard/backtest/compare", "compare", "strategies"),
        ("/api/dashboard/backtest/audit", "audit", "num_trials"),
        ("/api/dashboard/backtest/robustness", "robust", "pbo/stability"),
        ("/api/dashboard/backtest/cpcv", "cpcv", "sharpe_p50"),
        ("/api/dashboard/backtest/pit", "pit", "validation"),
    ]
    fig, ax = plt.subplots(figsize=(12.2, 6.0), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.91, "Web 展示不是证据源：页面字段必须反查到 API payload", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    headers = ["API", "层级", "验收字段"]
    col_x = [0.04, 0.53, 0.68]
    col_w = [0.45, 0.11, 0.22]
    y0 = 0.80
    row_h = 0.095
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.075, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.01, y0 + 0.049, header, transform=ax.transAxes, fontsize=10.2, color="#FFFFFF", weight="bold", va="center")
    for r, row in enumerate(rows):
        y = y0 - (r + 1) * row_h
        bg = "#FFFFFF" if r % 2 == 0 else "#F1F5F9"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=bg, edgecolor=GRID, linewidth=1))
            ax.text(x + 0.01, y + row_h * 0.58, fill(value, 34), transform=ax.transAxes, fontsize=9.3, color=INK, va="center")
    ax.text(0.04, 0.04, "对应路由来自 app.py 与 src/web/src/api.ts；浏览器截图必须能追到这些 payload 字段。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-34-api-route-map.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-34-api-route-map.png")


def save_web_traceability_matrix() -> None:
    fields = ["api", "window", "cost", "trades", "risk", "audit"]
    pages = [
        ("signal", [1, 1, 0, 0, 0, 1]),
        ("backtest", [1, 1, 1, 1, 1, 1]),
        ("compare", [1, 1, 1, 1, 0, 1]),
        ("risk", [1, 1, 0, 0, 1, 1]),
        ("audit", [1, 1, 1, 0, 1, 1]),
    ]
    fig, ax = plt.subplots(figsize=(11.6, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    for y, (_, values) in enumerate(pages):
        for x, value in enumerate(values):
            color = TEAL if value else ORANGE
            ax.add_patch(Rectangle((x, y), 1, 1, facecolor=color, edgecolor="#FFFFFF", linewidth=2))
            ax.text(x + 0.5, y + 0.5, "ok" if value else "n/a", ha="center", va="center", fontsize=8.5, color="#FFFFFF")
    ax.set_xlim(0, len(fields))
    ax.set_ylim(0, len(pages))
    ax.set_xticks([i + 0.5 for i in range(len(fields))])
    ax.set_xticklabels(fields)
    ax.set_yticks([i + 0.5 for i in range(len(pages))])
    ax.set_yticklabels([row[0] for row in pages])
    ax.invert_yaxis()
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.text(0.0, -0.16, "backtest 页必须覆盖成本、成交、风险和审计；compare 页不展示 risk 时要在报告中补充风险复核。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-34-web-traceability-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-34-web-traceability-matrix.png")


def main() -> None:
    setup_matplotlib()
    OUT.mkdir(parents=True, exist_ok=True)
    save_research_path_contracts()
    save_path_layer_status()
    save_metric_consistency_chart()
    save_audit_stopline_dashboard()
    save_api_route_map()
    save_web_traceability_matrix()


if __name__ == "__main__":
    main()
