"""Generate Chapter 27 publication figures."""

from __future__ import annotations

from pathlib import Path
import sys
import time
from textwrap import fill
from typing import Any, Callable

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from backtest.rolling.service import (  # noqa: E402
    compare_windows,
    execute_backtest,
    run_cpcv_service,
    run_robustness_audit,
    run_walk_forward,
)
from dashboard import api as dashboard_api  # noqa: E402
from research.report import build_report  # noqa: E402


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


def _timed(name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    start = time.perf_counter()
    payload = fn()
    return {"name": name, "ms": round((time.perf_counter() - start) * 1000, 1), "payload": payload}


def _audit_payloads() -> dict[str, Any]:
    kwargs = {
        "strategy_name": "ma_crossover",
        "symbol": "WEB3-DEMO/USDT",
        "limit": 120,
        "cost_preset": "teaching",
    }
    return {
        "backtest": execute_backtest(**kwargs),
        "windows": compare_windows(**kwargs),
        "wfo": run_walk_forward(**kwargs),
        "robustness": run_robustness_audit(**kwargs),
        "cpcv": run_cpcv_service(**kwargs),
        "risk": build_report(short=3, long=7),
    }


def save_browser_research_path() -> None:
    steps = [
        ("/data-sources", "来源 / 快照\n失败原因"),
        ("/trading", "行情总览\nK 线状态"),
        ("/radar", "候选排序\n风险等级"),
        ("/research", "K 线证据\n规则/LLM"),
        ("/backtests", "成本 / WFO\nPBO / CPCV"),
        ("/risk", "规则栈\n拒单原因"),
    ]
    colors = [BLUE, TEAL, "#0891B2", ORANGE, PURPLE, RED]
    fig, ax = plt.subplots(figsize=(13.4, 4.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "浏览器验收要证明路径可走、状态可见、失败可退", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    width = 0.128
    gap = 0.028
    for i, ((route, body), color) in enumerate(zip(steps, colors, strict=True)):
        x = 0.04 + i * (width + gap)
        ax.add_patch(Rectangle((x, 0.34), width, 0.38, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.text(x + 0.012, 0.64, route, transform=ax.transAxes, fontsize=10.5, color=color, weight="bold")
        ax.text(x + 0.012, 0.54, body, transform=ax.transAxes, fontsize=9.2, color=INK, va="top")
        if i < len(steps) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.005, 0.53), (x + width + gap - 0.006, 0.53), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=13, linewidth=1.6, color=MUTED))
    ax.text(0.04, 0.15, "对应代码：src/web/src/App.tsx 路由，app.py 的 /api/* 契约，tests/test_app_server.py 的 SPA/API 冒烟测试。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-27-browser-research-path.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-27-browser-research-path.png")


def save_route_api_contract() -> None:
    rows = [
        ("/data-sources", "DataSourcesPage", "/api/dashboard/sources/status", "source / saved_at / error"),
        ("/trading", "DashboardPage", "/api/market/candles", "symbol / candles / source"),
        ("/radar", "RadarPage", "/api/dashboard/opportunity-scan", "rank / riskLevel / reasons"),
        ("/research", "ResearchPage", "/api/market/kline-analysis", "trend / support / resistance"),
        ("/backtests", "BacktestsPage", "/api/dashboard/backtest/*", "cost / DSR / PBO / CPCV"),
        ("/risk", "RiskPage", "/api/report", "risk_rules / rejections"),
    ]
    fig, ax = plt.subplots(figsize=(13, 6.2), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.93, "每个浏览器页面都要能追到 API 字段", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    headers = ["浏览器路由", "React 页面", "API 契约", "验收字段"]
    col_x = [0.04, 0.23, 0.43, 0.71]
    col_w = [0.17, 0.18, 0.26, 0.25]
    y0 = 0.82
    row_h = 0.105
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.075, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.01, y0 + 0.048, header, transform=ax.transAxes, fontsize=10.2, color="#FFFFFF", weight="bold", va="center")
    for r, row in enumerate(rows):
        y = y0 - (r + 1) * row_h
        bg = "#FFFFFF" if r % 2 == 0 else "#F1F5F9"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=bg, edgecolor=GRID, linewidth=1))
            ax.text(x + 0.01, y + row_h * 0.58, fill(value, 26), transform=ax.transAxes, fontsize=9.4, color=INK, va="center")
    ax.text(0.04, 0.06, "验收口径：截图只能证明可见；API 字段对账才能证明可追。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-27-route-api-contract.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-27-route-api-contract.png")


def save_e2e_latency_status() -> None:
    calls = [
        _timed("sources", lambda: dashboard_api.sources_status()),
        _timed("candles", lambda: dashboard_api.market_candles(symbol="BTC-USDT", limit=80)),
        _timed("opportunity", lambda: dashboard_api.opportunity_scan(top_k=8)),
        _timed("kline", lambda: dashboard_api.kline_analysis(symbol="BTC-USDT", kline_type="1day", limit=80)),
        _timed("backtest", lambda: execute_backtest(strategy_name="ma_crossover", symbol="WEB3-DEMO/USDT", limit=120, cost_preset="teaching")),
        _timed("wfo", lambda: run_walk_forward(strategy_name="ma_crossover", symbol="WEB3-DEMO/USDT", limit=120, cost_preset="teaching")),
        _timed("risk", lambda: build_report(short=3, long=7)),
    ]
    labels = [row["name"] for row in calls]
    values = [row["ms"] for row in calls]
    colors = [TEAL if (row["payload"].get("ok", True) is True) else RED for row in calls]
    fig, ax = plt.subplots(figsize=(11.8, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar(labels, values, color=colors)
    ax.set_ylabel("毫秒")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for i, value in enumerate(values):
        ax.text(i, value + max(values) * 0.02, f"{value:.0f}", ha="center", fontsize=9, color=INK)
    ax.text(0.0, -0.18, "数据来自 dashboard.api 与 rolling backtest 服务；不同机器耗时可变，返回字段和失败出口不可省略。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-27-e2e-latency-status.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-27-e2e-latency-status.png")


def save_backtest_audit_summary() -> None:
    data = _audit_payloads()
    bt = data["backtest"]
    windows = data["windows"]
    wfo = data["wfo"]
    robustness = data["robustness"]
    cpcv = data["cpcv"]["cpcv"]
    metrics = [
        ("回测收益", float(bt["total_return_pct"]), "%", RED),
        ("最大回撤", float(bt["max_drawdown_pct"]), "%", ORANGE),
        ("正窗口", float(windows["positive_windows"]) / max(1, float(windows["num_windows"])) * 100, "%", RED),
        ("OOS 收益", float(wfo["out_of_sample_return_pct"]), "%", TEAL),
        ("稳定性", float(robustness["parameter_sensitivity"]["stability_score"]) * 100, "%", ORANGE),
        ("PBO", float(robustness["pbo"]["pbo"]) * 100, "%", RED),
        ("CPCV 盈利路径", float(cpcv["profitable_paths_pct"]), "%", RED),
    ]
    labels = [m[0] for m in metrics]
    vals = [m[1] for m in metrics]
    colors = [m[3] for m in metrics]
    fig, ax = plt.subplots(figsize=(12.4, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar(labels, vals, color=colors)
    ax.axhline(0, color="#94A3B8", linewidth=1)
    ax.set_ylabel("百分比")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", rotation=18)
    for i, value in enumerate(vals):
        offset = 2 if value >= 0 else -5
        ax.text(i, value + offset, f"{value:.1f}%", ha="center", fontsize=9, color=INK)
    ax.text(
        0.0,
        -0.24,
        f"WEB3-DEMO/USDT ma_crossover: trades={bt['total_trades']}, DSR={wfo['dsr']}, trials={wfo['num_trials']}, robust={robustness['verdict']}, CPCV={cpcv['verdict']}.",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-27-backtest-audit-summary.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-27-backtest-audit-summary.png")


def save_failure_exit_matrix() -> None:
    data = _audit_payloads()
    risk = data["risk"]
    rows = [
        ("SPA 路由", "缺失前端路径", "返回 index.html 或 404 明确", "tests/test_app_server.py"),
        ("数据源", "上游不可用", "显示 snapshot / fixture 来源", "sources_status"),
        ("回测", "窗口不稳定", f"{data['windows']['positive_windows']}/{data['windows']['num_windows']} 正窗口", "compare_windows"),
        ("WFO", "过拟合警告", f"DSR={data['wfo']['dsr']} warning={data['wfo']['overfit_warning']}", "run_walk_forward"),
        ("稳健性", "参数/PBO 异常", f"verdict={data['robustness']['verdict']} PBO={data['robustness']['pbo']['pbo']}", "run_robustness_audit"),
        ("风险中心", "运行期拒单", f"{len(risk['backtest']['risk_rejections'])} 次拒单", "build_report"),
    ]
    fig, ax = plt.subplots(figsize=(13, 6.4), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.93, "异常出口也是端到端验收的一部分", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    headers = ["环节", "失败注入", "页面应显示", "证据来源"]
    col_x = [0.04, 0.20, 0.42, 0.72]
    col_w = [0.14, 0.20, 0.28, 0.22]
    y0 = 0.82
    row_h = 0.108
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.075, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.01, y0 + 0.048, header, transform=ax.transAxes, fontsize=10, color="#FFFFFF", weight="bold", va="center")
    for r, row in enumerate(rows):
        y = y0 - (r + 1) * row_h
        bg = "#FFFFFF" if r % 2 == 0 else "#F1F5F9"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=bg, edgecolor=GRID, linewidth=1))
            ax.text(x + 0.01, y + row_h * 0.58, fill(str(value), 30), transform=ax.transAxes, fontsize=9.2, color=INK, va="center")
    ax.text(0.04, 0.05, "结论边界：异常出口可见，只证明应用诚实降级；不能证明策略有效。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-27-failure-exit-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-27-failure-exit-matrix.png")


def save_evidence_package_checklist() -> None:
    items = [
        ("路径记录", 6, "路由顺序和操作动作"),
        ("截图", 6, "关键页面状态"),
        ("API 对账", 6, "字段能回到接口"),
        ("异常出口", 5, "失败原因可见"),
        ("复测命令", 3, "pytest / verify / build"),
        ("人工结论", 3, "继续 / 修改 / 停止"),
    ]
    labels = [row[0] for row in items]
    values = [row[1] for row in items]
    fig, ax = plt.subplots(figsize=(11.6, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    bars = ax.barh(labels, values, color=[BLUE, TEAL, "#0891B2", ORANGE, PURPLE, RED])
    ax.set_xlabel("证据件数 / 检查点")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for bar, (_, value, note) in zip(bars, items, strict=True):
        ax.text(value + 0.1, bar.get_y() + bar.get_height() / 2, note, va="center", fontsize=9.3, color=INK)
    ax.text(0.0, -0.14, "建议：把截图、API JSON 摘要、命令输出和人工结论放在同一份验收记录里。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-27-evidence-package-checklist.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-27-evidence-package-checklist.png")


def main() -> None:
    setup_matplotlib()
    OUT.mkdir(parents=True, exist_ok=True)
    save_browser_research_path()
    save_route_api_contract()
    save_e2e_latency_status()
    save_backtest_audit_summary()
    save_failure_exit_matrix()
    save_evidence_package_checklist()


if __name__ == "__main__":
    main()
