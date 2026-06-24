"""Generate Chapter 18 publication figures."""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from backtest.trace import run_ma_crossover_trace, run_teaching_scenario  # noqa: E402


def save_event_backtest_combo() -> None:
    trace = run_ma_crossover_trace()
    trail = trace["trail"]
    steps = [item["step"] for item in trail]
    equity = [float(item["equity_after"] or 0) for item in trail]
    prices = [float(item["price"]) for item in trail]

    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 1, figsize=(10.8, 7), dpi=160, sharex=True)
    fig.patch.set_facecolor("#F7F9FC")
    for ax in axes:
        ax.set_facecolor("#FFFFFF")
        ax.grid(color="#E5E7EB", linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].plot(steps, prices, marker="o", color="#2563EB", linewidth=1.8)
    axes[0].set_title("成交事件价格轨迹", fontsize=16)
    axes[0].set_ylabel("成交价")
    axes[1].plot(steps, equity, marker="o", color="#F59E0B", linewidth=1.8)
    axes[1].set_title("成交后权益轨迹", fontsize=16)
    axes[1].set_xlabel("成交序号")
    axes[1].set_ylabel("权益")
    axes[1].text(
        0.01,
        -0.26,
        f"trades={len(trail)}，risk_rejections={len(trace['risk_rejections'])}；数据来自 run_ma_crossover_trace()。",
        transform=axes[1].transAxes,
        fontsize=10,
        color="#64748B",
    )
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "chapter-18-event-backtest-combo.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-18-event-backtest-combo.png")


def save_teaching_scenario() -> None:
    payload = run_teaching_scenario()
    labels = ["成交", "挂单", "风险拒绝"]
    values = [len(payload["trades"]), len(payload["pending_at_end"]), len(payload["risk_rejections"])]
    colors = ["#0F9B8E", "#F59E0B", "#DC2626"]

    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(9.5, 5.4), dpi=160)
    fig.patch.set_facecolor("#F7F9FC")
    ax.set_facecolor("#FFFFFF")
    bars = ax.bar(labels, values, color=colors, width=0.56)
    ax.set_ylim(0, max(values) + 1.2)
    ax.set_title("教学场景：成交、挂单与风险拒绝", fontsize=16, pad=14)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.05, str(value), ha="center", fontsize=11)
    ax.text(
        0.01,
        -0.16,
        "第 3 根 K 线成交，第 4 根 K 线留下限价挂单，第 5 根 K 线触发 MAX_POSITION_PCT 拒绝。",
        transform=ax.transAxes,
        fontsize=10,
        color="#64748B",
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-18-teaching-scenario.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-18-teaching-scenario.png")


def main() -> None:
    save_event_backtest_combo()
    save_teaching_scenario()


if __name__ == "__main__":
    main()
