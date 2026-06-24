"""Generate Chapter 20 publication figures."""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from backtest.pollution import run_pollution_checks  # noqa: E402
from backtest.trials import TrialLedger  # noqa: E402


def setup_matplotlib() -> None:
    plt.rcParams["font.sans-serif"] = [
        "SimHei",
        "Microsoft YaHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def save_pollution_gate() -> None:
    payload = run_pollution_checks()
    cases = payload["cases"]
    labels = [case["label"] for case in cases]
    columns = ["DSL 安全", "前视干净", "可进回测"]
    matrix = [
        [
            int(case["dsl_valid"]),
            int(case["lookahead_clean"]),
            int(case["backtest_ready"]),
        ]
        for case in cases
    ]

    fig, ax = plt.subplots(figsize=(10, 5.8), dpi=160)
    fig.patch.set_facecolor("#F7F9FC")
    colors = [["#0F766E" if value else "#DC2626" for value in row] for row in matrix]
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            ax.barh(y, 1, left=x, height=0.82, color=colors[y][x], edgecolor="#FFFFFF")
            ax.text(
                x + 0.5,
                y,
                "通过" if value else "拦截",
                ha="center",
                va="center",
                color="#FFFFFF",
                fontsize=12,
                fontweight="bold",
            )
    ax.set_xlim(0, len(columns))
    ax.set_ylim(-0.6, len(labels) - 0.4)
    ax.set_xticks([i + 0.5 for i in range(len(columns))])
    ax.set_xticklabels(columns)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_title("污染样本门禁结果", fontsize=15, loc="left")
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.text(
        0,
        len(labels) - 0.08,
        "safe_noop 可进回测；unsafe_import 被 DSL 拦截；lookahead_shift 被前视检查拦截。",
        fontsize=10,
        color="#64748B",
    )
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "chapter-20-overfit-pollution-gate.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-20-overfit-pollution-gate.png")


def save_trial_ledger_risk() -> None:
    ledger = TrialLedger()
    sample_rows = [
        ("grid_search", "ma_crossover", 0.8, 2.1),
        ("grid_search", "ma_crossover", 1.1, 3.2),
        ("grid_search", "ma_crossover", 1.4, 4.4),
        ("prompt_trial", "llm_signal", 0.5, 1.2),
        ("prompt_trial", "llm_signal", 1.0, 2.8),
        ("factor_mining", "rsi_mean_reversion", 0.7, 1.9),
        ("factor_mining", "rsi_mean_reversion", 1.6, 5.1),
        ("factor_mining", "rsi_mean_reversion", 1.2, 3.7),
    ]
    for source, strategy_key, sharpe, total_return in sample_rows:
        ledger.record(
            source=source,
            strategy_key=strategy_key,
            sharpe_ratio=sharpe,
            total_return_pct=total_return,
            params={"teaching_sample": True},
            total_trades=12,
            persist=False,
        )
    summary = ledger.summary()

    trial_counts = list(range(1, 51))
    alpha = 0.05
    false_positive = [1 - (1 - alpha) ** count for count in trial_counts]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.8), dpi=160)
    fig.patch.set_facecolor("#F7F9FC")
    sources = summary["sources"]
    axes[0].bar(list(sources.keys()), list(sources.values()), color=["#2563EB", "#F59E0B", "#0F766E"])
    axes[0].set_title("TrialLedger 记录试验来源", fontsize=14, loc="left")
    axes[0].set_ylabel("记录条数")
    axes[0].tick_params(axis="x", rotation=18)
    axes[0].grid(axis="y", color="#E5E7EB", linewidth=0.8)
    axes[0].spines[["top", "right"]].set_visible(False)

    axes[1].plot(trial_counts, [value * 100 for value in false_positive], color="#DC2626", linewidth=2.4)
    axes[1].set_title("多次尝试会放大偶然命中概率", fontsize=14, loc="left")
    axes[1].set_xlabel("尝试次数")
    axes[1].set_ylabel("至少一次假阳性概率（%）")
    axes[1].grid(color="#E5E7EB", linewidth=0.8)
    axes[1].spines[["top", "right"]].set_visible(False)
    axes[1].text(
        0.02,
        -0.22,
        f"示例 TrialLedger：num_trials={summary['num_trials']}，best_sharpe={summary['best_sharpe']}。",
        transform=axes[1].transAxes,
        fontsize=10,
        color="#64748B",
    )

    fig.tight_layout()
    fig.savefig(OUT / "chapter-20-trial-ledger-risk.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-20-trial-ledger-risk.png")


def main() -> None:
    setup_matplotlib()
    save_pollution_gate()
    save_trial_ledger_risk()


if __name__ == "__main__":
    main()
