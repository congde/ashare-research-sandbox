"""Generate Chapter 17 publication figures."""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from backtest.runner import load_prices, prices_to_candles  # noqa: E402
from paths import DATA_DIR  # noqa: E402
from strategy_engine.backtest import BacktestEngine  # noqa: E402
from strategy_engine.strategies.ma_crossover import make_ma_crossover_strategy  # noqa: E402


def save_ma_crossover_trades() -> None:
    prices = load_prices(DATA_DIR / "prices.csv")
    candles = prices_to_candles(prices[:80])
    engine = BacktestEngine(strategy_fn=make_ma_crossover_strategy(3, 7))
    result = engine.run(candles, symbol="WEB3-DEMO/USDT", timeframe="1day")
    dates = [c.ts for c in candles]
    closes = [float(c.close) for c in candles]
    equity_dates = [item[0] for item in result.equity_curve]
    equity = [float(item[1]) for item in result.equity_curve]

    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), dpi=160, sharex=True)
    fig.patch.set_facecolor("#F7F9FC")
    for ax in axes:
        ax.set_facecolor("#FFFFFF")
        ax.grid(color="#E5E7EB", linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].plot(dates, closes, color="#2563EB", linewidth=1.8, label="收盘价")
    for trade in result.trades:
        marker = "^" if trade.side == "buy" else "v"
        color = "#0F9B8E" if trade.side == "buy" else "#DC2626"
        axes[0].scatter(trade.ts, float(trade.price), marker=marker, color=color, s=58)
    axes[0].set_title("双均线策略的交易触发点", fontsize=16)
    axes[0].legend(frameon=False)
    axes[1].plot(equity_dates, equity, color="#F59E0B", linewidth=1.8)
    axes[1].set_title("事件驱动回测权益曲线", fontsize=16)
    axes[1].set_ylabel("权益")
    axes[1].text(
        0.01,
        -0.26,
        f"short=3, long=7；trades={len(result.trades)}；图用于实现复核，不证明策略有效。",
        transform=axes[1].transAxes,
        fontsize=10,
        color="#64748B",
    )
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "chapter-17-ma-crossover-trades.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-17-ma-crossover-trades.png")


def main() -> None:
    save_ma_crossover_trades()


if __name__ == "__main__":
    main()
