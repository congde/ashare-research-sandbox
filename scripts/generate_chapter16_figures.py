"""Generate Chapter 16 publication figures."""

from __future__ import annotations

from pathlib import Path
import sys
import textwrap

from PIL import Image, ImageDraw, ImageFont

try:
    import matplotlib.pyplot as plt
except ModuleNotFoundError:  # pragma: no cover - fallback used in lean editing envs
    plt = None


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets"
GEN = OUT / "generated"
FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from backtest.rolling.engine import run_backtest  # noqa: E402
from backtest.rolling.models import BacktestConfig  # noqa: E402
from backtest.rolling.registry import get_strategy  # noqa: E402
from backtest.rolling.service import execute_backtest  # noqa: E402


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if FONT_PATH.exists():
        return ImageFont.truetype(str(FONT_PATH), size)
    return ImageFont.load_default()


TITLE = font(42)
HEAD = font(28)
BODY = font(23)
SMALL = font(18)

BG = "#F7F9FC"
INK = "#111827"
MUTED = "#64748B"
BLUE = "#2563EB"
TEAL = "#0F9B8E"
ORANGE = "#F59E0B"
RED = "#DC2626"
PURPLE = "#7C3AED"
PANEL = "#FFFFFF"


def wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=True))


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str = MUTED) -> None:
    draw.line([start, end], fill=color, width=5)
    ex, ey = end
    sx, _ = start
    sign = 1 if ex >= sx else -1
    pts = [(ex, ey), (ex - sign * 18, ey - 11), (ex - sign * 18, ey + 11)]
    draw.polygon(pts, fill=color)


def card(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], title: str, body: str, color: str) -> None:
    x1, y1, _, _ = xy
    draw.rounded_rectangle(xy, radius=18, fill=PANEL, outline=color, width=4)
    draw.text((x1 + 24, y1 + 22), title, font=HEAD, fill=color)
    draw.multiline_text((x1 + 24, y1 + 78), wrap(body, 17), font=BODY, fill=INK, spacing=7)


def save_rule_card() -> None:
    img = Image.new("RGB", (1840, 980), BG)
    draw = ImageDraw.Draw(img)

    boxes = [
        ((100, 205, 360, 415), "触发", "指标\n周期\n阈值\n交叉方向", BLUE),
        ((455, 205, 715, 415), "仓位", "固定仓位\n风险预算\n已有持仓检查", TEAL),
        ((810, 205, 1070, 415), "退出", "止损\n止盈\n反向信号\n时间退出", ORANGE),
        ((1165, 205, 1425, 415), "冷却", "交易后等待\n避免反复\n频率约束", PURPLE),
        ((1520, 205, 1740, 415), "停止", "缺数据\n异常波动\n风险拒绝", RED),
    ]
    for xy, title, body, color in boxes:
        card(draw, xy, title, body, color)
    for x in (360, 715, 1070, 1425):
        arrow(draw, (x, 310), (x + 95, 310))

    draw.rounded_rectangle((300, 660, 1540, 765), radius=18, fill="#EEF2FF", outline=BLUE, width=4)
    draw.text((340, 692), "模糊信号：趋势偏多；策略规则：满足交叉、持仓、成本和风控条件后才产生动作。", font=BODY, fill=BLUE)
    img.save(OUT / "chapter-16-strategy-rule-card.png")
    print(OUT / "chapter-16-strategy-rule-card.png")


def save_backtest_metrics() -> None:
    payload = execute_backtest(strategy_name="ma_crossover", limit=120)
    equity = payload.get("equity_curve", [])
    trades = payload.get("trades", [])
    signals = payload.get("candle_signals", [])

    img = Image.new("RGB", (1840, 980), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 50), "ma_crossover 规则进入回测后的示例指标", font=TITLE, fill=INK)
    draw.text((80, 108), "权益、回撤、交易点和指标摘要放在同一张证据面板中；它说明规则可回测，不证明策略有效。", font=BODY, fill=MUTED)

    left, right = 95, 1260
    top, mid, bottom = 190, 470, 710
    width = right - left

    def x_at(pos: int, total: int) -> int:
        if total <= 1:
            return left
        return int(left + width * pos / (total - 1))

    def y_at(value: float, low: float, high: float, y1: int, y2: int) -> int:
        if high == low:
            return (y1 + y2) // 2
        return int(y2 - (value - low) * (y2 - y1) / (high - low))

    def panel(box: tuple[int, int, int, int], title: str) -> None:
        draw.rounded_rectangle(box, radius=18, fill=PANEL, outline="#CBD5E1", width=2)
        draw.text((box[0] + 22, box[1] + 18), title, font=HEAD, fill=INK)

    panel((70, 165, 1300, 430), "权益曲线")
    panel((70, 455, 1300, 720), "收盘价、入场与出场")

    equities = [float(row["equity"]) for row in equity]
    closes = [float(row["close"]) for row in equity]
    drawdowns = [abs(float(row.get("drawdown", 0.0))) for row in equity]
    total = len(equity)

    eq_low, eq_high = min(equities + [100.0]), max(equities + [100.0])
    eq_low -= max(0.5, (eq_high - eq_low) * 0.12)
    eq_high += max(0.5, (eq_high - eq_low) * 0.12)
    eq_points = [(x_at(i, total), y_at(v, eq_low, eq_high, top + 75, mid - 25)) for i, v in enumerate(equities)]
    if len(eq_points) > 1:
        draw.line(eq_points, fill=TEAL, width=5)
    baseline_y = y_at(100.0, eq_low, eq_high, top + 75, mid - 25)
    draw.line((left, baseline_y, right, baseline_y), fill="#CBD5E1", width=2)
    draw.text((left, top + 45), "equity", font=SMALL, fill=TEAL)

    dd_high = max(drawdowns + [1.0])
    for i, dd in enumerate(drawdowns):
        x = x_at(i, total)
        y = y_at(dd, 0.0, dd_high, top + 75, mid - 25)
        draw.line((x, mid - 25, x, y), fill="#FCA5A5", width=2)
    draw.text((left + 160, top + 45), "drawdown", font=SMALL, fill=RED)

    close_low, close_high = min(closes), max(closes)
    close_points = [(x_at(i, total), y_at(v, close_low, close_high, mid + 75, bottom - 25)) for i, v in enumerate(closes)]
    if len(close_points) > 1:
        draw.line(close_points, fill=BLUE, width=4)
    idx_to_pos = {int(row["idx"]): pos for pos, row in enumerate(equity)}
    close_by_idx = {int(row["idx"]): float(row["close"]) for row in equity}
    for trade in trades:
        entry_idx = int(trade.get("entry_idx", trade.get("entryIdx", -1))) if isinstance(trade, dict) else int(trade.entry_idx)
        exit_idx = int(trade.get("exit_idx", trade.get("exitIdx", -1))) if isinstance(trade, dict) else int(trade.exit_idx)
        for idx, label, color, marker in ((entry_idx, "入场", TEAL, "up"), (exit_idx, "出场", RED, "down")):
            if idx not in idx_to_pos:
                continue
            x = x_at(idx_to_pos[idx], total)
            y = y_at(close_by_idx[idx], close_low, close_high, mid + 75, bottom - 25)
            if marker == "up":
                draw.polygon([(x, y - 16), (x - 14, y + 12), (x + 14, y + 12)], fill=color)
            else:
                draw.polygon([(x, y + 16), (x - 14, y - 12), (x + 14, y - 12)], fill=color)
            draw.text((x + 12, y - 18), label, font=SMALL, fill=color)
    draw.text((left, mid + 45), "close", font=SMALL, fill=BLUE)

    metric_x = 1340
    cards = [
        ("总收益", f"{float(payload.get('total_return_pct') or 0):.2f}%", TEAL if float(payload.get("total_return_pct") or 0) >= 0 else RED),
        ("最大回撤", f"{float(payload.get('max_drawdown_pct') or 0):.2f}%", RED),
        ("交易数", str(int(payload.get("total_trades") or 0)), ORANGE),
        ("胜率", f"{float(payload.get('win_rate') or 0):.1f}%", PURPLE),
    ]
    for i, (label, value, color) in enumerate(cards):
        y = 185 + i * 132
        draw.rounded_rectangle((metric_x, y, 1745, y + 102), radius=16, fill="#FFFFFF", outline=color, width=3)
        draw.text((metric_x + 24, y + 18), label, font=BODY, fill=MUTED)
        draw.text((metric_x + 24, y + 50), value, font=HEAD, fill=color)

    note = f"strategy_key=ma_crossover，limit=120，engine={payload.get('engine')}；信号数={len(signals)}，交易数={len(trades)}。"
    draw.text((90, 765), note, font=BODY, fill=MUTED)
    draw.text((90, 805), "读图重点：先看规则是否能留下权益、回撤、交易和信号证据，再进入收益解释。", font=BODY, fill=INK)

    img.save(GEN / "chapter-16-breakout-signal-equity.png")
    print(GEN / "chapter-16-breakout-signal-equity.png")


def _synthetic_candles(closes: list[float]) -> list[dict]:
    candles: list[dict] = []
    for idx, close in enumerate(closes):
        candles.append(
            {
                "tsSec": 1_700_000_000 + idx * 86_400,
                "date": f"2024-01-{idx + 1:02d}",
                "open": close,
                "close": close,
                "high": round(close * 1.01, 6),
                "low": round(close * 0.99, 6),
                "volume": 1000.0,
                "turnover": close * 1000,
            }
        )
    return candles


def _golden_cross_payload() -> tuple[list[dict], list[dict], list[dict]]:
    closes = [100 - i * 0.5 for i in range(25)] + [88 + i * 1.2 for i in range(20)]
    candles = _synthetic_candles(closes)
    strategy = get_strategy("ma_crossover")
    params = {"fast_period": 5, "slow_period": 10, "entry_threshold": 25}
    config = BacktestConfig(min_context=15, commission_pct=0.1)
    trades, equity, signals = run_backtest(candles, strategy, params, config)
    return signals, trades, equity


def save_golden_cross_signal_chart() -> None:
    signals, _trades, _equity = _golden_cross_payload()
    xs = list(range(len(signals)))
    closes = [float(row["close"]) for row in signals]
    scores = [float(row["score"]) for row in signals]
    long_x = [idx for idx, row in enumerate(signals) if row["action"] == "LONG"]
    long_y = [closes[idx] for idx in long_x]

    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11.2, 7.2), dpi=160, sharex=True, height_ratios=[2, 1])
    fig.patch.set_facecolor(BG)
    ax1.set_facecolor("#FFFFFF")
    ax2.set_facecolor("#FFFFFF")
    ax1.plot(xs, closes, color=BLUE, linewidth=2.2, label="close")
    ax1.scatter(long_x, long_y, color=TEAL, s=75, marker="^", label="LONG")
    ax1.set_ylabel("收盘价")
    ax1.grid(color="#E5E7EB", linewidth=0.8)
    ax1.legend(loc="upper left", frameon=False)
    ax1.spines[["top", "right"]].set_visible(False)

    ax2.bar(xs, scores, color=[TEAL if value >= 25 else ORANGE if value > 0 else RED if value < 0 else "#CBD5E1" for value in scores], width=0.75)
    ax2.axhline(25, color="#334155", linestyle="--", linewidth=1.0, label="entry_threshold=25")
    ax2.set_ylabel("信号分数")
    ax2.set_xlabel("合成 K 线序号")
    ax2.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.legend(loc="upper left", frameon=False)
    ax2.text(
        0.01,
        -0.34,
        "合成样本来自 tests/test_qbot_strategies.py：先下跌后上涨，金叉产生 LONG。",
        transform=ax2.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-16-golden-cross-signal.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-16-golden-cross-signal.png")


def save_action_distribution_chart() -> None:
    signals, trades, equity = _golden_cross_payload()
    counts: dict[str, int] = {}
    for row in signals:
        action = str(row["action"])
        counts[action] = counts.get(action, 0) + 1

    img = Image.new("RGB", (1840, 980), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 50), "合成样本中的动作、持仓与分数门禁", font=TITLE, fill=INK)
    draw.text((80, 108), "先看价格路径上的 LONG/EXIT，再看动作、持仓、分数三条轨道是否互相对齐。", font=BODY, fill=MUTED)
    draw.rounded_rectangle((1260, 48, 1510, 102), radius=14, fill="#EFF6FF", outline=BLUE, width=2)
    draw.text((1280, 61), f"WAIT {counts.get('WAIT', 0)} / LONG {counts.get('LONG', 0)}", font=SMALL, fill=BLUE)
    draw.rounded_rectangle((1535, 48, 1765, 102), radius=14, fill="#ECFDF5", outline=TEAL, width=2)
    draw.text((1555, 61), f"交易 {len(trades)}  权益 {equity[-1]['equity']:.2f}", font=SMALL, fill=TEAL)

    chart = (70, 165, 1770, 520)
    lane = (70, 555, 1770, 835)
    left, right = 150, 1690
    top, bottom = 235, 475
    width = right - left
    total = len(signals)
    closes = [float(row["close"]) for row in signals]
    scores = [float(row["score"]) for row in signals]

    def x_at(pos: int) -> int:
        return int(left + width * pos / max(1, total - 1))

    def y_at(value: float, low: float, high: float, y1: int, y2: int) -> int:
        if high == low:
            return (y1 + y2) // 2
        return int(y2 - (value - low) * (y2 - y1) / (high - low))

    draw.rounded_rectangle(chart, radius=18, fill=PANEL, outline="#D7DEE8", width=2)
    draw.rounded_rectangle(lane, radius=18, fill=PANEL, outline="#D7DEE8", width=2)
    draw.text((110, 188), "价格路径与交易标记", font=HEAD, fill=INK)
    close_low, close_high = min(closes), max(closes)

    for frac in (0.25, 0.5, 0.75):
        y = int(top + (bottom - top) * frac)
        draw.line((left, y, right, y), fill="#E5EAF2", width=1)
    for pos in range(0, total, 5):
        x = x_at(pos)
        draw.line((x, bottom, x, bottom + 10), fill="#CBD5E1", width=2)
        draw.text((x - 8, bottom + 18), str(pos), font=SMALL, fill=MUTED)

    close_points = [(x_at(i), y_at(v, close_low, close_high, top, bottom)) for i, v in enumerate(closes)]
    if len(close_points) > 1:
        draw.line(close_points, fill=BLUE, width=5)

    idx_to_pos = {int(row["idx"]): pos for pos, row in enumerate(signals)}
    close_by_idx = {int(row["idx"]): float(row["close"]) for row in signals}
    for trade in trades:
        entry_idx = int(trade.entry_idx)
        exit_idx = int(trade.exit_idx)
        if entry_idx not in idx_to_pos or exit_idx not in idx_to_pos:
            continue
        x1 = x_at(idx_to_pos[entry_idx])
        x2 = x_at(idx_to_pos[exit_idx])
        draw.rounded_rectangle((x1, top + 4, x2, bottom - 4), radius=10, fill="#E7F8EF")
        draw.line(close_points, fill=BLUE, width=5)

    for pos, row in enumerate(signals):
        if row["action"] != "LONG":
            continue
        x = x_at(pos)
        y = y_at(float(row["close"]), close_low, close_high, top, bottom)
        draw.ellipse((x - 18, y - 18, x + 18, y + 18), fill=TEAL)
        draw.polygon([(x, y - 12), (x - 9, y + 8), (x + 9, y + 8)], fill="#FFFFFF")
        draw.text((x + 18, y - 34), "LONG", font=SMALL, fill=TEAL)

    for trade in trades:
        entry_idx = int(trade.entry_idx)
        exit_idx = int(trade.exit_idx)
        if entry_idx in idx_to_pos and exit_idx in idx_to_pos:
            x1 = x_at(idx_to_pos[entry_idx])
            x2 = x_at(idx_to_pos[exit_idx])
            y_exit = y_at(close_by_idx[exit_idx], close_low, close_high, top, bottom)
            draw.ellipse((x2 - 18, y_exit - 18, x2 + 18, y_exit + 18), fill=RED)
            draw.polygon([(x2, y_exit + 12), (x2 - 9, y_exit - 8), (x2 + 9, y_exit - 8)], fill="#FFFFFF")
            draw.text((x2 + 18, y_exit - 8), "EXIT", font=SMALL, fill=RED)

    draw.text((left, bottom + 52), "K 线序号", font=SMALL, fill=MUTED)
    draw.text((110, 580), "三条证据轨道", font=HEAD, fill=INK)
    lanes = [
        ("动作轨道", 650, "WAIT 是细点，LONG 是绿色节点", ORANGE),
        ("持仓轨道", 725, "绿色区间表示持有多头", TEAL),
        ("分数门禁", 800, "柱越过虚线才满足入场阈值", PURPLE),
    ]
    for label, y, hint, color in lanes:
        draw.text((110, y - 28), label, font=BODY, fill=INK)
        draw.text((245, y - 25), hint, font=SMALL, fill=MUTED)
        draw.line((left, y, right, y), fill="#D7DEE8", width=2)

    action_y, position_y, score_base_y = 650, 725, 800
    for pos, row in enumerate(signals):
        x = x_at(pos)
        if row["action"] == "LONG":
            draw.ellipse((x - 12, action_y - 12, x + 12, action_y + 12), fill=TEAL)
        else:
            draw.ellipse((x - 4, action_y - 4, x + 4, action_y + 4), fill="#FBBF24")

    for trade in trades:
        x1 = x_at(idx_to_pos[int(trade.entry_idx)])
        x2 = x_at(idx_to_pos[int(trade.exit_idx)])
        draw.rounded_rectangle((x1, position_y - 18, x2, position_y + 18), radius=10, fill="#BBF7D0", outline=TEAL, width=2)
        draw.text((x2 + 18, position_y - 15), f"{trade.bars_held} 根 / {trade.exit_reason}", font=SMALL, fill=TEAL)

    score_low, score_high = min(scores + [25.0]), max(scores + [25.0])
    score_top, score_bottom = 760, 820
    threshold_y = y_at(25.0, score_low, score_high, score_top, score_bottom)
    draw.line((left, threshold_y, right, threshold_y), fill="#334155", width=2)
    draw.text((right - 160, threshold_y - 28), "threshold=25", font=SMALL, fill="#334155")
    for pos, score in enumerate(scores):
        x = x_at(pos)
        y = y_at(score, score_low, score_high, score_top, score_bottom)
        color = TEAL if score >= 25 else "#CBD5E1"
        draw.rounded_rectangle((x - 5, min(y, score_base_y), x + 5, max(y, score_base_y)), radius=3, fill=color)

    draw.text((100, 890), "读图顺序：1. 找到 LONG 节点；2. 检查持仓区间；3. 对照分数是否越过 threshold=25。", font=BODY, fill=INK)
    draw.text((100, 930), "这张图用于复核规则触发、持仓和分数门禁，不用于证明策略收益。", font=BODY, fill=MUTED)

    img.save(OUT / "chapter-16-action-distribution.png")
    print(OUT / "chapter-16-action-distribution.png")


def save_cost_sensitivity_chart() -> None:
    presets = [
        ("0", 0.00, 0.0),
        ("1", 0.02, 2.0),
        ("2", 0.05, 5.0),
        ("3", 0.10, 10.0),
        ("4", 0.20, 20.0),
        ("5", 0.35, 35.0),
    ]
    returns: list[float] = []
    drawdowns: list[float] = []
    trade_counts: list[int] = []
    for _label, commission, slippage_bps in presets:
        payload = execute_backtest(
            strategy_name="ma_crossover",
            limit=120,
            cost_preset=None,
            commission_pct=commission,
            slippage_bps=slippage_bps,
        )
        returns.append(float(payload.get("total_return_pct") or 0))
        drawdowns.append(abs(float(payload.get("max_drawdown_pct") or 0)))
        trade_counts.append(int(payload.get("total_trades") or 0))

    labels = [item[0] for item in presets]
    x = list(range(len(labels)))
    fig, ax1 = plt.subplots(figsize=(11.4, 6.2), dpi=160)
    fig.patch.set_facecolor(BG)
    ax1.set_facecolor("#FFFFFF")
    ax1.plot(x, returns, color=TEAL, marker="o", linewidth=2.4, label="总收益%")
    ax1.plot(x, drawdowns, color=RED, marker="s", linewidth=2.4, label="最大回撤%")
    ax1.axhline(0, color="#334155", linewidth=1.0)
    ax1.set_xticks(x, labels)
    ax1.set_xlabel("成本压力档位")
    ax1.set_ylabel("百分比")
    ax1.set_title("成本敏感性曲线：同一规则在不同手续费与滑点下的路径变化", fontsize=15, pad=14)
    ax1.grid(color="#E5E7EB", linewidth=0.8)
    ax1.spines[["top", "right"]].set_visible(False)

    ax2 = ax1.twinx()
    ax2.plot(x, trade_counts, color=ORANGE, marker="^", linewidth=1.8, linestyle="--", label="交易数")
    ax2.set_ylabel("交易数")
    ax2.spines[["top"]].set_visible(False)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", frameon=False)
    for idx, (commission, slippage) in enumerate((item[1], item[2]) for item in presets):
        ax1.text(idx, min(returns + drawdowns) - 1.5, f"{commission:.2f}%\n{slippage:.0f}bps", ha="center", va="top", fontsize=8, color=MUTED)
    ax1.text(
        0.01,
        -0.23,
        "横轴下方依次为 commission_pct / slippage_bps；同一规则必须先固定成本口径，再解释收益和回撤。",
        transform=ax1.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-16-cost-sensitivity.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-16-cost-sensitivity.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    GEN.mkdir(parents=True, exist_ok=True)
    save_rule_card()
    save_golden_cross_signal_chart()
    save_action_distribution_chart()
    save_cost_sensitivity_chart()
    save_backtest_metrics()


if __name__ == "__main__":
    main()
