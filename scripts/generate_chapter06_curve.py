"""Generate the Chapter 06 Python source-timeline chart."""

from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib import pyplot as plt

try:
    import seaborn as sns
except ModuleNotFoundError:  # pragma: no cover - depends on local teaching env
    sns = None


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "dashboard"
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

BLUE = {"base": "#7EA4F8", "mid": "#5477C4", "dark": "#2E4780"}
ORANGE = {"base": "#F6B26B", "mid": "#CC6F47", "dark": "#804126", "xlight": "#FFF3E8"}
RED = {"mid": "#C94F4F", "dark": "#7F2E2E", "xlight": "#FDECEC"}
TEAL = {"mid": "#2D9C9C", "dark": "#126C6C", "xlight": "#E6F6F5"}
NEUTRAL = {"light": "#E2E5EA", "mid": "#7A828F", "dark": "#464C55"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def parse_ts(value: str | int | float) -> datetime:
    return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(tzinfo=None)


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
    title = textwrap.fill(title.strip(), width=70, break_long_words=False)
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
    locator = mdates.AutoDateLocator(minticks=5, maxticks=8)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.tick_params(axis="x", labelrotation=0)


def build_chart() -> Path:
    use_chart_theme()
    candles_payload = load_json(DATA / "market_candles.json")
    onchain_payload = load_json(DATA / "onchain.json")
    manifest = load_json(DATA / "manifest.json")

    candles = candles_payload["candles"]
    dates = [parse_date(row["date"]) for row in candles]
    closes = [float(row["close"]) for row in candles]
    volumes = [float(row["volume"]) for row in candles]

    fear_greed = onchain_payload["marketSentiment"]["fearGreed"]
    sentiment_date = parse_ts(fear_greed["timestamp"])
    sentiment_value = int(fear_greed["value"])
    sentiment_label = str(fear_greed["label"])

    market_entry = manifest["datasets"]["market_candles"]
    onchain_entry = manifest["datasets"]["onchain"]
    market_saved_at = parse_iso(market_entry["updated_at"])
    onchain_saved_at = parse_iso(onchain_entry["updated_at"])

    fig, (ax_price, ax_volume) = plt.subplots(
        2,
        1,
        figsize=(14, 8),
        dpi=160,
        sharex=True,
        gridspec_kw={"height_ratios": [3.1, 1.05], "hspace": 0.08},
    )

    price_line = ax_price.plot(dates, closes, color=BLUE["mid"], linewidth=2.0, label="BTC 收盘价")[0]
    ax_price.scatter(dates, closes, s=18, color=BLUE["base"], edgecolor=BLUE["dark"], linewidth=0.6, zorder=3)
    ax_volume.bar(dates, volumes, width=0.72, color=ORANGE["base"], edgecolor=ORANGE["mid"], linewidth=0.4, alpha=0.78, label="成交量")

    ax_price.axvline(sentiment_date, color=RED["mid"], linestyle="--", linewidth=1.3)
    ax_volume.axvline(sentiment_date, color=RED["mid"], linestyle="--", linewidth=1.1)

    sentiment_close = closes[dates.index(sentiment_date)] if sentiment_date in dates else closes[-1]
    ax_price.annotate(
        f"链上情绪观察日：{sentiment_date:%Y-%m-%d}\nFear & Greed = {sentiment_value} ({sentiment_label})",
        xy=(sentiment_date, sentiment_close),
        xytext=(-255, 58),
        textcoords="offset points",
        ha="left",
        va="center",
        fontsize=9.7,
        color=TOKENS["ink"],
        bbox={"boxstyle": "round,pad=0.45", "fc": RED["xlight"], "ec": RED["dark"], "lw": 1.0},
        arrowprops={"arrowstyle": "->", "color": RED["dark"], "lw": 1.0},
    )

    save_note = (
        f"manifest 保存时间\nmarket_candles: {market_saved_at:%Y-%m-%d %H:%M} UTC\n"
        f"onchain: {onchain_saved_at:%Y-%m-%d %H:%M} UTC"
    )
    ax_price.text(
        0.985,
        0.965,
        save_note,
        transform=ax_price.transAxes,
        ha="right",
        va="top",
        fontsize=9.3,
        color=TOKENS["ink"],
        bbox={"boxstyle": "round,pad=0.45", "fc": TEAL["xlight"], "ec": TEAL["dark"], "lw": 1.0},
    )

    ax_price.set_ylabel("BTC 收盘价 (USDT)", color=BLUE["dark"])
    ax_volume.set_ylabel("成交量", color=ORANGE["dark"])
    ax_price.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.0f}"))
    ax_volume.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.0f}"))
    ax_price.tick_params(axis="y", colors=BLUE["dark"])
    ax_volume.tick_params(axis="y", colors=ORANGE["dark"])
    format_date_axis(ax_volume)

    handles = [
        price_line,
        plt.Line2D([], [], color=ORANGE["base"], linewidth=6, label="成交量"),
        plt.Line2D([], [], color=RED["mid"], linestyle="--", linewidth=1.5, label="链上情绪观察日"),
    ]
    ax_price.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.02), frameon=False, ncol=3, borderaxespad=0)

    title = "BTC 行情曲线与链上情绪来源卡：观察时间和保存时间必须分开"
    subtitle = (
        "来源文件：data/dashboard/market_candles.json、data/dashboard/onchain.json、data/dashboard/manifest.json。"
        "本图是可复现教学样本，不是实盘执行指令。"
    )
    add_chart_header(fig, ax_price, title, subtitle)

    fig.text(
        ax_price.get_position().x0,
        0.045,
        "停止线：价格曲线只能说明样本窗口内的收盘价和成交量；链上情绪只能作为独立观察项。保存时间用于追溯数据版本，不能被写成同一时点市场因果结论。",
        ha="left",
        va="bottom",
        fontsize=9.5,
        color=TOKENS["muted"],
    )

    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / "chapter-06-python-source-timeline.png"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def main() -> None:
    print(build_chart())


if __name__ == "__main__":
    main()
