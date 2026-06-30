"""Generate Chapter 24 publication figures."""

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

from dashboard import api  # noqa: E402


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


def fmt_large(value: float | int | str | None) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number >= 1_000_000_000:
        return f"{sign}{number / 1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"{sign}{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{sign}{number / 1_000:.1f}K"
    return f"{sign}{number:.0f}"


def save_market_candidate_path() -> None:
    steps = [
        ("行情总览", "market_tickers\n价格 / 涨跌 / 成交额"),
        ("机会雷达", "opportunity_scan\n分数 / 置信度 / 理由"),
        ("数据源", "sources_status\nsource / ok / mode"),
        ("候选记录", "rank / riskLevel\nscanTime / snapshot"),
        ("后续研究", "K线 / LLM信号\n回测 / 风控"),
    ]
    colors = [BLUE, TEAL, ORANGE, PURPLE, RED]
    fig, ax = plt.subplots(figsize=(12.5, 4.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "行情入口必须把候选、来源和停止线放在一条路径上", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    xs = [0.04, 0.23, 0.42, 0.61, 0.80]
    width = 0.14
    for idx, ((title, body), color, x) in enumerate(zip(steps, colors, xs, strict=True)):
        ax.add_patch(Rectangle((x, 0.34), width, 0.4, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.text(x + 0.012, 0.66, title, transform=ax.transAxes, fontsize=12, color=color, weight="bold")
        ax.text(x + 0.012, 0.56, body, transform=ax.transAxes, fontsize=9.4, color=INK, va="top")
        if idx < len(xs) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.01, 0.54), (xs[idx + 1] - 0.01, 0.54), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=14, linewidth=1.8, color=MUTED))
    ax.text(0.04, 0.15, "对应页面：DashboardPage、RadarPage、DataSourcesPage；对应后端：dashboard.api.market_tickers/opportunity_scan/sources_status。", transform=ax.transAxes, fontsize=10.2, color=MUTED)
    fig.savefig(OUT / "chapter-24-market-candidate-path.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-24-market-candidate-path.png")


def save_opportunity_score_chart() -> None:
    payload = api.opportunity_scan(top_k=5, max_symbols=30)
    rows = payload.get("opportunities") or []
    labels = [f"#{row.get('rank')} {row.get('symbol')}" for row in rows]
    scores = [float(row.get("score") or 0) for row in rows]
    confidence = [float(row.get("confidence") or 0) for row in rows]
    colors = [RED if score < 0 else TEAL for score in scores]
    y_pos = list(range(len(labels)))
    fig, ax = plt.subplots(figsize=(11.2, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.barh(y_pos, scores, color=colors, height=0.55, label="机会分数")
    ax.scatter(confidence, y_pos, color=ORANGE, s=80, label="置信度")
    ax.axvline(0, color="#94A3B8", linewidth=1)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("分数 / 置信度")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for idx, row in enumerate(rows):
        reasons = " · ".join(row.get("keyReasons") or [])
        ax.text(max(scores[idx], 0) + 2, idx, fill(f"{row.get('label')} / {row.get('riskLevel')} / {reasons}", 30), va="center", fontsize=9.2, color=INK)
    ax.legend(frameon=False, loc="lower right")
    ax.text(0.0, -0.18, f"source={payload.get('source')}，scanTime={payload.get('scanTime')}，totalScanned={payload.get('totalScanned')}。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-24-opportunity-score-chart.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-24-opportunity-score-chart.png")


def save_market_ticker_volume_chart() -> None:
    payload = api.market_tickers(limit=8)
    rows = payload.get("tickers") or []
    labels = [str(row.get("symbol", "?")).replace("-USDT", "") for row in rows]
    volumes = [float(row.get("volValue") or 0) for row in rows]
    changes = [float(row.get("changeRate") or 0) * 100 for row in rows]
    colors = [TEAL if change >= 0 else RED for change in changes]
    fig, ax = plt.subplots(figsize=(11, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    bars = ax.bar(labels, [v / 1_000_000 for v in volumes], color=colors)
    ax.set_ylabel("24h 成交额（百万）")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for bar, change, volume in zip(bars, changes, volumes, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 5, f"{change:+.1f}%\n{fmt_large(volume)}", ha="center", va="bottom", fontsize=9, color=INK)
    ax.text(0.0, -0.18, f"source={payload.get('source')}，count={payload.get('count')}；颜色表示 24h 涨跌方向，不代表交易建议。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-24-market-ticker-volume.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-24-market-ticker-volume.png")


def save_source_probe_matrix() -> None:
    payload = api.sources_status()
    probes = payload.get("probes") or []
    labels = [str(row.get("name")) for row in probes]
    colors = [TEAL if row.get("ok") else RED for row in probes]
    fig, ax = plt.subplots(figsize=(11, 5.3), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.barh(labels, [1] * len(labels), color=colors, height=0.6)
    ax.set_xlim(0, 1.2)
    ax.set_xticks([])
    ax.invert_yaxis()
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    for idx, row in enumerate(probes):
        ax.text(0.03, idx, "OK" if row.get("ok") else "FAIL", va="center", ha="left", color="#FFFFFF", weight="bold", fontsize=10.5)
        ax.text(1.03, idx, str(row.get("source") or row.get("error") or "-"), va="center", ha="left", color=INK, fontsize=10)
    env = payload.get("env") or {}
    ax.text(0.0, -0.16, f"data_mode={env.get('data_mode')}，valuescan={env.get('valuescan')}，dexscan={env.get('dexscan')}。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-24-source-probe-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-24-source-probe-matrix.png")


def save_data_source_payload_card() -> None:
    ai = api.ai_picks()
    dex = api.dex_trending(limit=5)
    sector = api.sector_fund(1)
    tickers = api.market_tickers(limit=300)
    rows = [
        ("运行模式", ai.get("source", "-"), "页面必须写明 Snapshot/Fixture/Live"),
        ("AI 机会", f"{len(ai.get('chance') or [])} 条", "候选入口，不是买入建议"),
        ("资金异动", f"{len(ai.get('funds') or [])} 条", "解释资金线索"),
        ("风险回避", f"{len(ai.get('risk') or [])} 条", "风险候选要显式标记"),
        ("DEX Trending", f"{len(dex.get('tokens') or [])} 条", "高波动样本要看 riskLevel"),
        ("板块资金", f"{len(sector.get('sectors') or [])} 个板块", "展示 1h 资金轮动"),
        ("USDT 交易对", f"{tickers.get('count')} 个", "流动性是候选前置条件"),
    ]
    fig, ax = plt.subplots(figsize=(12, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.91, "DataSourcesPage 的内容不是装饰，而是候选可信度证据", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    col_x = [0.05, 0.28, 0.47]
    col_w = [0.18, 0.14, 0.38]
    headers = ["面板字段", "真实值", "研究含义"]
    y0 = 0.78
    row_h = 0.095
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.07, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.012, y0 + 0.035, header, transform=ax.transAxes, va="center", fontsize=10.8, color="#FFFFFF", weight="bold")
    for i, row in enumerate(rows):
        y = y0 - (i + 1) * row_h
        fill_color = "#FFFFFF" if i % 2 == 0 else "#F8FAFC"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=fill_color, edgecolor=GRID))
            ax.text(x + 0.012, y + row_h / 2, fill(str(value), 34), transform=ax.transAxes, va="center", fontsize=9.8, color=INK)
    ax.text(0.05, 0.05, "来源：dashboard.api.ai_picks/dex_trending/sector_fund/market_tickers。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-24-data-source-payload-card.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-24-data-source-payload-card.png")


def save_sector_inflow_chart() -> None:
    payload = api.sector_fund(1)
    rows = []
    for sector in payload.get("sectors") or []:
        name = sector.get("tagsSimplified") or sector.get("tag") or "sector"
        entries = sector.get("categoriesTradeDataList") or []
        h1 = next((entry for entry in entries if str(entry.get("timeRange")).lower() == "h1"), None)
        if h1:
            rows.append((str(name), float(h1.get("tradeInflow") or 0)))
    rows = sorted(rows, key=lambda item: item[1], reverse=True)[:8]
    labels = [row[0] for row in rows]
    values = [row[1] for row in rows]
    colors = [TEAL if value >= 0 else RED for value in values]
    fig, ax = plt.subplots(figsize=(11, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.barh(labels, values, color=colors, height=0.58)
    ax.axvline(0, color="#94A3B8", linewidth=1)
    ax.invert_yaxis()
    ax.set_xlabel("1h tradeInflow")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for idx, value in enumerate(values):
        ax.text(value + (max(abs(v) for v in values) * 0.02 if value >= 0 else -max(abs(v) for v in values) * 0.02), idx, fmt_large(value), va="center", ha="left" if value >= 0 else "right", fontsize=9.5, color=INK)
    ax.text(0.0, -0.16, f"source={payload.get('source')}，tradeType={payload.get('tradeType')}；资金流向是背景证据，不是独立交易信号。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-24-sector-inflow-chart.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-24-sector-inflow-chart.png")


def save_offline_fallback_ladder() -> None:
    steps = [
        ("刷新请求", "用户点击刷新\n或页面自动加载"),
        ("上游代理", "WEB3_TRADING_UPSTREAM\n可用则优先"),
        ("直连 API", "ValueScan / DexScan\nweb3交易所 / 恐贪"),
        ("快照缓存", "data/dashboard/snapshots\nsource=snapshot"),
        ("内置样本", "data/dashboard\nsource=fixture"),
        ("页面说明", "显示来源 / 时间 / 失败\n不得伪装实时"),
    ]
    colors = [BLUE, PURPLE, TEAL, ORANGE, "#64748B", RED]
    fig, ax = plt.subplots(figsize=(12.8, 4.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "实时数据断开后，页面必须解释降级路径", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
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
    ax.text(0.04, 0.14, "对应代码：dashboard.api._try_upstream/_with_fallback/try_cached_first/load_offline；页面文案要区分 Snapshot、Fixture 和 Live。", transform=ax.transAxes, fontsize=10.2, color=MUTED)
    fig.savefig(OUT / "chapter-24-offline-fallback-ladder.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-24-offline-fallback-ladder.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    setup_matplotlib()
    save_market_candidate_path()
    save_opportunity_score_chart()
    save_market_ticker_volume_chart()
    save_source_probe_matrix()
    save_data_source_payload_card()
    save_sector_inflow_chart()
    save_offline_fallback_ladder()


if __name__ == "__main__":
    main()
