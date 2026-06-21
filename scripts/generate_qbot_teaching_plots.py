#!/usr/bin/env python3
"""Generate HD teaching plots inspired by vendor/Qbot/docs/notebook/ (MIT).

Uses fixed offline sample data/prices.csv only — no live market APIs.
Outputs PNGs under docs/v2/assets/generated/ at 300 DPI for print-ready course chapters.
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "docs" / "v2" / "assets" / "generated"
PRICES_CSV = ROOT / "data" / "prices.csv"

from print_figure_config import PRINT_DPI as DPI
FOOTER = (
    "教学样本 WEB3-DEMO · data/prices.csv · 不进入实盘执行 · "
    "参考 vendor/Qbot/docs/notebook/01-strategy.ipynb 出图模式"
)


def _load_prices() -> tuple[list[str], list[float]]:
    dates: list[str] = []
    closes: list[float] = []
    with PRICES_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            dates.append(row["date"])
            closes.append(float(row["close"]))
    return dates, closes


def _prices_to_candles(closes: list[float], dates: list[str]) -> list[dict]:
    candles: list[dict] = []
    for idx, close in enumerate(closes):
        candles.append(
            {
                "date": dates[idx],
                "open": close,
                "close": close,
                "high": round(close * 1.002, 6),
                "low": round(close * 0.998, 6),
                "volume": 1.0,
                "tsSec": idx,
            }
        )
    return candles


def _rolling_sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0:
        return out
    window_sum = 0.0
    for i, value in enumerate(values):
        window_sum += value
        if i >= period:
            window_sum -= values[i - period]
        if i >= period - 1:
            out[i] = window_sum / period
    return out


def _rolling_extreme_shift(values: list[float], period: int, *, kind: str) -> list[float | None]:
    """pandas rolling(period).max/min().shift(1) — uses bars strictly before index i."""
    out: list[float | None] = [None] * len(values)
    for i in range(1, len(values)):
        start = max(0, i - period)
        window = values[start:i]
        if not window:
            continue
        out[i] = max(window) if kind == "max" else min(window)
    return out


def _log_returns(closes: list[float]) -> list[float]:
    out = [0.0]
    for i in range(1, len(closes)):
        out.append(math.log(closes[i] / closes[i - 1]))
    return out


def _cumsum(values: list[float]) -> list[float]:
    total = 0.0
    out: list[float] = []
    for value in values:
        total += value
        out.append(total)
    return out


def _date_ticks(dates: list[str], n: int) -> tuple[list[int], list[str]]:
    tick_step = max(1, n // 8)
    tick_idx = list(range(0, n, tick_step))
    if tick_idx[-1] != n - 1:
        tick_idx.append(n - 1)
    return tick_idx, [dates[i][5:] for i in tick_idx]


def _setup_matplotlib():
    import matplotlib as mpl
    import matplotlib.pyplot as plt

    for family in ("Microsoft YaHei", "SimHei", "DejaVu Sans"):
        try:
            mpl.rcParams["font.sans-serif"] = [family, "DejaVu Sans"]
            break
        except Exception:
            continue
    mpl.rcParams["axes.unicode_minus"] = False
    plt.rcParams.update(
        {
            "figure.facecolor": "#fafbfc",
            "axes.facecolor": "#ffffff",
            "axes.edgecolor": "#cbd5e1",
            "axes.labelcolor": "#1e293b",
            "axes.titleweight": "bold",
            "grid.color": "#e2e8f0",
            "grid.linestyle": "-",
            "grid.alpha": 0.8,
            "legend.framealpha": 0.92,
            "font.size": 11,
        }
    )
    return plt


def plot_chapter04_price_signal_equity() -> Path:
    """三面板：价格+均线 / 信号 / 累计收益（Qbot 01-strategy 模式，3/7 均线）."""
    plt = _setup_matplotlib()
    dates, closes = _load_prices()
    n = len(closes)
    x = list(range(n))

    fast_p, slow_p = 3, 7
    fast = _rolling_sma(closes, fast_p)
    slow = _rolling_sma(closes, slow_p)

    signal = [0.0] * n
    for i in range(n):
        if fast[i] is None or slow[i] is None:
            continue
        if fast[i] > slow[i]:
            signal[i] = 1.0
        elif fast[i] < slow[i]:
            signal[i] = -1.0

    log_returns = _log_returns(closes)

    position = [0.0] * n
    for i in range(1, n):
        position[i] = signal[i - 1]

    strat_log = [position[i] * log_returns[i] for i in range(n)]
    strat_cum = _cumsum(strat_log)
    bh_cum = _cumsum(log_returns)

    fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)
    fig.suptitle(
        "第 4 讲 · 价格、信号与策略累计收益（3/7 双均线 · 固定样本）",
        fontsize=16,
        color="#0f172a",
        y=0.98,
    )

    ax0 = axes[0]
    ax0.plot(x, closes, color="#2563eb", linewidth=2.2, label="收盘价")
    ax0.plot(
        x,
        [v if v is not None else float("nan") for v in fast],
        color="#f59e0b",
        linewidth=1.8,
        label=f"MA{fast_p}",
    )
    ax0.plot(
        x,
        [v if v is not None else float("nan") for v in slow],
        color="#7c3aed",
        linewidth=1.8,
        label=f"MA{slow_p}",
    )
    ax0.set_ylabel("价格")
    ax0.set_title("面板 A · 价格与指标（输入层）", loc="left", fontsize=12)
    ax0.grid(True)
    ax0.legend(loc="upper left")

    ax1 = axes[1]
    ax1.fill_between(x, 0, signal, where=[s > 0 for s in signal], color="#16a34a", alpha=0.35)
    ax1.fill_between(x, 0, signal, where=[s < 0 for s in signal], color="#dc2626", alpha=0.25)
    ax1.plot(x, signal, color="#334155", linewidth=1.5, drawstyle="steps-post")
    ax1.axhline(0, color="#94a3b8", linewidth=1)
    ax1.set_yticks([-1, 0, 1])
    ax1.set_yticklabels(["空向/平多", "观望", "多向"])
    ax1.set_ylabel("信号")
    ax1.set_title("面板 B · 规则信号（非订单；position = signal.shift(1)）", loc="left", fontsize=12)
    ax1.grid(True)

    ax2 = axes[2]
    ax2.plot(x, [v * 100 for v in bh_cum], color="#64748b", linewidth=2.0, label="买入持有（对数累计 %）")
    ax2.plot(
        x,
        [v * 100 for v in strat_cum],
        color="#0d9488",
        linewidth=2.2,
        label="策略路径（shift(1) × 收益）",
    )
    ax2.set_ylabel("累计对数收益（%）")
    ax2.set_xlabel(f"样本序号（data/prices.csv 共 {len(dates)} 日）")
    ax2.set_title("面板 C · 仓位作用后的路径（非事件引擎成交明细）", loc="left", fontsize=12)
    ax2.grid(True)
    ax2.legend(loc="upper left")

    tick_idx, tick_labels = _date_ticks(dates, n)
    ax2.set_xticks(tick_idx)
    ax2.set_xticklabels(tick_labels, rotation=0)

    fig.text(0.5, 0.01, FOOTER, ha="center", fontsize=9, color="#64748b")

    out = OUT / "chapter-04-price-signal-equity.png"
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter09_indicators_panel() -> Path:
    """第 9 讲：趋势 + 动量 + 波动指标同屏."""
    from backtest.rolling.indicators import compute_all_indicators

    plt = _setup_matplotlib()
    dates, closes = _load_prices()
    candles = _prices_to_candles(closes, dates)
    ind = compute_all_indicators(candles)
    n = len(closes)
    x = list(range(n))

    fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)
    fig.suptitle("第 9 讲 · 技术指标描述市场状态（固定样本）", fontsize=16, color="#0f172a", y=0.98)

    ax0 = axes[0]
    ax0.plot(x, closes, color="#1d4ed8", linewidth=2.0, label="收盘价")
    ax0.plot(
        x,
        [v if v is not None else float("nan") for v in ind.sma20],
        color="#ea580c",
        linewidth=1.6,
        label="SMA20",
    )
    ax0.fill_between(
        x,
        [ind.bb_lower[i] if ind.bb_lower[i] is not None else closes[i] for i in range(n)],
        [ind.bb_upper[i] if ind.bb_upper[i] is not None else closes[i] for i in range(n)],
        color="#93c5fd",
        alpha=0.25,
        label="布林带(20,2)",
    )
    ax0.set_ylabel("价格")
    ax0.set_title("趋势 + 偏离 · 均线与布林带", loc="left", fontsize=12)
    ax0.grid(True)
    ax0.legend(loc="upper left", ncol=2)

    ax1 = axes[1]
    rsi_vals = [v if v is not None else float("nan") for v in ind.rsi]
    ax1.plot(x, rsi_vals, color="#7c3aed", linewidth=2.0, label="RSI(14)")
    ax1.axhline(70, color="#dc2626", linestyle="--", linewidth=1, alpha=0.7)
    ax1.axhline(30, color="#16a34a", linestyle="--", linewidth=1, alpha=0.7)
    ax1.fill_between(x, 70, 100, color="#fecaca", alpha=0.15)
    ax1.fill_between(x, 0, 30, color="#bbf7d0", alpha=0.15)
    ax1.set_ylim(0, 100)
    ax1.set_ylabel("RSI")
    ax1.set_title("动量 · 超买/超卖区仅作状态描述，非预测", loc="left", fontsize=12)
    ax1.grid(True)

    ax2 = axes[2]
    atr_pct = [v if v is not None else float("nan") for v in ind.atr_pct]
    bb_w = [v if v is not None else float("nan") for v in ind.bb_width]
    ax2.plot(x, atr_pct, color="#0f766e", linewidth=2.0, label="ATR%")
    ax2.plot(x, bb_w, color="#c026d3", linewidth=1.6, alpha=0.85, label="布林带宽度")
    ax2.set_ylabel("波动指标")
    ax2.set_xlabel("样本序号")
    ax2.set_title("波动 · 止损距离与 regime 需要联合阅读", loc="left", fontsize=12)
    ax2.grid(True)
    ax2.legend(loc="upper left")

    fig.text(0.5, 0.01, FOOTER.replace("01-strategy", "indicators"), ha="center", fontsize=9, color="#64748b")
    out = OUT / "chapter-09-indicators-panel.png"
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter17_ma_crossover_trades() -> Path:
    """第 17 讲：双均线交叉与首次买卖区间（Qbot average/choose_stock 风格）."""
    plt = _setup_matplotlib()
    dates, closes = _load_prices()
    n = len(closes)
    x = list(range(n))
    fast_p, slow_p = 3, 7
    fast = _rolling_sma(closes, fast_p)
    slow = _rolling_sma(closes, slow_p)

    buy_idx: list[int] = []
    sell_idx: list[int] = []
    in_long = False
    for i in range(1, n):
        if fast[i] is None or slow[i] is None or fast[i - 1] is None or slow[i - 1] is None:
            continue
        crossed_up = fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]
        crossed_down = fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]
        if crossed_up and not in_long:
            buy_idx.append(i)
            in_long = True
        elif crossed_down and in_long:
            sell_idx.append(i)
            in_long = False

    fig, ax = plt.subplots(figsize=(14, 6.5))
    ax.plot(x, closes, color="#1e3a8a", linewidth=2.2, label="收盘价")
    ax.plot(
        x,
        [v if v is not None else float("nan") for v in fast],
        color="#f97316",
        linewidth=1.8,
        label=f"MA{fast_p}",
    )
    ax.plot(
        x,
        [v if v is not None else float("nan") for v in slow],
        color="#9333ea",
        linewidth=1.8,
        label=f"MA{slow_p}",
    )
    ax.scatter(buy_idx, [closes[i] for i in buy_idx], marker="^", s=140, color="#16a34a", zorder=5, label="金叉买入")
    ax.scatter(sell_idx, [closes[i] for i in sell_idx], marker="v", s=140, color="#dc2626", zorder=5, label="死叉卖出")

    for i in buy_idx:
        ax.annotate(dates[i][5:], (i, closes[i]), textcoords="offset points", xytext=(0, 10), fontsize=8, color="#166534")
    for i in sell_idx:
        ax.annotate(dates[i][5:], (i, closes[i]), textcoords="offset points", xytext=(0, -14), fontsize=8, color="#991b1b")

    ax.set_title("第 17 讲 · 3/7 双均线首次交叉信号（固定样本）", fontsize=15, loc="left")
    ax.set_ylabel("价格")
    ax.set_xlabel("日期（MM-DD）")
    ax.set_xticks(x[::4])
    ax.set_xticklabels([dates[i][5:] for i in range(0, n, 4)])
    ax.grid(True)
    ax.legend(loc="upper left", ncol=2)
    fig.text(0.5, 0.01, FOOTER.replace("01-strategy", "average"), ha="center", fontsize=9, color="#64748b")
    out = OUT / "chapter-17-ma-crossover-trades.png"
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter19_metrics_comparison() -> Path:
    """第 19 讲：多策略收益 vs 回撤对比（quantstats-rolling 思路）."""
    from backtest.rolling.service import compare_strategies

    plt = _setup_matplotlib()
    payload = compare_strategies(limit=35)
    rows = payload["strategies"]
    names = [r["strategy"] for r in rows]
    returns = [r["total_return_pct"] for r in rows]
    drawdowns = [abs(r["max_drawdown_pct"]) for r in rows]

    x_pos = list(range(len(names)))
    width = 0.38

    fig, ax1 = plt.subplots(figsize=(14, 7))
    bars1 = ax1.bar([i - width / 2 for i in x_pos], returns, width=width, color="#2563eb", label="累计收益 %")
    ax2 = ax1.twinx()
    bars2 = ax2.bar([i + width / 2 for i in x_pos], drawdowns, width=width, color="#f97316", alpha=0.85, label="最大回撤 %")

    ax1.set_ylabel("累计收益（%）", color="#1e40af")
    ax2.set_ylabel("最大回撤（%）", color="#c2410c")
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(names, rotation=15, ha="right")
    ax1.set_title("第 19 讲 · 同窗口多策略：收益与回撤必须联合阅读", fontsize=15, loc="left")
    ax1.grid(True, axis="y", alpha=0.4)
    ax1.axhline(0, color="#94a3b8", linewidth=1)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

    fig.text(
        0.5,
        0.01,
        "data/prices.csv · py scripts/backtest_lab.py compare · 不进入实盘执行",
        ha="center",
        fontsize=9,
        color="#64748b",
    )
    out = OUT / "chapter-19-metrics-comparison.png"
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter16_breakout_signal_equity() -> Path:
    """第 16 讲：通道突破规则三面板（Qbot 01-strategy.ipynb 第二段，窗口缩放至短样本）."""
    plt = _setup_matplotlib()
    dates, closes = _load_prices()
    n = len(closes)
    x = list(range(n))

    n1_p, n2_p = 10, 5
    n1_high = _rolling_extreme_shift(closes, n1_p, kind="max")
    n2_low = _rolling_extreme_shift(closes, n2_p, kind="min")

    signal = [0.0] * n
    for i in range(n):
        if n1_high[i] is None or n2_low[i] is None:
            continue
        if closes[i] > n1_high[i]:
            signal[i] = 1.0
        elif closes[i] < n2_low[i]:
            signal[i] = -1.0

    log_returns = _log_returns(closes)
    position = [0.0] * n
    for i in range(1, n):
        position[i] = signal[i - 1]
    strat_cum = _cumsum([position[i] * log_returns[i] for i in range(n)])
    bh_cum = _cumsum(log_returns)

    fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)
    fig.suptitle(
        "第 16 讲 · 通道突破规则：价格 / 信号 / 路径（固定样本）",
        fontsize=16,
        color="#0f172a",
        y=0.98,
    )

    ax0 = axes[0]
    ax0.plot(x, closes, color="#2563eb", linewidth=2.2, label="收盘价")
    ax0.plot(
        x,
        [v if v is not None else float("nan") for v in n1_high],
        color="#dc2626",
        linewidth=1.6,
        linestyle="--",
        label=f"前{n1_p}日最高 shift(1)",
    )
    ax0.plot(
        x,
        [v if v is not None else float("nan") for v in n2_low],
        color="#16a34a",
        linewidth=1.6,
        linestyle="--",
        label=f"前{n2_p}日最低 shift(1)",
    )
    ax0.set_ylabel("价格")
    ax0.set_title("面板 A · 入场=突破前高；出场=跌破前低（文字规则须写清 shift）", loc="left", fontsize=12)
    ax0.grid(True)
    ax0.legend(loc="upper left", fontsize=9)

    ax1 = axes[1]
    ax1.fill_between(x, 0, signal, where=[s > 0 for s in signal], color="#16a34a", alpha=0.35)
    ax1.fill_between(x, 0, signal, where=[s < 0 for s in signal], color="#dc2626", alpha=0.25)
    ax1.plot(x, signal, color="#334155", linewidth=1.5, drawstyle="steps-post")
    ax1.axhline(0, color="#94a3b8", linewidth=1)
    ax1.set_yticks([-1, 0, 1])
    ax1.set_yticklabels(["平多/空向", "观望", "突破多向"])
    ax1.set_ylabel("信号")
    ax1.set_title("面板 B · 规则输出（close>n1_high → +1；close<n2_low → -1）", loc="left", fontsize=12)
    ax1.grid(True)

    ax2 = axes[2]
    ax2.plot(x, [v * 100 for v in bh_cum], color="#64748b", linewidth=2.0, label="买入持有")
    ax2.plot(x, [v * 100 for v in strat_cum], color="#0d9488", linewidth=2.2, label="策略路径 shift(1)")
    ax2.set_ylabel("累计对数收益（%）")
    ax2.set_xlabel("样本序号（data/prices.csv）")
    ax2.set_title("面板 C · 向量化路径预览（非事件引擎成交明细）", loc="left", fontsize=12)
    ax2.grid(True)
    ax2.legend(loc="upper left")

    tick_idx, tick_labels = _date_ticks(dates, n)
    ax2.set_xticks(tick_idx)
    ax2.set_xticklabels(tick_labels, rotation=0)

    footer = FOOTER.replace("01-strategy", "01-strategy 通道突破段")
    fig.text(0.5, 0.01, footer, ha="center", fontsize=9, color="#64748b")
    out = OUT / "chapter-16-breakout-signal-equity.png"
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter19_equity_drawdown() -> Path:
    """第 19 讲：权益曲线 + 历史峰值 + 回撤阴影（Qbot pandas.ipynb + rolling 引擎）."""
    from backtest.rolling.service import execute_backtest

    plt = _setup_matplotlib()
    payload = execute_backtest(
        strategy_name="ma_crossover",
        limit=35,
        strategy_params={"short": 3, "long": 7},
    )
    curve = payload.get("equity_curve") or []
    if not curve:
        raise RuntimeError("equity_curve empty — cannot plot chapter-19-equity-drawdown")

    dates, closes = _load_prices()
    x = [pt["idx"] for pt in curve]
    equities = [pt["equity"] for pt in curve]
    drawdowns = [pt["drawdown"] for pt in curve]

    peak_line: list[float] = []
    peak = 0.0
    for eq in equities:
        peak = max(peak, eq)
        peak_line.append(peak)

    max_dd = max(drawdowns) if drawdowns else 0.0

    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    fig.suptitle(
        "第 19 讲 · 权益路径与最大回撤（3/7 双均线 · 事件引擎）",
        fontsize=16,
        color="#0f172a",
        y=0.98,
    )

    ax0 = axes[0]
    ax0.plot(x, equities, color="#2563eb", linewidth=2.2, label="权益（初始 100）")
    ax0.plot(x, peak_line, color="#94a3b8", linewidth=1.5, linestyle="--", label="历史峰值 expanding.max")
    ax0.fill_between(x, equities, peak_line, color="#fecaca", alpha=0.45, label="相对峰值回落区")
    ax0.axhline(100, color="#cbd5e1", linewidth=1)
    ax0.set_ylabel("权益")
    ax0.set_title("面板 A · 回撤 = 权益相对历史峰值的回落（非价格跌幅）", loc="left", fontsize=12)
    ax0.grid(True)
    ax0.legend(loc="upper left")

    ax1 = axes[1]
    ax1.fill_between(x, 0, drawdowns, color="#f97316", alpha=0.55)
    ax1.plot(x, drawdowns, color="#c2410c", linewidth=1.8, label="回撤 %")
    ax1.set_ylabel("回撤（%）")
    ax1.set_xlabel("K 线索引（与 data/prices.csv 对齐）")
    ax1.set_title(f"面板 B · 最大回撤 ≈ {max_dd:.2f}%（来自 rolling 引擎 equity_curve）", loc="left", fontsize=12)
    ax1.grid(True)
    ax1.legend(loc="upper left")

    tick_idx = [i for i in x if i % max(1, len(x) // 8) == 0 or i == x[-1]]
    ax1.set_xticks(tick_idx)
    if len(dates) >= max(x) + 1:
        ax1.set_xticklabels([dates[i][5:] if i < len(dates) else str(i) for i in tick_idx])

    fig.text(
        0.5,
        0.01,
        "参考 vendor/Qbot/docs/notebook/pandas.ipynb · execute_backtest(ma_crossover) · 不进入实盘执行",
        ha="center",
        fontsize=9,
        color="#64748b",
    )
    out = OUT / "chapter-19-equity-drawdown.png"
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter21_factor_ic_panel() -> Path:
    """第 21 讲：单因子 IC 与 GP/ML train-test 对比（精简 alphalens 思路）."""
    from factor_mining.evaluate import spearman
    from factor_mining.expressions import eval_series
    from factor_mining.features import build_feature_matrix
    from backtest.rolling.service import load_candles
    from factor_mining.serialize import expr_from_dict
    from factor_mining.service import run_factor_mining

    plt = _setup_matplotlib()
    mining = run_factor_mining(mode="both", limit=35, horizon=1, seed=42, gp_generations=12, gp_population=24)
    baseline = mining.get("baseline_univariate") or []
    baseline = sorted(baseline, key=lambda r: abs(r["ic_mean"]), reverse=True)[:6]

    _, _, candles, _ = load_candles(limit=35)
    features, labels, _ = build_feature_matrix(candles, horizon=1, target="return", risk_kind="abs_ret")

    rolling_ics: list[float] = []
    window = 8
    leader = mining.get("leader") or {}
    gp = mining.get("gp") or {}
    if leader.get("method") == "gp" and gp.get("factor_spec", {}).get("expr"):
        leader_expr = expr_from_dict(gp["factor_spec"]["expr"])
        series = eval_series(leader_expr, features)
        paired_x: list[float] = []
        paired_y: list[float] = []
        for i, val in enumerate(series):
            if val is None or labels[i] is None:
                continue
            paired_x.append(float(val))
            paired_y.append(float(labels[i]))
        for start in range(0, len(paired_x) - window + 1):
            rolling_ics.append(spearman(paired_x[start : start + window], paired_y[start : start + window]))

    fig, axes = plt.subplots(1, 2, figsize=(14, 6.5))
    fig.suptitle("第 21 讲 · 因子 IC 证据（固定样本 seed=42）", fontsize=16, color="#0f172a", y=0.98)

    ax0 = axes[0]
    names = [r["feature"] for r in baseline]
    ics = [r["ic_mean"] for r in baseline]
    colors = ["#2563eb" if v >= 0 else "#dc2626" for v in ics]
    y_pos = list(range(len(names)))
    ax0.barh(y_pos, ics, color=colors, alpha=0.85)
    ax0.set_yticks(y_pos)
    ax0.set_yticklabels(names)
    ax0.axvline(0, color="#94a3b8", linewidth=1)
    ax0.set_xlabel("Spearman IC（全样本单因子）")
    ax0.set_title("面板 A · 基线特征 IC（Top 6 |IC|）", loc="left", fontsize=12)
    ax0.grid(True, axis="x", alpha=0.4)
    ax0.invert_yaxis()

    ax1 = axes[1]
    leaders: list[tuple[str, float, float]] = []
    if gp:
        train_ic = (gp.get("train") or {}).get("ic_mean", 0.0)
        test_ic = (gp.get("test") or {}).get("ic_mean", 0.0)
        leaders.append(("GP", train_ic, test_ic))
    ml = mining.get("ml") or {}
    if ml:
        train_ic = (ml.get("train") or {}).get("ic_mean", 0.0)
        test_ic = (ml.get("test") or {}).get("ic_mean", 0.0)
        leaders.append(("ML", train_ic, test_ic))

    if leaders:
        labels_x = [row[0] for row in leaders]
        train_vals = [row[1] for row in leaders]
        test_vals = [row[2] for row in leaders]
        xp = list(range(len(labels_x)))
        w = 0.35
        ax1.bar([i - w / 2 for i in xp], train_vals, width=w, color="#6366f1", label="训练 IC")
        ax1.bar([i + w / 2 for i in xp], test_vals, width=w, color="#f97316", label="测试 IC")
        ax1.set_xticks(xp)
        ax1.set_xticklabels(labels_x)
        gap = leader.get("overfit_gap")
        if gap is None and gp:
            gap = gp.get("overfit_gap")
        gap_txt = f"leader overfit_gap={gap:.3f}" if gap is not None else ""
        ax1.set_title(f"面板 B · 挖掘 leader train/test IC · {gap_txt}", loc="left", fontsize=11)
    else:
        ax1.text(0.5, 0.5, "无 leader", ha="center", va="center", transform=ax1.transAxes)

    ax1.axhline(0, color="#94a3b8", linewidth=1)
    ax1.set_ylabel("IC")
    ax1.grid(True, axis="y", alpha=0.4)
    ax1.legend(loc="upper right")

    if rolling_ics:
        inset = ax1.inset_axes([0.55, 0.08, 0.42, 0.38])
        inset.plot(range(len(rolling_ics)), rolling_ics, color="#0d9488", linewidth=1.6)
        inset.axhline(0, color="#94a3b8", linewidth=0.8)
        inset.set_title(f"GP rolling IC (w={window})", fontsize=8)
        inset.grid(True, alpha=0.3)

    fig.text(
        0.5,
        0.01,
        "参考 vendor/Qbot/docs/notebook/02-alphalens.ipynb · src/factor_mining/ · 不进入实盘执行",
        ha="center",
        fontsize=9,
        color="#64748b",
    )
    out = OUT / "chapter-21-factor-ic-panel.png"
    fig.tight_layout(rect=(0, 0.04, 1, 0.96))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter21_rolling_sharpe() -> Path:
    """第 21 讲：滚动 Sharpe（quantstats-rolling 思路，基于事件引擎权益序列）."""
    from backtest.rolling.service import execute_backtest

    plt = _setup_matplotlib()
    payload = execute_backtest(strategy_name="ma_crossover", limit=35, strategy_params={"short": 3, "long": 7})
    curve = payload.get("equity_curve") or []
    equities = [pt["equity"] for pt in curve]
    rets: list[float] = [0.0]
    for i in range(1, len(equities)):
        prev = equities[i - 1]
        rets.append((equities[i] - prev) / prev * 100 if prev > 0 else 0.0)

    window = 8
    rolling_sharpe: list[float | None] = [None] * len(rets)
    for i in range(window - 1, len(rets)):
        chunk = rets[i - window + 1 : i + 1]
        mean = sum(chunk) / len(chunk)
        var = sum((v - mean) ** 2 for v in chunk) / max(1, len(chunk) - 1)
        std = math.sqrt(var)
        rolling_sharpe[i] = (mean / std * math.sqrt(252)) if std > 1e-9 else 0.0

    x = list(range(len(rets)))
    dates, _ = _load_prices()

    fig, ax = plt.subplots(figsize=(14, 6))
    sharpe_vals = [v if v is not None else float("nan") for v in rolling_sharpe]
    ax.plot(x, sharpe_vals, color="#7c3aed", linewidth=2.2, label=f"滚动 Sharpe（窗口={window} 根 K）")
    ax.axhline(0, color="#94a3b8", linewidth=1)
    ax.fill_between(
        x,
        0,
        sharpe_vals,
        where=[v is not None and v >= 0 for v in rolling_sharpe],
        color="#bbf7d0",
        alpha=0.35,
    )
    ax.fill_between(
        x,
        0,
        sharpe_vals,
        where=[v is not None and v < 0 for v in rolling_sharpe],
        color="#fecaca",
        alpha=0.35,
    )
    ax.set_title("第 21 讲 · 滚动 Sharpe（由权益序列推导，非 quantstats 依赖）", fontsize=15, loc="left")
    ax.set_ylabel("年化 Sharpe（近似）")
    ax.set_xlabel("K 线索引")
    ax.grid(True)
    ax.legend(loc="upper left")

    tick_idx, tick_labels = _date_ticks(dates, min(len(dates), len(x)))
    ax.set_xticks(tick_idx)
    ax.set_xticklabels(tick_labels)

    fig.text(
        0.5,
        0.01,
        "参考 vendor/Qbot/docs/notebook/quantstats-rolling.ipynb · 不进入实盘执行",
        ha="center",
        fontsize=9,
        color="#64748b",
    )
    out = OUT / "chapter-21-rolling-sharpe.png"
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def _scatter_trade_markers(ax, trades: list[dict], *, annotate: bool = False, dates: list[str] | None = None) -> None:
    if not trades:
        return
    entries_x = [t["entryIdx"] for t in trades]
    entries_y = [t["entryPrice"] for t in trades]
    exits_x = [t["exitIdx"] for t in trades]
    exits_y = [t["exitPrice"] for t in trades]
    ax.scatter(entries_x, entries_y, marker="^", s=140, color="#16a34a", zorder=5, label="入场成交")
    ax.scatter(exits_x, exits_y, marker="v", s=140, color="#dc2626", zorder=5, label="出场成交")
    for trade in trades:
        ax.plot(
            [trade["entryIdx"], trade["exitIdx"]],
            [trade["entryPrice"], trade["exitPrice"]],
            color="#94a3b8",
            linewidth=1.0,
            alpha=0.45,
            linestyle=":",
        )
        if annotate and dates:
            ei = trade["entryIdx"]
            xi = trade["exitIdx"]
            if ei < len(dates):
                ax.annotate(
                    dates[ei],
                    (ei, trade["entryPrice"]),
                    textcoords="offset points",
                    xytext=(0, 8),
                    fontsize=7,
                    color="#166534",
                )
            if xi < len(dates):
                reason = trade.get("exitReason") or "出场"
                ax.annotate(
                    reason[:6],
                    (xi, trade["exitPrice"]),
                    textcoords="offset points",
                    xytext=(0, -12),
                    fontsize=7,
                    color="#991b1b",
                )


def plot_chapter18_event_backtest_combo() -> Path:
    """第 18 讲：日 K + 事件引擎成交标记 + 权益曲线（BacktestComboChart / average.ipynb 思路）."""
    from backtest.rolling.service import execute_backtest, load_candles

    plt = _setup_matplotlib()
    payload = execute_backtest(
        strategy_name="ma_crossover",
        limit=35,
        strategy_params={"short": 3, "long": 7},
        stop_loss_pct=3.0,
        take_profit_pct=5.0,
    )
    _, _, candles, _ = load_candles(limit=35)
    closes = [c["close"] for c in candles]
    dates = [c["date"] for c in candles]
    date_labels = [d[5:] for d in dates]
    trades = payload.get("trades") or []
    curve = payload.get("equity_curve") or []

    x = list(range(len(closes)))
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    fig.suptitle(
        "第 18 讲 · 事件驱动回测：成交标记与权益路径（3/7 双均线）",
        fontsize=16,
        color="#0f172a",
        y=0.98,
    )

    ax0 = axes[0]
    ax0.plot(x, closes, color="#1e3a8a", linewidth=2.2, label="收盘价")
    _scatter_trade_markers(ax0, trades, annotate=True, dates=date_labels)
    ax0.set_ylabel("价格")
    ax0.set_title(
        f"面板 A · 来自 trades[] 的 ▲入场 / ▼出场（共 {len(trades)} 笔 · 含止损/止盈/信号）",
        loc="left",
        fontsize=12,
    )
    ax0.grid(True)
    ax0.legend(loc="upper left", fontsize=9)

    ax1 = axes[1]
    eq_x = [pt["idx"] for pt in curve]
    eq_y = [pt["equity"] for pt in curve]
    ax1.plot(eq_x, eq_y, color="#2563eb", linewidth=2.2, label="权益（初始 100）")
    ax1.axhline(100, color="#94a3b8", linewidth=1)
    ax1.fill_between(eq_x, 100, eq_y, where=[y >= 100 for y in eq_y], color="#bbf7d0", alpha=0.35)
    ax1.fill_between(eq_x, 100, eq_y, where=[y < 100 for y in eq_y], color="#fecaca", alpha=0.35)
    ax1.set_ylabel("权益")
    ax1.set_xlabel("K 线索引（与 data/prices.csv 日期对齐）")
    ax1.set_title("面板 B · equity_curve[] 逐 bar 盯市（非向量化 cumsum）", loc="left", fontsize=12)
    ax1.grid(True)
    ax1.legend(loc="upper left")

    tick_idx, tick_labels = _date_ticks(dates, len(dates))
    ax1.set_xticks(tick_idx)
    ax1.set_xticklabels(tick_labels)

    fig.text(
        0.5,
        0.01,
        "参考 vendor/Qbot/docs/notebook/average.ipynb cerebro.plot · execute_backtest · 不进入实盘执行",
        ha="center",
        fontsize=9,
        color="#64748b",
    )
    out = OUT / "chapter-18-event-backtest-combo.png"
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter18_macd_trailing_backtest() -> Path:
    """第 18 讲：MACD 策略 + 柱状图 + 权益（bitcoin_bt_example 叙事，固定样本）."""
    from backtest.rolling.indicators import compute_all_indicators
    from backtest.rolling.service import execute_backtest, load_candles

    plt = _setup_matplotlib()
    payload = execute_backtest(
        strategy_name="macd",
        limit=35,
        trailing_stop_pct=2.0,
        stop_loss_pct=3.0,
    )
    _, _, candles, _ = load_candles(limit=35)
    ind = compute_all_indicators(candles)
    closes = [c["close"] for c in candles]
    dates = [c["date"] for c in candles]
    trades = payload.get("trades") or []
    curve = payload.get("equity_curve") or []
    n = len(closes)
    x = list(range(n))

    fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True, gridspec_kw={"height_ratios": [2, 1, 1.2]})
    fig.suptitle(
        "第 18 讲 · MACD 事件回测 + 追踪止损（固定样本 · 参考 bitcoin_bt_example）",
        fontsize=16,
        color="#0f172a",
        y=0.98,
    )

    ax0 = axes[0]
    ax0.plot(x, closes, color="#0f172a", linewidth=2.0, label="收盘价")
    _scatter_trade_markers(ax0, trades)
    ax0.set_ylabel("价格")
    ax0.set_title("面板 A · MACD 策略成交（rolling 引擎 · trailing_stop=2%）", loc="left", fontsize=12)
    ax0.grid(True)
    ax0.legend(loc="upper left", fontsize=9)

    ax1 = axes[1]
    hist = [v if v is not None else 0.0 for v in ind.macd_histogram]
    colors = ["#16a34a" if v >= 0 else "#dc2626" for v in hist]
    ax1.bar(x, hist, color=colors, alpha=0.75, width=0.85)
    ax1.axhline(0, color="#94a3b8", linewidth=1)
    ax1.set_ylabel("MACD 柱")
    ax1.set_title("面板 B · 指标状态（描述层，不等于成交命令）", loc="left", fontsize=12)
    ax1.grid(True, axis="y", alpha=0.4)

    ax2 = axes[2]
    eq_x = [pt["idx"] for pt in curve]
    eq_y = [pt["equity"] for pt in curve]
    ax2.plot(eq_x, eq_y, color="#7c3aed", linewidth=2.2, label="权益")
    ax2.axhline(100, color="#94a3b8", linewidth=1)
    ax2.set_ylabel("权益")
    ax2.set_xlabel("K 线索引")
    ax2.set_title(
        f"面板 C · 权益路径（{payload.get('total_trades', 0)} 笔 · 回撤 {payload.get('max_drawdown_pct', 0):.1f}%）",
        loc="left",
        fontsize=12,
    )
    ax2.grid(True)
    ax2.legend(loc="upper left")

    tick_idx, tick_labels = _date_ticks(dates, n)
    ax2.set_xticks(tick_idx)
    ax2.set_xticklabels(tick_labels)

    fig.text(
        0.5,
        0.01,
        "参考 vendor/Qbot/qbot/engine/backtest/bitcoin_bt_example.py · 无 Amberdata 在线数据 · 不进入实盘执行",
        ha="center",
        fontsize=9,
        color="#64748b",
    )
    out = OUT / "chapter-18-macd-trailing-backtest.png"
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter21_compare_windows() -> Path:
    """第 21 讲：多窗口收益/回撤并排（compare_windows CLI 可视化）."""
    from backtest.rolling.service import compare_windows

    plt = _setup_matplotlib()
    payload = compare_windows(strategy_name="ma_crossover", num_windows=3, limit=35)
    windows = payload.get("windows") or []
    if not windows:
        raise RuntimeError("compare_windows returned no windows")

    labels = [f"窗口 {w['window']}\n({w['candles']} K)" for w in windows]
    returns = [w["total_return_pct"] for w in windows]
    drawdowns = [abs(w["max_drawdown_pct"]) for w in windows]
    stable = payload.get("stable", False)

    x_pos = list(range(len(labels)))
    width = 0.36

    fig, ax1 = plt.subplots(figsize=(14, 7))
    ax1.bar(
        [i - width / 2 for i in x_pos],
        returns,
        width=width,
        color="#2563eb",
        label="累计收益 %",
    )
    ax2 = ax1.twinx()
    ax2.bar(
        [i + width / 2 for i in x_pos],
        drawdowns,
        width=width,
        color="#f97316",
        alpha=0.88,
        label="最大回撤 %",
    )

    ax1.set_ylabel("累计收益（%）", color="#1e40af")
    ax2.set_ylabel("最大回撤（%）", color="#c2410c")
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(labels)
    stability = "stable=True" if stable else "stable=False（需人工解释）"
    ax1.set_title(
        f"第 21 讲 · 同策略三分窗：收益与回撤必须联合阅读 · {stability}",
        fontsize=15,
        loc="left",
    )
    ax1.grid(True, axis="y", alpha=0.4)
    ax1.axhline(0, color="#94a3b8", linewidth=1)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

    fig.text(
        0.5,
        0.01,
        "py scripts/backtest_lab.py windows ·  chronologic split · 不进入实盘执行",
        ha="center",
        fontsize=9,
        color="#64748b",
    )
    out = OUT / "chapter-21-compare-windows.png"
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter18_cost_presets() -> Path:
    """第 18 讲：同一策略在三档成本预设下的收益对比."""
    from backtest.cost_presets import PRESETS
    from backtest.rolling.service import execute_backtest

    plt = _setup_matplotlib()
    presets = ("teaching", "realistic", "perp")
    labels: list[str] = []
    returns: list[float] = []
    sharpes: list[float] = []

    for preset in presets:
        payload = execute_backtest(
            strategy_name="ma_crossover",
            limit=35,
            strategy_params={"short": 3, "long": 7},
            cost_preset=preset,
        )
        labels.append(PRESETS[preset]["label"])
        returns.append(float(payload.get("total_return_pct") or 0.0))
        sharpes.append(float(payload.get("sharpe_ratio") or 0.0))

    x_pos = list(range(len(labels)))
    width = 0.36
    fig, ax1 = plt.subplots(figsize=(14, 7))
    ax1.bar(
        [i - width / 2 for i in x_pos],
        returns,
        width=width,
        color="#2563eb",
        label="累计收益 %",
    )
    ax2 = ax1.twinx()
    ax2.bar(
        [i + width / 2 for i in x_pos],
        sharpes,
        width=width,
        color="#7c3aed",
        alpha=0.88,
        label="Sharpe",
    )
    ax1.set_ylabel("累计收益（%）", color="#1e40af")
    ax2.set_ylabel("Sharpe", color="#6d28d9")
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(labels, rotation=12, ha="right")
    ax1.set_title("第 18 讲 · 成本预设：同一策略在不同成交假设下的落差", fontsize=15, loc="left")
    ax1.grid(True, axis="y", alpha=0.4)
    ax1.axhline(0, color="#94a3b8", linewidth=1)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
    fig.text(
        0.5,
        0.01,
        "ma_crossover · execute_backtest(cost_preset=…) · data/prices.csv · 不进入实盘执行",
        ha="center",
        fontsize=9,
        color="#64748b",
    )
    out = OUT / "chapter-18-cost-presets.png"
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter19_dsr_vs_trials() -> Path:
    """第 19 讲：试验次数上升时 DSR 如何变保守."""
    from backtest.audit.dsr import deflated_sharpe_ratio

    plt = _setup_matplotlib()
    observed_sr = 1.2
    sample_length = 120
    trial_counts = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233]
    dsrs = [
        float(deflated_sharpe_ratio(observed_sr, sample_length, n)["dsr"])
        for n in trial_counts
    ]
    psrs = [
        float(deflated_sharpe_ratio(observed_sr, sample_length, n)["psr"])
        for n in trial_counts
    ]

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(trial_counts, dsrs, color="#dc2626", linewidth=2.4, marker="o", label="DSR")
    ax.plot(trial_counts, psrs, color="#2563eb", linewidth=2.0, linestyle="--", marker="s", label="PSR")
    ax.axhline(0.95, color="#16a34a", linewidth=1.2, linestyle=":", label="显著性阈值 0.95")
    ax.set_xscale("log")
    ax.set_xlabel("试验次数 num_trials（对数刻度）")
    ax.set_ylabel("概率值")
    ax.set_title(
        f"第 19 讲 · 固定样本内 Sharpe={observed_sr} 时，试验越多 DSR 越保守",
        fontsize=15,
        loc="left",
    )
    ax.grid(True, alpha=0.4)
    ax.legend(loc="upper right")
    fig.text(
        0.5,
        0.01,
        "audit/dsr.py · deflated_sharpe_ratio · 不进入实盘执行",
        ha="center",
        fontsize=9,
        color="#64748b",
    )
    out = OUT / "chapter-19-dsr-vs-trials.png"
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter21_cpcv_sharpe_distribution() -> Path:
    """第 21 讲：CPCV 多条 OOS 路径的 Sharpe 分布."""
    from backtest.rolling.service import run_cpcv_service

    plt = _setup_matplotlib()
    payload = run_cpcv_service(strategy_name="ma_crossover", limit=35)
    cpcv = payload.get("cpcv") or {}
    path_rows = cpcv.get("paths") or []
    paths = [float(row["sharpe"]) for row in path_rows]
    if not paths:
        raise RuntimeError("CPCV returned no path_sharpes")

    p5 = float(cpcv.get("sharpe_p5") or 0.0)
    p50 = float(cpcv.get("sharpe_p50") or 0.0)
    p95 = float(cpcv.get("sharpe_p95") or 0.0)
    profitable = float(cpcv.get("profitable_paths_pct") or 0.0)

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.hist(paths, bins=min(12, max(5, len(paths) // 2)), color="#60a5fa", edgecolor="#1e40af", alpha=0.85)
    for value, color, label in (
        (p5, "#f97316", "p5"),
        (p50, "#dc2626", "p50"),
        (p95, "#16a34a", "p95"),
    ):
        ax.axvline(value, color=color, linewidth=2, linestyle="--", label=f"Sharpe {label} = {value:.2f}")
    ax.set_xlabel("OOS Sharpe")
    ax.set_ylabel("路径数量")
    ax.set_title(
        f"第 21 讲 · CPCV Sharpe 分布 · 盈利路径 {profitable:.0f}%",
        fontsize=15,
        loc="left",
    )
    ax.grid(True, axis="y", alpha=0.35)
    ax.legend(loc="upper right")
    fig.text(
        0.5,
        0.01,
        "run_cpcv_service · py scripts/backtest_lab.py cpcv · 不进入实盘执行",
        ha="center",
        fontsize=9,
        color="#64748b",
    )
    out = OUT / "chapter-21-cpcv-sharpe-dist.png"
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter21_parameter_sensitivity() -> Path:
    """第 21 讲：参数 ±20% 扰动后的收益漂移."""
    from backtest.rolling.service import run_robustness_audit

    plt = _setup_matplotlib()
    payload = run_robustness_audit(strategy_name="ma_crossover", limit=35)
    sensitivity = payload.get("parameter_sensitivity") or {}
    rows = sensitivity.get("perturbations") or []
    if not rows:
        raise RuntimeError("robustness audit returned no perturbations")

    labels = [f"{row['param']} {row['direction']}" for row in rows]
    drifts = [float(row["return_drift_pct"]) for row in rows]
    colors = ["#16a34a" if row["stable"] else "#dc2626" for row in rows]
    stability = float(sensitivity.get("stability_score") or 0.0)
    pbo = float((payload.get("pbo") or {}).get("pbo") or 0.0)

    y_pos = list(range(len(labels)))
    fig, ax = plt.subplots(figsize=(14, max(5, len(labels) * 0.55 + 2)))
    ax.barh(y_pos, drifts, color=colors, alpha=0.9)
    ax.axvline(30, color="#94a3b8", linewidth=1.5, linestyle="--", label="漂移阈值 30%")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.set_xlabel("收益漂移（%）")
    ax.set_title(
        f"第 21 讲 · 参数敏感性 · 稳定性 {stability * 100:.0f}% · PBO {pbo * 100:.0f}%",
        fontsize=15,
        loc="left",
    )
    ax.grid(True, axis="x", alpha=0.35)
    ax.legend(loc="lower right")
    fig.text(
        0.5,
        0.01,
        "run_robustness_audit · 绿色=稳定 · 红色=超阈值 · 不进入实盘执行",
        ha="center",
        fontsize=9,
        color="#64748b",
    )
    out = OUT / "chapter-21-parameter-sensitivity.png"
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_chapter21_walkforward_sharpe() -> Path:
    """第 21 讲：Walk-forward 样本内/外 Sharpe 与 DSR."""
    from backtest.rolling.service import run_walk_forward

    plt = _setup_matplotlib()
    payload = run_walk_forward(strategy_name="ma_crossover", limit=35, num_windows=3)
    is_sharpe = float(payload.get("in_sample_sharpe") or 0.0)
    oos_sharpe = float(payload.get("out_of_sample_sharpe") or 0.0)
    dsr = float(payload.get("dsr") or 0.0)
    num_trials = int(payload.get("num_trials") or 0)
    warning = bool(payload.get("overfit_warning"))

    labels = ["样本内 Sharpe", "样本外 Sharpe"]
    values = [is_sharpe, oos_sharpe]
    colors = ["#2563eb", "#f97316" if warning else "#16a34a"]

    fig, ax = plt.subplots(figsize=(12, 6))
    bars = ax.bar(labels, values, color=colors, width=0.55)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.05,
            f"{value:.2f}",
            ha="center",
            va="bottom",
            fontsize=12,
            color="#0f172a",
        )
    ax.axhline(0, color="#94a3b8", linewidth=1)
    ax.set_ylabel("Sharpe")
    status = "过拟合警告" if warning else "未触发警告"
    ax.set_title(
        f"第 21 讲 · Walk-forward · DSR={dsr:.2f} · 试验 {num_trials} 次 · {status}",
        fontsize=15,
        loc="left",
    )
    ax.grid(True, axis="y", alpha=0.35)
    fig.text(
        0.5,
        0.01,
        "run_walk_forward · py scripts/backtest_lab.py walk-forward · 不进入实盘执行",
        ha="center",
        fontsize=9,
        color="#64748b",
    )
    out = OUT / "chapter-21-walkforward-sharpe.png"
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def _run_pil_chapter18_flow() -> Path:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from generate_chapter18_backtrader_flow import backtrader_vs_local

    return backtrader_vs_local()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    outputs = [
        plot_chapter04_price_signal_equity(),
        plot_chapter09_indicators_panel(),
        plot_chapter16_breakout_signal_equity(),
        plot_chapter17_ma_crossover_trades(),
        plot_chapter18_event_backtest_combo(),
        plot_chapter18_macd_trailing_backtest(),
        plot_chapter18_cost_presets(),
        _run_pil_chapter18_flow(),
        plot_chapter19_metrics_comparison(),
        plot_chapter19_equity_drawdown(),
        plot_chapter19_dsr_vs_trials(),
        plot_chapter21_factor_ic_panel(),
        plot_chapter21_rolling_sharpe(),
        plot_chapter21_compare_windows(),
        plot_chapter21_cpcv_sharpe_distribution(),
        plot_chapter21_parameter_sensitivity(),
        plot_chapter21_walkforward_sharpe(),
    ]
    for path in outputs:
        print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
