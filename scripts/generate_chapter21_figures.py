"""Generate Chapter 21 publication figures."""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from backtest.rolling.service import (  # noqa: E402
    compare_windows,
    run_cpcv_service,
    run_robustness_audit,
    run_walk_forward,
)


def setup_matplotlib() -> None:
    plt.rcParams["font.sans-serif"] = [
        "SimHei",
        "Microsoft YaHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def save_compare_windows() -> None:
    payload = compare_windows(strategy_name="ma_crossover", num_windows=3, limit=120)
    rows = payload["windows"]
    labels = [f"W{row['window']}" for row in rows]
    returns = [float(row["total_return_pct"]) for row in rows]
    drawdowns = [float(row["max_drawdown_pct"]) for row in rows]
    trades = [int(row["total_trades"]) for row in rows]

    x_pos = list(range(len(labels)))
    width = 0.34
    fig, ax1 = plt.subplots(figsize=(10.5, 5.8), dpi=160)
    fig.patch.set_facecolor("#F7F9FC")
    ax1.set_facecolor("#FFFFFF")
    ax1.bar([x - width / 2 for x in x_pos], returns, width=width, color="#2563EB", label="总收益 %")
    ax1.bar([x + width / 2 for x in x_pos], drawdowns, width=width, color="#DC2626", label="最大回撤 %")
    ax1.axhline(0, color="#94A3B8", linewidth=1)
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(labels)
    ax1.set_ylabel("百分比")
    ax1.set_title("同一策略在连续窗口中的表现", fontsize=15, loc="left")
    ax1.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax1.spines[["top", "right"]].set_visible(False)

    ax2 = ax1.twinx()
    ax2.plot(x_pos, trades, color="#0F766E", marker="o", linewidth=2, label="交易次数")
    ax2.set_ylabel("交易次数")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
    ax1.text(
        0.01,
        -0.18,
        f"strategy={payload['strategy_key']}，positive_windows={payload['positive_windows']}，stable={payload['stable']}。",
        transform=ax1.transAxes,
        fontsize=10,
        color="#64748B",
    )
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "chapter-21-compare-windows.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-21-compare-windows.png")


def save_walk_forward() -> None:
    payload = run_walk_forward(strategy_name="ma_crossover", num_windows=2, limit=120)
    labels = ["样本内 Sharpe", "样本外 Sharpe", "DSR"]
    values = [
        float(payload["in_sample_sharpe"]),
        float(payload["out_of_sample_sharpe"]),
        float(payload["dsr"]),
    ]
    colors = ["#2563EB", "#F59E0B", "#DC2626"]

    fig, ax = plt.subplots(figsize=(9.6, 5.6), dpi=160)
    fig.patch.set_facecolor("#F7F9FC")
    ax.set_facecolor("#FFFFFF")
    bars = ax.bar(labels, values, color=colors, width=0.55)
    ax.axhline(0, color="#94A3B8", linewidth=1)
    ax.set_title("Walk-forward：样本内、样本外与 DSR", fontsize=15, loc="left")
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.2f}", ha="center", va="bottom", fontsize=11)
    ax.text(
        0.01,
        -0.18,
        f"best_params={payload['best_params']}，num_trials={payload['num_trials']}，overfit_warning={payload['overfit_warning']}。",
        transform=ax.transAxes,
        fontsize=10,
        color="#64748B",
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-21-walkforward-sharpe.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-21-walkforward-sharpe.png")


def save_cpcv_distribution() -> None:
    payload = run_cpcv_service(strategy_name="ma_crossover", limit=120)
    cpcv = payload["cpcv"]
    path_sharpes = [float(row["sharpe"]) for row in cpcv["paths"]]

    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=160)
    fig.patch.set_facecolor("#F7F9FC")
    ax.set_facecolor("#FFFFFF")
    ax.hist(path_sharpes, bins=min(8, max(4, len(path_sharpes))), color="#60A5FA", edgecolor="#1E40AF", alpha=0.9)
    for value, color, label in (
        (float(cpcv["sharpe_p5"]), "#F59E0B", "p5"),
        (float(cpcv["sharpe_p50"]), "#DC2626", "p50"),
        (float(cpcv["sharpe_p95"]), "#0F766E", "p95"),
    ):
        ax.axvline(value, color=color, linestyle="--", linewidth=2, label=f"Sharpe {label}={value:.2f}")
    ax.set_title("CPCV 多条样本外路径的 Sharpe 分布", fontsize=15, loc="left")
    ax.set_xlabel("样本外 Sharpe")
    ax.set_ylabel("路径数量")
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper right")
    ax.text(
        0.01,
        -0.18,
        f"num_paths={cpcv['num_paths']}，profitable_paths={cpcv['profitable_paths_pct']}%，verdict={cpcv['verdict']}。",
        transform=ax.transAxes,
        fontsize=10,
        color="#64748B",
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-21-cpcv-sharpe-dist.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-21-cpcv-sharpe-dist.png")


def save_parameter_sensitivity() -> None:
    payload = run_robustness_audit(strategy_name="ma_crossover", limit=120)
    rows = payload["parameter_sensitivity"]["perturbations"]
    labels = [f"{row['param']}\n{row['direction']}" for row in rows]
    drift = [float(row["return_drift_pct"]) for row in rows]
    colors = ["#0F766E" if row["stable"] else "#DC2626" for row in rows]

    fig, ax = plt.subplots(figsize=(11.5, 5.8), dpi=160)
    fig.patch.set_facecolor("#F7F9FC")
    ax.set_facecolor("#FFFFFF")
    ax.bar(labels, drift, color=colors, width=0.6)
    ax.axhline(30, color="#F59E0B", linestyle="--", linewidth=1.5, label="30% 漂移参考线")
    ax.set_title("参数扰动后的收益漂移", fontsize=15, loc="left")
    ax.set_ylabel("收益漂移（%）")
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper right")
    ax.text(
        0.01,
        -0.24,
        f"stability_score={payload['parameter_sensitivity']['stability_score']}，PBO={payload['pbo']['pbo']}，verdict={payload['verdict']}。",
        transform=ax.transAxes,
        fontsize=10,
        color="#64748B",
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-21-parameter-sensitivity.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-21-parameter-sensitivity.png")


def main() -> None:
    setup_matplotlib()
    save_compare_windows()
    save_walk_forward()
    save_cpcv_distribution()
    save_parameter_sensitivity()


if __name__ == "__main__":
    main()
