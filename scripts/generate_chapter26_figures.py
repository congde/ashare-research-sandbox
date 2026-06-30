"""Generate Chapter 26 publication figures."""

from __future__ import annotations

from pathlib import Path
import sys
from textwrap import fill

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from backtest.rolling.service import (  # noqa: E402
    compare_strategies,
    compare_windows,
    execute_backtest,
    run_cpcv_service,
    run_robustness_audit,
    run_walk_forward,
)
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


def _bt() -> dict:
    return execute_backtest(
        strategy_name="ma_crossover",
        symbol="BTC-USDT",
        limit=120,
        stop_loss_pct=3,
        take_profit_pct=5,
        cost_preset="teaching",
    )


def save_backtest_risk_center() -> None:
    steps = [
        ("信号证据", "K线页面\n规则信号"),
        ("回测实验", "strategy / symbol\nSL / TP / cost"),
        ("绩效证据", "equity / trades\nreturn / DD / Sharpe"),
        ("稳健审计", "windows / WFO\nDSR / PBO / CPCV"),
        ("风险中心", "rules / rejections\nreason / stop line"),
        ("处理决定", "继续 / 复测\n修改 / 停止"),
    ]
    colors = [BLUE, TEAL, ORANGE, PURPLE, RED, "#334155"]
    fig, ax = plt.subplots(figsize=(13, 4.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "回测页和风险页必须共享同一条证据链", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    x0 = 0.04
    width = 0.125
    gap = 0.03
    for i, ((title, body), color) in enumerate(zip(steps, colors, strict=True)):
        x = x0 + i * (width + gap)
        ax.add_patch(Rectangle((x, 0.34), width, 0.38, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.text(x + 0.01, 0.64, title, transform=ax.transAxes, fontsize=11.3, color=color, weight="bold")
        ax.text(x + 0.01, 0.55, body, transform=ax.transAxes, fontsize=8.8, color=INK, va="top")
        if i < len(steps) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.006, 0.53), (x + width + gap - 0.006, 0.53), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=13, linewidth=1.7, color=MUTED))
    ax.text(0.04, 0.14, "对应页面：/backtests 运行实验，/risk 解释 RiskManager 阻断；页面通过不等于策略放行。", transform=ax.transAxes, fontsize=10.2, color=MUTED)
    fig.savefig(OUT / "chapter-26-backtest-risk-center.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-26-backtest-risk-center.png")


def save_equity_drawdown_chart() -> None:
    payload = _bt()
    curve = payload.get("equity_curve") or []
    x = list(range(len(curve)))
    equity = [float(row.get("equity") or 0) for row in curve]
    peaks: list[float] = []
    current_peak = 0.0
    drawdown: list[float] = []
    for value in equity:
        current_peak = max(current_peak, value)
        peaks.append(current_peak)
        drawdown.append((value / current_peak - 1) * 100 if current_peak else 0)
    fig, ax1 = plt.subplots(figsize=(11.6, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax1.set_facecolor("#FFFFFF")
    ax1.plot(x, equity, color=BLUE, linewidth=2, label="equity")
    ax1.plot(x, peaks, color=TEAL, linewidth=1.4, linestyle="--", label="peak")
    idx_to_pos = {int(row.get("idx", pos)): pos for pos, row in enumerate(curve)}
    for trade in payload.get("trades") or []:
        entry_pos = idx_to_pos.get(int(trade["entryIdx"]))
        exit_pos = idx_to_pos.get(int(trade["exitIdx"]))
        if entry_pos is not None:
            ax1.scatter(entry_pos, equity[entry_pos], color=TEAL, s=50, zorder=3)
        if exit_pos is not None:
            ax1.scatter(exit_pos, equity[exit_pos], color=RED, s=50, zorder=3)
    ax2 = ax1.twinx()
    ax2.fill_between(x, drawdown, 0, color=RED, alpha=0.16, label="drawdown")
    ax2.set_ylabel("回撤 %")
    ax1.set_ylabel("权益")
    ax1.grid(color=GRID, linewidth=0.8)
    ax1.spines[["top"]].set_visible(False)
    ax2.spines[["top"]].set_visible(False)
    ax1.legend(frameon=False, loc="upper left")
    ax2.legend(frameon=False, loc="lower left")
    ax1.text(
        0.0,
        -0.18,
        f"BTC-USDT ma_crossover: return={payload['total_return_pct']}%, maxDD={payload['max_drawdown_pct']}%, trades={payload['total_trades']}, cost={payload['cost_preset']}.",
        transform=ax1.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-26-equity-drawdown-trades.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-26-equity-drawdown-trades.png")


def save_strategy_compare_chart() -> None:
    payload = compare_strategies(symbol="BTC-USDT", limit=120, cost_preset="teaching")
    rows = payload["strategies"]
    labels = [row["strategy_key"] for row in rows]
    returns = [float(row["total_return_pct"]) for row in rows]
    drawdowns = [float(row["max_drawdown_pct"]) for row in rows]
    x = list(range(len(labels)))
    width = 0.34
    fig, ax = plt.subplots(figsize=(11.4, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar([i - width / 2 for i in x], returns, width=width, color=[TEAL if v >= 0 else RED for v in returns], label="收益 %")
    ax.bar([i + width / 2 for i in x], drawdowns, width=width, color=ORANGE, label="最大回撤 %")
    ax.axhline(0, color="#94A3B8", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("百分比")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    ax.text(0.0, -0.24, f"leader={payload['leader']}，laggard={payload['laggard']}；统一 BTC-USDT 100 根快照 K 线。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-26-strategy-compare-chart.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-26-strategy-compare-chart.png")


def save_windows_wfo_chart() -> None:
    windows = compare_windows(strategy_name="ma_crossover", symbol="BTC-USDT", limit=120, cost_preset="teaching")
    wfo = run_walk_forward(strategy_name="ma_crossover", symbol="BTC-USDT", limit=120, cost_preset="teaching")
    labels = [f"W{row['window']}" for row in windows["windows"]]
    returns = [float(row["total_return_pct"]) for row in windows["windows"]]
    fig, ax = plt.subplots(figsize=(10.8, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar(labels, returns, color=[TEAL if v > 0 else RED if v < 0 else "#94A3B8" for v in returns], label="窗口收益")
    ax.axhline(0, color="#94A3B8", linewidth=1)
    for row in wfo["windows"]:
        idx = int(row["window"]) - 1
        if 0 <= idx < len(labels):
            ax.scatter(idx, float(row["outOfSampleReturn"]), color=ORANGE, s=90, zorder=3)
            ax.text(idx, float(row["outOfSampleReturn"]) + 0.6, "OOS", ha="center", fontsize=9, color=INK)
    ax.set_ylabel("收益 %")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(
        0.0,
        -0.18,
        f"positive_windows={windows['positive_windows']}/{windows['num_windows']}, stable={windows['stable']}; WFO DSR={wfo['dsr']}, OOS return={wfo['out_of_sample_return_pct']}%, warning={wfo['overfit_warning']}.",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-26-windows-wfo-chart.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-26-windows-wfo-chart.png")


def save_robustness_cpcv_chart() -> None:
    robust = run_robustness_audit(strategy_name="ma_crossover", symbol="BTC-USDT", limit=120, cost_preset="teaching")
    cpcv = run_cpcv_service(strategy_name="ma_crossover", symbol="BTC-USDT", limit=120, cost_preset="teaching")["cpcv"]
    perturbs = robust["parameter_sensitivity"]["perturbations"]
    labels = [f"{row['param']}\n{row['direction']}" for row in perturbs]
    returns = [float(row["total_return_pct"]) for row in perturbs]
    fig, ax = plt.subplots(figsize=(11.4, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar(labels, returns, color=[TEAL if v >= 0 else RED for v in returns], label="扰动收益")
    ax.axhline(float(robust["parameter_sensitivity"]["baseline_return_pct"]), color=BLUE, linestyle="--", linewidth=1.6, label="baseline")
    paths = [float(row["return_pct"]) for row in cpcv["paths"]]
    ax.scatter([len(labels) + 0.6] * len(paths), paths, color=ORANGE, s=60, alpha=0.85, label="CPCV paths")
    ax.set_xticks(list(range(len(labels))) + [len(labels) + 0.6])
    ax.set_xticklabels(labels + ["CPCV\npaths"], fontsize=8.5)
    ax.set_ylabel("收益 %")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper right")
    ax.text(
        0.0,
        -0.2,
        f"stability={robust['parameter_sensitivity']['stability_score']}, PBO={robust['pbo']['pbo']}, CPCV p50={cpcv['return_p50']}%, verdict={cpcv['verdict']}.",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-26-robustness-cpcv-chart.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-26-robustness-cpcv-chart.png")


def save_risk_rejection_card() -> None:
    report = build_report(short=3, long=7)
    checks = report["risk_checks"]
    runtime = next((item for item in checks if item["phase"] == "pre_trade"), None)
    first = (report["backtest"]["risk_rejections"] or [{}])[0]
    rows = [
        ("活跃规则", ", ".join(report["backtest"]["risk_rules"][:3]) + " ...", "页面显示规则栈"),
        ("运行期拦截", f"{runtime['rule_id']} {runtime['count']}x" if runtime else "无", "风险中心计数"),
        ("首笔阻断", f"{first.get('date')} {first.get('side')}", "可定位订单意图"),
        ("阻断原因", first.get("reason", "-"), "不能只写失败"),
        ("后测复核", next((x["rule_id"] for x in checks if x["phase"] != "pre_trade"), "无"), "策略是否低于基准"),
    ]
    fig, ax = plt.subplots(figsize=(12, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.91, "风险中心必须解释阻断，而不是只列规则名", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    col_x = [0.05, 0.25, 0.62]
    col_w = [0.16, 0.33, 0.25]
    headers = ["检查", "真实结果", "页面职责"]
    y0 = 0.78
    row_h = 0.11
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.07, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.012, y0 + 0.035, header, transform=ax.transAxes, va="center", fontsize=10.8, color="#FFFFFF", weight="bold")
    for i, row in enumerate(rows):
        y = y0 - (i + 1) * row_h
        fill_color = "#FFFFFF" if i % 2 == 0 else "#F8FAFC"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=fill_color, edgecolor=GRID))
            ax.text(x + 0.012, y + row_h / 2, fill(str(value), 42), transform=ax.transAxes, va="center", fontsize=9.4, color=INK)
    ax.text(0.05, 0.05, "来源：research.report.build_report(short=3,long=7) 与 risk.simulation.evaluate_backtest_risk。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-26-risk-rejection-card.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-26-risk-rejection-card.png")


def save_cost_preset_chart() -> None:
    rows = []
    for preset in ["teaching", "realistic", "perp"]:
        payload = execute_backtest(
            strategy_name="ma_crossover",
            symbol="BTC-USDT",
            limit=120,
            stop_loss_pct=3,
            take_profit_pct=5,
            cost_preset=preset,
        )
        rows.append(payload)
    labels = [row["cost_preset"] for row in rows]
    returns = [float(row["total_return_pct"]) for row in rows]
    drawdowns = [float(row["max_drawdown_pct"]) for row in rows]
    x = list(range(len(labels)))
    width = 0.36
    fig, ax = plt.subplots(figsize=(9.8, 5.4), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar([i - width / 2 for i in x], returns, width=width, color=TEAL, label="收益 %")
    ax.bar([i + width / 2 for i in x], drawdowns, width=width, color=RED, label="最大回撤 %")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    ax.text(0.0, -0.18, "同一策略、同一样本下比较 teaching / realistic / perp；页面必须显示成本口径。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-26-cost-preset-chart.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-26-cost-preset-chart.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    setup_matplotlib()
    save_backtest_risk_center()
    save_equity_drawdown_chart()
    save_strategy_compare_chart()
    save_windows_wfo_chart()
    save_robustness_cpcv_chart()
    save_risk_rejection_card()
    save_cost_preset_chart()


if __name__ == "__main__":
    main()
