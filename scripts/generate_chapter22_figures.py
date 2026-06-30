"""Generate Chapter 22 publication figures."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
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

from backtest.rolling.portfolio import compare_portfolio  # noqa: E402
from research.report import build_report  # noqa: E402
from risk import (  # noqa: E402
    AbnormalCandleRule,
    KillSwitch,
    MaxDrawdownRule,
    MaxPositionRule,
    MaxSlippageRule,
    RiskManager,
    default_risk_manager,
)
from strategy_engine.backtest.candles import Candle  # noqa: E402
from strategy_engine.backtest.engine import BacktestEngine, StrategyContext  # noqa: E402
from strategy_engine.backtest.portfolio import Portfolio  # noqa: E402
from strategy_engine.backtest.protocol import OrderIntent, OrderSide, OrderType  # noqa: E402


BLUE = "#2563EB"
TEAL = "#0F9B8E"
ORANGE = "#F59E0B"
RED = "#DC2626"
PURPLE = "#7C3AED"
INK = "#111827"
MUTED = "#64748B"
GRID = "#E5E7EB"
PAPER = "#F7F9FC"
UTC = timezone.utc


def setup_matplotlib() -> None:
    plt.rcParams["font.sans-serif"] = [
        "SimHei",
        "Microsoft YaHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def _candle(price: float = 100.0, *, high: float | None = None, low: float | None = None, volume: float = 1.0) -> Candle:
    close = Decimal(str(price))
    return Candle(
        exchange="teaching",
        symbol="BTC/USDT",
        timeframe="1day",
        ts=datetime(2026, 6, 26, tzinfo=UTC),
        open=close,
        high=Decimal(str(high if high is not None else price * 1.001)),
        low=Decimal(str(low if low is not None else price * 0.999)),
        close=close,
        volume=Decimal(str(volume)),
    )


def _intent(qty: str = "1", *, side: OrderSide = OrderSide.BUY) -> OrderIntent:
    return OrderIntent(symbol="BTC/USDT", side=side, type=OrderType.MARKET, qty=Decimal(qty))


def risk_case_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    ctx = StrategyContext(symbol="BTC/USDT", timeframe="1day", portfolio=Portfolio(initial_cash=Decimal("1000")))
    result = MaxPositionRule(max_notional_usd=Decimal("100")).check(
        _intent("2.0"),
        ctx=ctx,
        portfolio=ctx.portfolio,
        candle=_candle(100.0),
    )
    rows.append({"case": "超仓订单", "rule": result.rule_id, "result": "BLOCK" if not result.allowed else "ALLOW"})

    ctx2 = StrategyContext(symbol="BTC/USDT", timeframe="1day", portfolio=Portfolio(initial_cash=Decimal("1000")))
    ctx2.portfolio.apply_buy("BTC/USDT", Decimal("5"), Decimal("100"), Decimal("0"))
    dd_rule = MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))
    dd_rule.check(_intent("0.01"), ctx=ctx2, portfolio=ctx2.portfolio, candle=_candle(100.0))
    result = dd_rule.check(_intent("0.01"), ctx=ctx2, portfolio=ctx2.portfolio, candle=_candle(80.0))
    rows.append({"case": "回撤后加仓", "rule": result.rule_id, "result": "BLOCK" if not result.allowed else "ALLOW"})

    ctx3 = StrategyContext(symbol="BTC/USDT", timeframe="1day", portfolio=Portfolio(initial_cash=Decimal("1000")))
    result = MaxSlippageRule(max_spread_pct=Decimal("0.02")).check(
        _intent("0.1"),
        ctx=ctx3,
        portfolio=ctx3.portfolio,
        candle=_candle(100.0, high=105.0, low=95.0),
    )
    rows.append({"case": "宽价差成交", "rule": result.rule_id, "result": "BLOCK" if not result.allowed else "ALLOW"})

    ctx4 = StrategyContext(symbol="BTC/USDT", timeframe="1day", portfolio=Portfolio(initial_cash=Decimal("1000")))
    stale = _candle(100.0, high=100.0, low=100.0, volume=50.0)
    ctx4.history.append(stale)
    result = AbnormalCandleRule(max_price_jump_pct=Decimal("0.10")).check(
        _intent("0.1"),
        ctx=ctx4,
        portfolio=ctx4.portfolio,
        candle=stale,
    )
    rows.append({"case": "异常 K 线", "rule": result.rule_id, "result": "BLOCK" if not result.allowed else "ALLOW"})

    ctx5 = StrategyContext(symbol="BTC/USDT", timeframe="1day", portfolio=Portfolio(initial_cash=Decimal("1000")))
    kill = KillSwitch()
    kill.trip("incident drill")
    result = kill.check(_intent("0.1"), ctx=ctx5, portfolio=ctx5.portfolio, candle=_candle(100.0))
    rows.append({"case": "急停状态", "rule": result.rule_id, "result": "BLOCK" if not result.allowed else "ALLOW"})
    return rows


def save_risk_order_gate() -> None:
    nodes = [
        ("订单意图", "side / qty / type\n来自策略 on_tick"),
        ("组合状态", "cash / position\nequity / drawdown"),
        ("市场状态", "price / spread\nvolume / jump"),
        ("RiskManager", "按规则顺序检查\n首个拒绝即阻断"),
        ("结果记录", "trade 或\nrisk_rejections"),
    ]
    colors = [BLUE, TEAL, ORANGE, RED, PURPLE]
    fig, ax = plt.subplots(figsize=(12, 4.7), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    xs = [0.04, 0.24, 0.44, 0.64, 0.84]
    width = 0.13
    for i, ((title, body), x, color) in enumerate(zip(nodes, xs, colors, strict=True)):
        ax.add_patch(Rectangle((x, 0.34), width, 0.42, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.text(x + 0.012, 0.67, title, transform=ax.transAxes, fontsize=12.5, color=color, weight="bold")
        ax.text(x + 0.012, 0.56, body, transform=ax.transAxes, fontsize=9.6, color=INK, va="top")
        if i < len(xs) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.012, 0.55), (xs[i + 1] - 0.014, 0.55), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=15, linewidth=1.8, color=MUTED))
    ax.text(
        0.04,
        0.16,
        "对应代码：BacktestEngine._risk_allows() 在提交订单和挂单成交前调用 RiskManager.check()。",
        transform=ax.transAxes,
        fontsize=10.8,
        color=MUTED,
    )
    fig.savefig(OUT / "chapter-22-risk-order-gate.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-22-risk-order-gate.png")


def save_risk_block_matrix() -> None:
    rows = risk_case_rows()
    labels = [row["case"] for row in rows]
    fig, ax = plt.subplots(figsize=(11, 5.4), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.barh(labels, [1] * len(rows), color=RED, height=0.62)
    ax.set_xlim(0, 1.2)
    ax.set_xticks([])
    ax.invert_yaxis()
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    for idx, row in enumerate(rows):
        ax.text(0.03, idx, row["result"], va="center", ha="left", color="#FFFFFF", weight="bold", fontsize=11)
        ax.text(1.03, idx, row["rule"], va="center", ha="left", color=INK, fontsize=10.5)
    ax.text(
        0.0,
        -0.16,
        "样本由真实 RiskRule.check() 构造：超仓、回撤、宽价差、异常 K 线和急停均被阻断。",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-22-risk-block-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-22-risk-block-matrix.png")


def save_position_budget_curve() -> None:
    equity = 10_000
    risk_rates = [0.005, 0.01, 0.02]
    stop_distances = [0.01, 0.02, 0.03, 0.05, 0.08, 0.10]
    fig, ax = plt.subplots(figsize=(10.5, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    for rate, color in zip(risk_rates, [TEAL, BLUE, RED], strict=True):
        notionals = [equity * rate / d for d in stop_distances]
        ax.plot([d * 100 for d in stop_distances], notionals, marker="o", linewidth=2.2, color=color, label=f"单笔风险 {rate * 100:.1f}%")
    ax.set_xlabel("止损距离（%）")
    ax.set_ylabel("名义仓位上限")
    ax.grid(color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    ax.text(
        0.01,
        -0.18,
        "公式：position_notional <= equity * risk_rate / stop_distance；止损越近，仓位上限越容易被放大。",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-22-position-budget-curve.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-22-position-budget-curve.png")


def save_portfolio_leg_comparison() -> None:
    payload = compare_portfolio(strategy_name="ma_crossover", limit=120)
    rows = payload["legs"]
    labels = [row["symbol"].replace("WEB3-DEMO", "LEG").replace("/USDT", "") for row in rows]
    returns = [float(row["total_return_pct"]) for row in rows]
    drawdowns = [float(row["max_drawdown_pct"]) for row in rows]
    x_pos = list(range(len(labels)))
    width = 0.34
    fig, ax = plt.subplots(figsize=(10.5, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar([x - width / 2 for x in x_pos], returns, width=width, color=BLUE, label="收益 %")
    ax.bar([x + width / 2 for x in x_pos], drawdowns, width=width, color=RED, label="最大回撤 %")
    ax.axhline(0, color="#94A3B8", linewidth=1)
    ax.set_xticks(x_pos)
    ax.set_xticklabels(labels)
    ax.set_ylabel("百分比")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    ax.text(
        0.01,
        -0.2,
        f"equal_weight_daily_return_sum={payload['equal_weight_daily_return_sum_pct']}%，avg_leg_return={payload['equal_weight_leg_avg_return_pct']}%。",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-22-portfolio-leg-comparison.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-22-portfolio-leg-comparison.png")


def save_risk_decision_card() -> None:
    report = build_report(short=3, long=7)
    portfolio = compare_portfolio(strategy_name="ma_crossover", limit=120)
    checks = report["risk_checks"]
    runtime = next((item for item in checks if item["phase"] == "pre_trade"), None)
    rows = [
        ("运行期拦截", f"{runtime['rule_id']} 拦截 {runtime['count']} 笔" if runtime else "无", "保留并解释，不得隐藏"),
        ("规则清单", ", ".join(report["backtest"]["risk_rules"][:3]) + " ...", "确认下单前门禁存在"),
        ("组合三腿", f"等权收益 {portfolio['equal_weight_daily_return_sum_pct']}%", "组合不是自动分散"),
        ("相关性", f"最高相关约 {max(row['correlation'] for row in portfolio['pair_correlations'])}", "高相关腿不能当独立风险"),
        ("结论", "收益下降但风险可见", "继续复核风险预算与停止线"),
    ]
    fig, ax = plt.subplots(figsize=(12, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.91, "风险审计决策卡：风控要留下可复查阻断", transform=ax.transAxes, fontsize=16, color=INK, weight="bold")
    col_x = [0.04, 0.22, 0.56]
    col_w = [0.15, 0.3, 0.36]
    headers = ["检查", "真实结果", "处理决定"]
    y0 = 0.78
    row_h = 0.12
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.075, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.012, y0 + 0.025, header, fontsize=11.2, color="#FFFFFF", weight="bold", transform=ax.transAxes)
    for i, row in enumerate(rows):
        y = y0 - (i + 1) * row_h
        fill_color = "#FFFFFF" if i % 2 == 0 else "#F8FAFC"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=fill_color, edgecolor=GRID))
            ax.text(x + 0.012, y + row_h / 2, fill(str(value), 34), fontsize=10.2, color=INK, transform=ax.transAxes, va="center")
    ax.text(
        0.04,
        0.07,
        "本章结论：风险控制不是收益优化器，而是订单进入成交前的否决权和审计记录。",
        fontsize=10.5,
        color=MUTED,
        transform=ax.transAxes,
    )
    fig.savefig(OUT / "chapter-22-risk-decision-card.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-22-risk-decision-card.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    setup_matplotlib()
    save_risk_order_gate()
    save_risk_block_matrix()
    save_position_budget_curve()
    save_portfolio_leg_comparison()
    save_risk_decision_card()


if __name__ == "__main__":
    main()
