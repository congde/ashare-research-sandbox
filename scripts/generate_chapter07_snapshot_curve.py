"""Generate the Chapter 07 snapshot-history evidence curve."""

from __future__ import annotations

import json
import textwrap
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib import pyplot as plt

try:
    import seaborn as sns
except ModuleNotFoundError:  # pragma: no cover - depends on local teaching env
    sns = None


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "dashboard" / "snapshots"
HISTORY = SNAPSHOTS / "history"
OUT = ROOT / "docs" / "v2" / "assets"

DATASETS = ["market_tickers", "market_candles", "onchain", "ai_picks"]

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

COLORS = {
    "market_tickers": "#5477C4",
    "market_candles": "#2D9C9C",
    "onchain": "#C94F4F",
    "ai_picks": "#CC6F47",
}


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
    ax.set_title("")
    fig.subplots_adjust(top=0.82)
    left = ax.get_position().x0
    fig.text(left, 0.965, textwrap.fill(title, width=72), ha="left", va="top", fontsize=17, fontweight="semibold", color=TOKENS["ink"])
    fig.text(left, 0.918, textwrap.fill(subtitle, width=112), ha="left", va="top", fontsize=10.5, color=TOKENS["muted"])
    if sns is not None:
        sns.despine(ax=ax)
    else:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)


def parse_history_time(path: Path) -> datetime:
    stem = path.stem
    value = stem.replace("T", " ").replace("+00-00", "+00:00")
    value = value.replace("-", ":", 2) if False else value
    date_part, time_part = stem.split("T", maxsplit=1)
    time_part = time_part.replace("+00-00", "+00:00").replace("-", ":", 2)
    return datetime.fromisoformat(f"{date_part}T{time_part}").replace(tzinfo=None)


def latest_snapshot_meta(dataset: str) -> dict:
    path = SNAPSHOTS / f"{dataset}.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload.get("snapshot") or {}


def cumulative_rows(dataset: str) -> list[tuple[datetime, int]]:
    paths = sorted((HISTORY / dataset).glob("*.json"))
    rows: list[tuple[datetime, int]] = []
    for index, path in enumerate(paths, start=1):
        rows.append((parse_history_time(path), index))
    return rows


def build_chart() -> Path:
    use_chart_theme()
    fig, ax = plt.subplots(figsize=(14, 8), dpi=160)

    final_counts: dict[str, int] = {}
    latest_saved: dict[str, str] = {}
    for dataset in DATASETS:
        rows = cumulative_rows(dataset)
        if not rows:
            continue
        dates = [item[0] for item in rows]
        counts = [item[1] for item in rows]
        final_counts[dataset] = counts[-1]
        ax.step(dates, counts, where="post", linewidth=2.0, color=COLORS[dataset], label=dataset)
        ax.scatter([dates[-1]], [counts[-1]], s=44, color=COLORS[dataset], edgecolor=TOKENS["panel"], linewidth=0.8, zorder=4)

        saved_at = latest_snapshot_meta(dataset).get("saved_at")
        if saved_at:
            latest_saved[dataset] = str(saved_at).split(".")[0].replace("T", " ")

    note_lines = ["latest 指针保存时间"]
    note_lines.extend(f"{name}: {latest_saved.get(name, 'missing')}" for name in DATASETS)
    ax.text(
        0.985,
        0.05,
        "\n".join(note_lines),
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9.3,
        color=TOKENS["ink"],
        bbox={"boxstyle": "round,pad=0.45", "fc": "#E6F6F5", "ec": "#126C6C", "lw": 1.0},
    )

    summary = "，".join(f"{name}={count}" for name, count in final_counts.items())
    ax.annotate(
        f"历史版本数量\n{summary}",
        xy=(0.02, 0.92),
        xycoords="axes fraction",
        ha="left",
        va="top",
        fontsize=9.5,
        color=TOKENS["ink"],
        bbox={"boxstyle": "round,pad=0.45", "fc": "#FFF3E8", "ec": "#804126", "lw": 1.0},
    )

    locator = mdates.AutoDateLocator(minticks=5, maxticks=8)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.set_ylabel("历史快照累计数量")
    ax.set_xlabel("保存时间")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), frameon=False, ncol=4, borderaxespad=0)

    title = "核心数据集历史快照累积曲线：latest 只是入口，history 才是证据"
    subtitle = "来源目录：data/dashboard/snapshots/history/；latest 文件用于标注当前指针保存时间。图中每一个台阶都对应一个可回查 JSON 历史文件。"
    add_chart_header(fig, ax, title, subtitle)

    fig.text(
        ax.get_position().x0,
        0.045,
        "停止线：只有 latest 而没有 history，不能证明研究输入可复现；历史文件存在但来源、完整性或保存时间缺失时，结论必须退回快照记录。",
        ha="left",
        va="bottom",
        fontsize=9.5,
        color=TOKENS["muted"],
    )

    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / "chapter-07-python-snapshot-history.png"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def main() -> None:
    print(build_chart())


if __name__ == "__main__":
    main()
