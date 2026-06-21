"""Generate the Chapter 05 Python evidence curve chart."""

from __future__ import annotations

import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib import pyplot as plt

try:
    import seaborn as sns
except ModuleNotFoundError:  # pragma: no cover - depends on local teaching env
    sns = None

from backtest.rolling.service import execute_backtest


OUT = ROOT / "docs" / "v2" / "assets"

FONT_FAMILY = ["Microsoft YaHei", "SimHei", "Segoe UI", "DejaVu Sans", "Arial", "sans-serif"]
MONO_FONT_FAMILY = ["Consolas", "DejaVu Sans Mono", "monospace"]

TOKENS = {
    "surface": "#FCFCFD",
    "panel": "#FFFFFF",
    "ink": "#1F2430",
    "muted": "#6F768A",
    "grid": "#E6E8F0",
    "axis": "#D7DBE7",
}

BLUE = {"base": "#A3BEFA", "mid": "#5477C4", "dark": "#2E4780"}
ORANGE = {"base": "#F0986E", "mid": "#CC6F47", "dark": "#804126", "xlight": "#FFEDDE"}
OLIVE = {"base": "#A3D576", "mid": "#71B436", "dark": "#386411"}
NEUTRAL = {"light": "#E2E5EA", "mid": "#7A828F", "dark": "#464C55"}


def use_chart_theme() -> None:
    rc = {
        "figure.facecolor": TOKENS["surface"],
        "figure.edgecolor": "none",
        "savefig.facecolor": TOKENS["surface"],
        "savefig.edgecolor": "none",
        "axes.facecolor": TOKENS["panel"],
        "axes.edgecolor": TOKENS["axis"],
        "axes.labelcolor": TOKENS["ink"],
        "axes.grid": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "grid.color": TOKENS["grid"],
        "grid.linewidth": 0.8,
        "font.family": "sans-serif",
        "font.sans-serif": FONT_FAMILY,
        "font.monospace": MONO_FONT_FAMILY,
        "axes.unicode_minus": False,
    }
    if sns is not None:
        sns.set_theme(style="whitegrid", rc=rc)
    else:
        plt.rcParams.update(rc)


def add_chart_header(fig, ax, title: str, subtitle: str) -> None:
    title = textwrap.fill(title.strip(), width=74, break_long_words=False)
    subtitle = textwrap.fill(subtitle.strip(), width=112, break_long_words=False)
    ax.set_title("")
    fig.subplots_adjust(top=0.82)
    left = ax.get_position().x0
    fig.text(left, 0.965, title, ha="left", va="top", fontsize=17, fontweight="semibold", color=TOKENS["ink"])
    fig.text(left, 0.918, subtitle, ha="left", va="top", fontsize=10.5, color=TOKENS["muted"])
    if sns is not None:
        sns.despine(ax=ax)
    else:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)


def format_date_axis(ax) -> None:
    locator = mdates.AutoDateLocator(minticks=4, maxticks=7)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.tick_params(axis="x", labelrotation=0)


def ts_to_datetime(ts: int | float) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).replace(tzinfo=None)


def build_chart() -> Path:
    use_chart_theme()
    payload = execute_backtest(strategy_name="ma_crossover")
    equity_curve = payload["equity_curve"]
    trades = payload["trades"]

    dates = [ts_to_datetime(item["ts"]) for item in equity_curve]
    closes = [float(item["close"]) for item in equity_curve]
    equity = [float(item["equity"]) for item in equity_curve]

    fig, ax_price = plt.subplots(figsize=(14, 8), dpi=160)
    ax_equity = ax_price.twinx()
    ax_equity.grid(False)

    price_line = ax_price.plot(dates, closes, color=BLUE["base"], linewidth=1.6, label="BTC close")[0]
    equity_line = ax_equity.plot(dates, equity, color=OLIVE["mid"], linewidth=1.7, label="Backtest equity")[0]

    idx_to_date = {int(item["idx"]): ts_to_datetime(item["ts"]) for item in equity_curve}
    for trade in trades:
        entry_date = idx_to_date.get(int(trade["entryIdx"]))
        exit_date = idx_to_date.get(int(trade["exitIdx"]))
        if entry_date:
            ax_price.scatter(
                [entry_date],
                [float(trade["entryPrice"])],
                s=58,
                marker="^",
                facecolor=ORANGE["base"],
                edgecolor=ORANGE["dark"],
                linewidth=1.0,
                zorder=5,
            )
        if exit_date:
            ax_price.scatter(
                [exit_date],
                [float(trade["exitPrice"])],
                s=58,
                marker="v",
                facecolor=TOKENS["panel"],
                edgecolor=ORANGE["dark"],
                linewidth=1.2,
                zorder=5,
            )

    latest_date = dates[-1]
    latest_close = closes[-1]
    ax_price.axvline(latest_date, color=NEUTRAL["dark"], linestyle=":", linewidth=1.0)
    ax_price.annotate(
        "执行门：HOLD 信号进入研究记录\n真实订单入口不存在",
        xy=(latest_date, latest_close),
        xytext=(-240, 72),
        textcoords="offset points",
        ha="left",
        va="center",
        fontsize=10,
        color=TOKENS["ink"],
        bbox={"boxstyle": "round,pad=0.45", "fc": ORANGE["xlight"], "ec": ORANGE["dark"], "lw": 1.0},
        arrowprops={"arrowstyle": "->", "color": ORANGE["dark"], "lw": 1.0},
    )

    ax_price.set_ylabel("BTC close (USDT)", color=BLUE["dark"])
    ax_equity.set_ylabel("Backtest equity (start = 100)", color=OLIVE["dark"])
    ax_price.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.0f}"))
    ax_equity.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.1f}"))
    ax_price.tick_params(axis="y", colors=BLUE["dark"])
    ax_equity.tick_params(axis="y", colors=OLIVE["dark"])
    format_date_axis(ax_price)

    handles = [
        price_line,
        equity_line,
        plt.Line2D([], [], linestyle="", marker="^", markersize=8, markerfacecolor=ORANGE["base"], markeredgecolor=ORANGE["dark"], label="Entry"),
        plt.Line2D([], [], linestyle="", marker="v", markersize=8, markerfacecolor=TOKENS["panel"], markeredgecolor=ORANGE["dark"], label="Exit"),
    ]
    ax_price.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.02), frameon=False, ncol=4, borderaxespad=0)

    title = "BTC 价格与回测权益曲线：正收益仍停在研究层"
    subtitle = (
        "Source: execute_backtest(strategy_name='ma_crossover'), fixed offline BTC-USDT sample; "
        "2 trades, total return 6.92%, latest rule signal HOLD."
    )
    add_chart_header(fig, ax_price, title, subtitle)

    fig.text(
        ax_price.get_position().x0,
        0.045,
        "停止线：价格曲线和权益曲线只证明固定样本内的研究结果；实盘执行必须另走真实账户权限、风控审批和人工决定。",
        ha="left",
        va="bottom",
        fontsize=9.5,
        color=TOKENS["muted"],
    )

    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / "chapter-05-python-equity-curve.png"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def main() -> None:
    print(build_chart())


if __name__ == "__main__":
    main()
