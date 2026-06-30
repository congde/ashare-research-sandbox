"""Generate Chapter 33 publication figures."""

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
from backtest.trace import run_teaching_scenario  # noqa: E402
from risk import ExecutionBoundaryRequest, classify_execution_request  # noqa: E402


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


def save_sim_trading_boundary() -> None:
    steps = [
        ("数据", "prices.csv\nsnapshot"),
        ("信号", "rule signal\nLLM fallback"),
        ("策略", "MA crossover\nparameters"),
        ("回测", "event engine\nrolling engine"),
        ("风控", "RiskManager\nrejections"),
        ("Web", "API / page\nresearch only"),
    ]
    colors = [BLUE, TEAL, ORANGE, PURPLE, RED, "#0891B2"]
    fig, ax = plt.subplots(figsize=(13.6, 4.9), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "端到端模拟交易系统验证研究流程，不提供真实订单能力", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    width = 0.13
    gap = 0.026
    for i, ((title, body), color) in enumerate(zip(steps, colors, strict=True)):
        x = 0.04 + i * (width + gap)
        ax.add_patch(Rectangle((x, 0.34), width, 0.38, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.text(x + 0.012, 0.64, title, transform=ax.transAxes, fontsize=11, color=color, weight="bold")
        ax.text(x + 0.012, 0.54, body, transform=ax.transAxes, fontsize=8.7, color=INK, va="top")
        if i < len(steps) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.005, 0.53), (x + width + gap - 0.006, 0.53), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=13, linewidth=1.6, color=MUTED))
    ax.text(0.04, 0.15, "对应代码：backtest.research_path、backtest.trace、strategy_engine.backtest.engine、risk.execution_boundary。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-33-sim-trading-boundary.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-33-sim-trading-boundary.png")


def save_research_path_steps() -> None:
    payload = path_payload()
    steps = payload["path"]
    labels = [f"{item['step']}. {item['name']}" for item in steps]
    values = [item["step"] for item in steps]
    colors = [TEAL if item["step"] <= 6 else ORANGE for item in steps]
    fig, ax = plt.subplots(figsize=(12.4, 6.2), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.barh(labels, values, color=colors)
    ax.invert_yaxis()
    ax.set_xlabel("路径步骤")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(0.0, -0.12, "前 6 步是核心模拟闭环；后 4 步是走向交付前必须补齐的样本外和审计检查。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-33-research-path-steps.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-33-research-path-steps.png")


def save_metrics_bridge_card() -> None:
    payload = path_payload()
    rows = [
        ("event report", payload["report_summary"]["strategy_return_pct"], payload["report_summary"]["maximum_drawdown_pct"], payload["report_summary"]["trade_count"]),
        ("rolling", payload["rolling_summary"]["total_return_pct"], payload["rolling_summary"]["max_drawdown_pct"], payload["rolling_summary"]["total_trades"]),
        ("realistic cost", payload["realistic_cost_summary"]["total_return_pct"], None, None),
    ]
    labels = [row[0] for row in rows]
    returns = [float(row[1] or 0) for row in rows]
    drawdowns = [abs(float(row[2] or 0)) for row in rows]
    fig, ax = plt.subplots(figsize=(11.8, 5.8), dpi=160)
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
    for i, row in enumerate(rows):
        trades = "-" if row[3] is None else str(row[3])
        ax.text(i, max(returns[i], drawdowns[i]) + 1, f"trades={trades}", ha="center", fontsize=9, color=INK)
    ax.legend(frameon=False)
    ax.text(0.0, -0.18, "同一策略在事件引擎、滚动引擎、真实成本预设中口径不同，不能只摘一个最漂亮数字。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-33-metrics-bridge-card.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-33-metrics-bridge-card.png")


def save_fill_pending_risk_timeline() -> None:
    payload = run_teaching_scenario()
    bars = payload["bars"]
    labels = [row["date"] for row in bars]
    close = [row["close"] for row in bars]
    fig, ax = plt.subplots(figsize=(12.2, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.plot(labels, close, color=BLUE, marker="o", linewidth=2)
    for i, row in enumerate(bars):
        if "fill" in row:
            ax.scatter([labels[i]], [close[i]], s=150, color=TEAL, zorder=3)
            ax.text(i, close[i] + 1.5, "fill", ha="center", fontsize=9, color=TEAL, weight="bold")
        if "risk_block" in row:
            ax.scatter([labels[i]], [close[i]], s=150, color=RED, zorder=3)
            ax.text(i, close[i] + 1.5, row["risk_block"]["rule_id"], ha="center", fontsize=8.5, color=RED, weight="bold")
    ax.set_ylabel("close")
    ax.tick_params(axis="x", rotation=24)
    ax.grid(color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(0.0, -0.24, "run_teaching_scenario() 构造 market fill、pending limit、MAX_POSITION_PCT risk block 三类事件。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-33-fill-pending-risk-timeline.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-33-fill-pending-risk-timeline.png")


def save_execution_boundary_matrix() -> None:
    requests = [
        ("record_signal", "none", False),
        ("dry_run_order", "none", False),
        ("dry_run_order", "simulation_only", False),
        ("dry_run_order", "simulation_only", True),
        ("real_order", "simulation_only", True),
        ("real_order", "real_order", True),
    ]
    rows = []
    for action, capability, confirmed in requests:
        result = classify_execution_request(
            ExecutionBoundaryRequest(
                symbol="WEB3-DEMO/USDT",
                signal="BUY",
                requested_action=action,  # type: ignore[arg-type]
                capability=capability,  # type: ignore[arg-type]
                human_confirmed=confirmed,
            )
        )
        rows.append((action, capability, str(confirmed), result.outcome))
    fig, ax = plt.subplots(figsize=(12.0, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.91, "模拟交易入口必须先过执行边界，real_order 永远 blocked", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    headers = ["请求动作", "能力", "人工确认", "结果"]
    col_x = [0.04, 0.31, 0.53, 0.70]
    col_w = [0.22, 0.18, 0.13, 0.18]
    y0 = 0.79
    row_h = 0.105
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.078, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.01, y0 + 0.05, header, transform=ax.transAxes, fontsize=10.2, color="#FFFFFF", weight="bold", va="center")
    for r, row in enumerate(rows):
        y = y0 - (r + 1) * row_h
        bg = "#FFFFFF" if r % 2 == 0 else "#F1F5F9"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=bg, edgecolor=GRID, linewidth=1))
            color = RED if value == "blocked" else TEAL if value == "dry_run" else INK
            ax.text(x + 0.01, y + row_h * 0.58, fill(value, 20), transform=ax.transAxes, fontsize=9.5, color=color, va="center")
    ax.text(0.04, 0.04, "即使 human_confirmed=True，只要请求 real_order 或能力 real_order，研究沙箱也必须阻断。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-33-execution-boundary-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-33-execution-boundary-matrix.png")


def save_contract_completeness_matrix() -> None:
    fields = ["source", "version", "state", "risk", "cost", "audit"]
    modules = [
        ("data", [1, 1, 1, 0, 0, 1]),
        ("signal", [1, 1, 1, 0, 0, 1]),
        ("strategy", [1, 1, 1, 1, 0, 1]),
        ("backtest", [1, 1, 1, 1, 1, 1]),
        ("risk", [1, 1, 1, 1, 0, 1]),
        ("web", [1, 1, 1, 1, 0, 1]),
    ]
    fig, ax = plt.subplots(figsize=(11.8, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    for y, (_, values) in enumerate(modules):
        for x, value in enumerate(values):
            color = TEAL if value else ORANGE
            ax.add_patch(Rectangle((x, y), 1, 1, facecolor=color, edgecolor="#FFFFFF", linewidth=2))
            ax.text(x + 0.5, y + 0.5, "ok" if value else "n/a", ha="center", va="center", fontsize=8.5, color="#FFFFFF")
    ax.set_xlim(0, len(fields))
    ax.set_ylim(0, len(modules))
    ax.set_xticks([i + 0.5 for i in range(len(fields))])
    ax.set_xticklabels(fields)
    ax.set_yticks([i + 0.5 for i in range(len(modules))])
    ax.set_yticklabels([item[0] for item in modules])
    ax.invert_yaxis()
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.text(0.0, -0.17, "每个模块至少要说清来源、版本、状态和审计；只有回测层必须完整说明成本口径。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-33-contract-completeness-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-33-contract-completeness-matrix.png")


def main() -> None:
    setup_matplotlib()
    OUT.mkdir(parents=True, exist_ok=True)
    save_sim_trading_boundary()
    save_research_path_steps()
    save_metrics_bridge_card()
    save_fill_pending_risk_timeline()
    save_execution_boundary_matrix()
    save_contract_completeness_matrix()


if __name__ == "__main__":
    main()
