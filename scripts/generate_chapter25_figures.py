"""Generate Chapter 25 publication figures."""

from __future__ import annotations

import os
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

# Publication figures should be reproducible from the bundled teaching sample.
os.environ["DASHBOARD_DATA_MODE"] = "offline"
os.environ["OPENAI_API_KEY"] = ""

from dashboard import api as dashboard_api  # noqa: E402
from dashboard import kline_analysis as kline_mod  # noqa: E402
from dashboard import signal_analysis as signal_mod  # noqa: E402

dashboard_api.prefer_offline = lambda: True
dashboard_api.serve_offline_first = lambda *, refresh=False: not refresh
dashboard_api.try_live_public = lambda: False
kline_mod.prefer_offline = lambda: True
kline_mod.try_live_public = lambda: False
signal_mod.prefer_offline = lambda: True

run_kline_analysis = kline_mod.run_kline_analysis
run_signal_analysis = signal_mod.run_signal_analysis


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


def save_kline_llm_binding() -> None:
    steps = [
        ("K线样本", "candles\nopen/high/low/close/volume"),
        ("指标层", "MA20 / MA60\nRSI / ATR / 支撑阻力"),
        ("规则信号", "signal / score\nconfidence / tradePlan"),
        ("LLM解释", "summary / logicFlow\n必须引用规则证据"),
        ("页面状态", "engineMeta / fallback\n错误说明 / 边界"),
    ]
    colors = [BLUE, TEAL, ORANGE, PURPLE, RED]
    fig, ax = plt.subplots(figsize=(12.5, 4.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "单币种页面必须先有证据，再有模型解释", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    xs = [0.04, 0.23, 0.42, 0.61, 0.80]
    width = 0.14
    for idx, ((title, body), color, x) in enumerate(zip(steps, colors, xs, strict=True)):
        ax.add_patch(Rectangle((x, 0.34), width, 0.4, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.text(x + 0.012, 0.66, title, transform=ax.transAxes, fontsize=12, color=color, weight="bold")
        ax.text(x + 0.012, 0.56, body, transform=ax.transAxes, fontsize=9.4, color=INK, va="top")
        if idx < len(xs) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.01, 0.54), (xs[idx + 1] - 0.01, 0.54), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=14, linewidth=1.8, color=MUTED))
    ax.text(0.04, 0.15, "对应代码：ResearchPage 调用 fetchKlineAnalysis、submitLlmSignalAnalysis、pollLlmSignalAnalysis；后端先生成规则基线，再合并 LLM 输出。", transform=ax.transAxes, fontsize=10.2, color=MUTED)
    fig.savefig(OUT / "chapter-25-kline-llm-binding.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-25-kline-llm-binding.png")


def save_kline_indicator_chart() -> None:
    payload = run_kline_analysis("BTC-USDT", kline_type="1hour", limit=120)
    candles = payload.get("candles") or []
    closes = [float(row.get("close") or 0) for row in candles]
    dates = [str(row.get("date") or idx) for idx, row in enumerate(candles)]
    metrics = payload.get("metrics") or {}
    x = list(range(len(closes)))

    def rolling(values: list[float], window: int) -> list[float | None]:
        out: list[float | None] = []
        for idx in range(len(values)):
            if idx + 1 < window:
                out.append(None)
            else:
                out.append(sum(values[idx + 1 - window : idx + 1]) / window)
        return out

    ma20 = rolling(closes, 20)
    ma60 = rolling(closes, 60)
    fig, ax = plt.subplots(figsize=(11.6, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.plot(x, closes, color=INK, linewidth=1.8, label="close")
    ax.plot(x, [v if v is not None else float("nan") for v in ma20], color=BLUE, linewidth=1.6, label="MA20")
    ax.plot(x, [v if v is not None else float("nan") for v in ma60], color=ORANGE, linewidth=1.6, label="MA60")
    ax.axhline(float(metrics.get("support20") or 0), color=TEAL, linestyle="--", linewidth=1.2, label="support20")
    ax.axhline(float(metrics.get("resistance20") or 0), color=RED, linestyle="--", linewidth=1.2, label="resistance20")
    ticks = [0, max(0, len(x) // 3), max(0, len(x) * 2 // 3), len(x) - 1]
    ax.set_xticks(ticks)
    ax.set_xticklabels([dates[i] for i in ticks], rotation=0)
    ax.grid(color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    ax.text(
        0.0,
        -0.18,
        f"source={payload.get('source')}，trend={payload.get('trend')}，RSI={metrics.get('rsi')}，regime={metrics.get('regime')}。",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-25-kline-indicator-chart.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-25-kline-indicator-chart.png")


def save_metric_verdict_card() -> None:
    payload = run_kline_analysis("BTC-USDT", kline_type="1hour", limit=120)
    metrics = payload.get("metrics") or {}
    verdict = payload.get("verdict") or {}
    rows = [
        ("最新价", f"{metrics.get('latestClose'):.2f}", "页面价格卡"),
        ("RSI", metrics.get("rsi"), "动量状态"),
        ("MA20 / MA60", f"{metrics.get('sma20'):.2f} / {metrics.get('sma60'):.2f}", "趋势基线"),
        ("支撑 / 阻力", f"{metrics.get('support20'):.2f} / {metrics.get('resistance20'):.2f}", "tradePlan 价位线"),
        ("规则判断", f"{verdict.get('actionLabel')} / {verdict.get('score')}", "LLM 解释前的基线"),
        ("原因", "；".join(verdict.get("reasons") or []), "可复算证据"),
    ]
    fig, ax = plt.subplots(figsize=(12, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.91, "K线页面的结论必须先落在可复算指标上", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    col_x = [0.05, 0.25, 0.48]
    col_w = [0.16, 0.18, 0.38]
    headers = ["字段", "真实值", "页面职责"]
    y0 = 0.78
    row_h = 0.105
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.07, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.012, y0 + 0.035, header, transform=ax.transAxes, va="center", fontsize=10.8, color="#FFFFFF", weight="bold")
    for i, row in enumerate(rows):
        y = y0 - (i + 1) * row_h
        fill_color = "#FFFFFF" if i % 2 == 0 else "#F8FAFC"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=fill_color, edgecolor=GRID))
            ax.text(x + 0.012, y + row_h / 2, fill(str(value), 34), transform=ax.transAxes, va="center", fontsize=9.8, color=INK)
    ax.text(0.05, 0.05, "来源：dashboard.kline_analysis.run_kline_analysis('BTC-USDT', '1hour')。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-25-metric-verdict-card.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-25-metric-verdict-card.png")


def save_multitimeframe_signal_matrix() -> None:
    payload = run_signal_analysis("BTC")
    bundle = payload.get("kline") or {}
    labels = list(bundle.keys())
    scores = [float(bundle[tf].get("score") or 0) for tf in labels]
    rsi_values = [float(bundle[tf].get("rsi") or 0) for tf in labels]
    colors = [TEAL if score > 0 else RED if score < 0 else "#64748B" for score in scores]
    x = list(range(len(labels)))
    fig, ax = plt.subplots(figsize=(10.8, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar(x, scores, color=colors, width=0.55, label="规则分数")
    ax.plot(x, rsi_values, color=ORANGE, marker="o", linewidth=2, label="RSI")
    ax.axhline(0, color="#94A3B8", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("score / RSI")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for idx, tf in enumerate(labels):
        row = bundle[tf]
        ax.text(idx, scores[idx] + (2 if scores[idx] >= 0 else -4), row.get("trend", ""), ha="center", va="bottom" if scores[idx] >= 0 else "top", fontsize=9.5, color=INK)
    ax.legend(frameon=False, loc="upper right")
    ax.text(0.0, -0.18, f"signal={payload.get('signalLabel')}，score={payload.get('score')}，marketState={payload.get('analysis', {}).get('marketState')}。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-25-multitimeframe-signal-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-25-multitimeframe-signal-matrix.png")


def save_rule_llm_comparison() -> None:
    rule = run_signal_analysis("BTC")
    llm = dict(rule)
    llm["engine"] = "sandbox-rule-based"
    llm["engineMeta"] = {
        "provider": "sandbox",
        "model": "deepseek-v4-pro",
        "displayModel": "DeepSeek V4 Pro",
        "note": "教学图禁用 OPENAI_API_KEY；页面应展示 fallback 状态。",
    }
    llm["summary"] = f"{rule.get('signalLabel')}，但当前为规则基线 fallback，不能当成 LLM 成功调用。"
    rows = [
        ("引擎", rule.get("engine"), llm.get("engine")),
        ("模型状态", rule.get("engineMeta", {}).get("model"), llm.get("engineMeta", {}).get("displayModel") or llm.get("engineMeta", {}).get("model")),
        ("信号", rule.get("signalLabel"), llm.get("signalLabel")),
        ("分数", rule.get("score"), llm.get("score")),
        ("置信度", rule.get("confidence"), llm.get("confidence")),
        ("市场状态", rule.get("analysis", {}).get("marketState"), llm.get("analysis", {}).get("marketState")),
        ("执行准备度", rule.get("analysis", {}).get("executionReadiness"), llm.get("analysis", {}).get("executionReadiness")),
    ]
    fig, ax = plt.subplots(figsize=(12, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.91, "规则基线和 LLM 输出要同屏比较", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    col_x = [0.05, 0.25, 0.55]
    col_w = [0.16, 0.24, 0.34]
    headers = ["字段", "规则基线", "LLM / fallback 输出"]
    y0 = 0.78
    row_h = 0.092
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.07, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.012, y0 + 0.035, header, transform=ax.transAxes, va="center", fontsize=10.8, color="#FFFFFF", weight="bold")
    for i, row in enumerate(rows):
        y = y0 - (i + 1) * row_h
        fill_color = "#FFFFFF" if i % 2 == 0 else "#F8FAFC"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=fill_color, edgecolor=GRID))
            ax.text(x + 0.012, y + row_h / 2, fill(str(value), 34), transform=ax.transAxes, va="center", fontsize=9.6, color=INK)
    ax.text(0.05, 0.05, "要点：LLM 可以改写解释，但不能隐藏规则基线、engineMeta、fallback note 和风险边界。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-25-rule-llm-comparison.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-25-rule-llm-comparison.png")


def save_field_trace_matrix() -> None:
    rows = [
        ("K线图", "candles[].open/high/low/close", "fetchKlineAnalysis", "OK"),
        ("MA20 / MA60", "metrics.sma20 / metrics.sma60", "run_kline_analysis", "OK"),
        ("RSI", "metrics.rsi", "run_kline_analysis", "OK"),
        ("信号标签", "signalLabel", "run_signal_analysis / LLM", "OK"),
        ("置信度", "confidence", "run_signal_analysis / LLM", "OK"),
        ("交易计划", "tradePlan.entry/stop/target", "run_signal_analysis", "OK"),
        ("模型状态", "engineMeta", "run_llm_signal_analysis", "OK"),
        ("失败说明", "engineMeta.note / signalError", "LLM fallback", "OK"),
    ]
    fig, ax = plt.subplots(figsize=(12, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.91, "页面字段必须能回到 API 输出", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    col_x = [0.05, 0.24, 0.53, 0.78]
    col_w = [0.15, 0.25, 0.21, 0.08]
    headers = ["页面元素", "API 字段", "来源函数", "追溯"]
    y0 = 0.79
    row_h = 0.078
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.065, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.01, y0 + 0.032, header, transform=ax.transAxes, va="center", fontsize=10.5, color="#FFFFFF", weight="bold")
    for i, row in enumerate(rows):
        y = y0 - (i + 1) * row_h
        fill_color = "#FFFFFF" if i % 2 == 0 else "#F8FAFC"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=fill_color, edgecolor=GRID))
            ax.text(x + 0.01, y + row_h / 2, fill(str(value), 28), transform=ax.transAxes, va="center", fontsize=9.2, color=INK)
    ax.text(0.05, 0.05, "字段追溯率 = matched_fields / required_fields；本章核心字段应达到 100%。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-25-field-trace-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-25-field-trace-matrix.png")


def save_llm_fallback_ladder() -> None:
    steps = [
        ("规则基线", "run_signal_analysis\n永远先产出"),
        ("检查密钥", "OPENAI_API_KEY\n未配置则规则输出"),
        ("提交任务", "submit_task / poll\n异步状态可见"),
        ("合并 JSON", "_merge_llm\n校验 signal/score/confidence"),
        ("失败回退", "engineMeta.note\n保留错误原因"),
        ("页面边界", "不是投资建议\n不得隐藏 fallback"),
    ]
    colors = [BLUE, TEAL, ORANGE, PURPLE, RED, "#334155"]
    fig, ax = plt.subplots(figsize=(12.8, 4.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "LLM 信号必须有规则基线和失败回退", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
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
    ax.text(0.04, 0.14, "对应代码：dashboard.llm_signal.run_llm_signal_analysis()；LLM 成功、未配置和调用失败都要有可见状态。", transform=ax.transAxes, fontsize=10.2, color=MUTED)
    fig.savefig(OUT / "chapter-25-llm-fallback-ladder.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-25-llm-fallback-ladder.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    setup_matplotlib()
    save_kline_llm_binding()
    save_kline_indicator_chart()
    save_metric_verdict_card()
    save_multitimeframe_signal_matrix()
    save_rule_llm_comparison()
    save_field_trace_matrix()
    save_llm_fallback_ladder()


if __name__ == "__main__":
    main()
