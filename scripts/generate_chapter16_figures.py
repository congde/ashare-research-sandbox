"""Generate Chapter 16 publication figures."""

from __future__ import annotations

from pathlib import Path
import sys
import textwrap

import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets"
GEN = OUT / "generated"
FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from backtest.rolling.service import execute_backtest  # noqa: E402


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if FONT_PATH.exists():
        return ImageFont.truetype(str(FONT_PATH), size)
    return ImageFont.load_default()


TITLE = font(42)
HEAD = font(28)
BODY = font(23)

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
    draw.text((80, 55), "第 16 章：策略规则卡", font=TITLE, fill=INK)
    draw.text((80, 116), "研究信号进入回测前，要变成逐根 K 线可执行、可回放、可停止的规则。", font=BODY, fill=MUTED)

    boxes = [
        ((100, 260, 360, 470), "触发", "指标\n周期\n阈值\n交叉方向", BLUE),
        ((455, 260, 715, 470), "仓位", "固定仓位\n风险预算\n已有持仓检查", TEAL),
        ((810, 260, 1070, 470), "退出", "止损\n止盈\n反向信号\n时间退出", ORANGE),
        ((1165, 260, 1425, 470), "冷却", "交易后等待\n避免反复\n频率约束", PURPLE),
        ((1520, 260, 1740, 470), "停止", "缺数据\n异常波动\n风险拒绝", RED),
    ]
    for xy, title, body, color in boxes:
        card(draw, xy, title, body, color)
    for x in (360, 715, 1070, 1425):
        arrow(draw, (x, 365), (x + 95, 365))

    draw.rounded_rectangle((300, 720, 1540, 825), radius=18, fill="#EEF2FF", outline=BLUE, width=4)
    draw.text((340, 752), "模糊信号：趋势偏多；策略规则：满足交叉、持仓、成本和风控条件后才产生动作。", font=BODY, fill=BLUE)
    img.save(OUT / "chapter-16-strategy-rule-card.png")
    print(OUT / "chapter-16-strategy-rule-card.png")


def save_backtest_metrics() -> None:
    payload = execute_backtest(strategy_name="ma_crossover", limit=80)
    values = {
        "总收益": float(payload.get("total_return_pct") or 0),
        "最大回撤": -abs(float(payload.get("max_drawdown_pct") or 0)),
        "交易数": float(payload.get("total_trades") or 0),
    }

    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(10.5, 5.8), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor("#FFFFFF")
    colors = [TEAL, RED, ORANGE]
    bars = ax.bar(values.keys(), values.values(), color=colors, width=0.58)
    ax.axhline(0, color="#334155", linewidth=1.1)
    ax.set_title("ma_crossover 规则进入回测后的示例指标", fontsize=17, pad=14)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, values.values()):
        y = value + 0.5 if value >= 0 else value - 0.5
        ax.text(bar.get_x() + bar.get_width() / 2, y, f"{value:.2f}", ha="center", va="bottom" if value >= 0 else "top", fontsize=10)
    ax.text(
        0.01,
        -0.16,
        f"strategy_key=ma_crossover，limit=80，engine={payload.get('engine')}；图只说明规则可回测，不证明策略有效。",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(GEN / "chapter-16-breakout-signal-equity.png", bbox_inches="tight")
    plt.close(fig)
    print(GEN / "chapter-16-breakout-signal-equity.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    GEN.mkdir(parents=True, exist_ok=True)
    save_rule_card()
    save_backtest_metrics()


if __name__ == "__main__":
    main()
