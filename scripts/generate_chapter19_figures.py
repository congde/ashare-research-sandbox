"""Generate Chapter 19 publication figures."""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from backtest.audit.dsr import deflated_sharpe_ratio  # noqa: E402
from backtest.metrics_explain import explain_metrics  # noqa: E402
from backtest.trace import run_ma_crossover_trace  # noqa: E402


def setup_matplotlib() -> None:
    plt.rcParams["font.sans-serif"] = [
        "SimHei",
        "Microsoft YaHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def save_equity_drawdown() -> None:
    trace = run_ma_crossover_trace()
    trail = trace["trail"]
    steps = [item["step"] for item in trail]
    equity = [float(item["equity_after"] or 0.0) for item in trail]

    peak = []
    drawdown = []
    current_peak = equity[0]
    for value in equity:
        current_peak = max(current_peak, value)
        peak.append(current_peak)
        drawdown.append(value / current_peak - 1.0)

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), dpi=160, sharex=True)
    fig.patch.set_facecolor("#F7F9FC")
    for ax in axes:
        ax.set_facecolor("#FFFFFF")
        ax.grid(color="#E5E7EB", linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)

    axes[0].plot(steps, equity, color="#2563EB", marker="o", linewidth=2, label="权益")
    axes[0].plot(steps, peak, color="#0F766E", linestyle="--", linewidth=1.8, label="历史峰值")
    axes[0].set_title("权益路径先于压缩指标", fontsize=15, loc="left")
    axes[0].set_ylabel("权益")
    axes[0].legend(loc="upper left")

    axes[1].fill_between(steps, [value * 100 for value in drawdown], 0, color="#DC2626", alpha=0.25)
    axes[1].plot(steps, [value * 100 for value in drawdown], color="#DC2626", linewidth=1.8)
    axes[1].set_xlabel("成交序号")
    axes[1].set_ylabel("回撤（%）")
    axes[1].set_title("每个时点都相对历史峰值复算回撤", fontsize=13, loc="left")
    axes[1].text(
        0.01,
        -0.28,
        "数据来自 backtest.trace.run_ma_crossover_trace()，用于教学复核，不代表投资建议。",
        transform=axes[1].transAxes,
        fontsize=10,
        color="#64748B",
    )

    OUT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-19-equity-drawdown.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-19-equity-drawdown.png")


def save_metrics_comparison() -> None:
    payload = explain_metrics(limit=120)
    rows = payload["strategies"]
    labels = [row["strategy"] for row in rows]
    returns = [float(row["total_return_pct"]) for row in rows]
    drawdowns = [float(row["max_drawdown_pct"]) for row in rows]
    calmars = [float(row["calmar_ratio"]) for row in rows]

    x_pos = list(range(len(labels)))
    width = 0.25
    fig, ax = plt.subplots(figsize=(12, 6.4), dpi=160)
    fig.patch.set_facecolor("#F7F9FC")
    ax.set_facecolor("#FFFFFF")
    ax.bar([x - width for x in x_pos], returns, width=width, color="#2563EB", label="总收益 %")
    ax.bar(x_pos, drawdowns, width=width, color="#DC2626", label="最大回撤 %")
    ax.bar([x + width for x in x_pos], calmars, width=width, color="#0F766E", label="卡玛比率")
    ax.axhline(0, color="#94A3B8", linewidth=1)
    ax.set_xticks(x_pos)
    ax.set_xticklabels(labels, rotation=18, ha="right")
    ax.set_title("同一批策略不能只按收益率排序", fontsize=15, loc="left")
    ax.set_ylabel("指标值")
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper left")
    ax.text(
        0.01,
        -0.28,
        f"engine={payload['engine']}，样本 K 线={payload['total_candles']}，数据来自 explain_metrics(limit=120)。",
        transform=ax.transAxes,
        fontsize=10,
        color="#64748B",
    )

    fig.tight_layout()
    fig.savefig(OUT / "chapter-19-metrics-comparison.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-19-metrics-comparison.png")


def save_dsr_vs_trials() -> None:
    observed_sr = 1.2
    sample_length = 120
    trial_counts = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233]
    dsrs = [
        float(deflated_sharpe_ratio(observed_sr, sample_length, count)["dsr"])
        for count in trial_counts
    ]
    psrs = [
        float(deflated_sharpe_ratio(observed_sr, sample_length, count)["psr"])
        for count in trial_counts
    ]

    fig, ax = plt.subplots(figsize=(11, 5.8), dpi=160)
    fig.patch.set_facecolor("#F7F9FC")
    ax.set_facecolor("#FFFFFF")
    ax.plot(trial_counts, psrs, color="#2563EB", linestyle="--", marker="s", linewidth=2, label="PSR 概率夏普")
    ax.plot(trial_counts, dsrs, color="#DC2626", marker="o", linewidth=2.3, label="DSR 去偏夏普")
    ax.axhline(0.95, color="#0F766E", linewidth=1.4, linestyle=":", label="0.95 参考线")
    ax.set_xscale("log")
    ax.set_ylim(0, 1.04)
    ax.set_xlabel("试验次数 num_trials（对数刻度）")
    ax.set_ylabel("概率值")
    ax.set_title("试验次数越多，去偏夏普越保守", fontsize=15, loc="left")
    ax.grid(color="#E5E7EB", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="lower left")
    ax.text(
        0.01,
        -0.24,
        "固定 observed_sr=1.2、sample_length=120；计算来自 backtest.audit.dsr.deflated_sharpe_ratio()。",
        transform=ax.transAxes,
        fontsize=10,
        color="#64748B",
    )

    fig.tight_layout()
    fig.savefig(OUT / "chapter-19-dsr-vs-trials.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-19-dsr-vs-trials.png")


def main() -> None:
    setup_matplotlib()
    save_equity_drawdown()
    save_metrics_comparison()
    save_dsr_vs_trials()


if __name__ == "__main__":
    main()
