"""Generate Chapter 09 publication figures."""

from __future__ import annotations

import json
import textwrap
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from matplotlib import pyplot as plt

from dashboard.kline_analysis import analyze_candles


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets"
DATA = ROOT / "data" / "dashboard" / "market_candles.json"
FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if FONT_PATH.is_file():
        return ImageFont.truetype(str(FONT_PATH), size)
    return ImageFont.load_default()


TITLE = font(42)
HEAD = font(28)
BODY = font(23)
SMALL = font(20)

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
    sx, sy = start
    if abs(ex - sx) >= abs(ey - sy):
        sign = 1 if ex >= sx else -1
        pts = [(ex, ey), (ex - sign * 18, ey - 11), (ex - sign * 18, ey + 11)]
    else:
        sign = 1 if ey >= sy else -1
        pts = [(ex, ey), (ex - 11, ey - sign * 18), (ex + 11, ey - sign * 18)]
    draw.polygon(pts, fill=color)


def card(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], title: str, body: str, color: str) -> None:
    x1, y1, x2, _ = xy
    draw.rounded_rectangle(xy, radius=18, fill=PANEL, outline=color, width=4)
    draw.rectangle((x1, y1, x2, y1 + 64), fill=color)
    draw.text((x1 + 24, y1 + 18), title, font=HEAD, fill="#FFFFFF")
    draw.multiline_text((x1 + 24, y1 + 92), body, font=BODY, fill=INK, spacing=8)


def save_indicator_boundary_cards() -> None:
    img = Image.new("RGB", (1840, 980), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 9 章实战：指标计算与解释边界", font=TITLE, fill=INK)
    draw.text((80, 116), "指标只压缩历史价格的一个侧面；它可以描述状态，不能直接替代策略、风控和订单决定。", font=BODY, fill=MUTED)

    cards = [
        ((80, 230, 495, 610), "趋势 SMA", "描述：价格相对窗口均线的位置\n可说：短期趋势线索偏多\n边界：趋势不必然延续", BLUE),
        ((525, 230, 940, 610), "动量 RSI", "描述：近期涨跌强弱\n可说：动量进入偏热区\n边界：超买不等于必跌", ORANGE),
        ((970, 230, 1385, 610), "波动 布林带", "描述：价格相对波动通道的位置\n可说：接近上轨或下轨\n边界：上轨不是卖点保证", TEAL),
        ((1415, 230, 1830, 610), "风险尺度 ATR", "描述：真实波幅变化\n可说：波动环境抬升\n边界：风险不等于可控", PURPLE),
    ]
    for args in cards:
        card(draw, *args)

    draw.rounded_rectangle((330, 735, 1510, 875), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((370, 765), "停止线", font=HEAD, fill=RED)
    draw.text((370, 820), "出现“应该买入”“必然回调”“风险可控”等交易动作语言时，退回指标解释卡。", font=BODY, fill=INK)
    output = OUT / "chapter-09-indicator-boundaries.png"
    img.save(output)
    print(output)


def save_conflict_card() -> None:
    img = Image.new("RGB", (1800, 960), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 9 章实战：指标冲突解释卡", font=TITLE, fill=INK)
    draw.text((80, 116), "冲突不是噪声，而是研究材料；成熟记录保留冲突，再交给策略规则或人工复核。", font=BODY, fill=MUTED)

    left = [
        ((100, 245, 560, 345), "均线", "close > SMA20：短线偏多", BLUE),
        ((100, 390, 560, 490), "RSI", "RSI=78：动量偏热", ORANGE),
        ((100, 535, 560, 635), "布林带", "bbPctB=91：接近上轨", TEAL),
        ((100, 680, 560, 780), "ATR", "atrPct 抬升：波动扩大", PURPLE),
    ]
    for xy, title, body, color in left:
        draw.rounded_rectangle(xy, radius=18, fill=PANEL, outline=color, width=4)
        draw.text((xy[0] + 24, xy[1] + 22), title, font=HEAD, fill=color)
        draw.text((xy[0] + 150, xy[1] + 28), body, font=BODY, fill=INK)
        arrow(draw, (xy[2], (xy[1] + xy[3]) // 2), (700, 512), color)

    draw.rounded_rectangle((700, 395, 1120, 630), radius=20, fill="#FFFFFF", outline="#D8DEE9", width=4)
    draw.text((740, 425), "合格解释", font=HEAD, fill=INK)
    draw.multiline_text(
        (740, 485),
        "短线趋势线索偏多，\n但动量偏热且价格接近上轨，\n仅可继续观察或进入策略验证。",
        font=BODY,
        fill=INK,
        spacing=9,
    )

    draw.rounded_rectangle((1250, 245, 1665, 390), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((1285, 275), "风险解释", font=HEAD, fill=RED)
    draw.text((1285, 330), "“现在应该买入”", font=BODY, fill=INK)
    draw.rounded_rectangle((1250, 455, 1665, 600), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((1285, 485), "风险解释", font=HEAD, fill=RED)
    draw.text((1285, 540), "“马上要回调”", font=BODY, fill=INK)
    draw.rounded_rectangle((1250, 665, 1665, 810), radius=18, fill="#FFF7ED", outline=ORANGE, width=4)
    draw.text((1285, 695), "下一步", font=HEAD, fill=ORANGE)
    draw.text((1285, 750), "策略规则 / 回测 / 风控另行验证", font=SMALL, fill=INK)

    arrow(draw, (1120, 512), (1250, 320), RED)
    arrow(draw, (1120, 512), (1250, 530), RED)
    arrow(draw, (1120, 512), (1250, 735), ORANGE)

    output = OUT / "chapter-09-conflict-card.png"
    img.save(output)
    print(output)


def moving_average(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            out.append(None)
            continue
        sample = values[index + 1 - window : index + 1]
        out.append(sum(sample) / window)
    return out


def save_indicators_panel() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    candles = sorted(payload.get("candles") or [], key=lambda row: row.get("tsSec") or 0)
    analysis = analyze_candles(candles) or {}
    dates = [datetime.fromisoformat(str(row["date"])) for row in candles]
    closes = [float(row["close"]) for row in candles]
    sma20 = moving_average(closes, 20)
    bb_upper = [analysis.get("bbUpper")] * len(dates)
    bb_lower = [analysis.get("bbLower")] * len(dates)

    plt.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans", "Arial", "sans-serif"],
            "axes.unicode_minus": False,
            "figure.facecolor": "#FCFCFD",
            "axes.facecolor": "#FFFFFF",
            "axes.grid": True,
            "grid.color": "#E6E8F0",
        }
    )
    fig, axes = plt.subplots(3, 1, figsize=(13, 9), dpi=160, sharex=True, height_ratios=[2.2, 1, 1])
    axes[0].plot(dates, closes, color=BLUE, linewidth=1.8, label="收盘价")
    axes[0].plot(dates, sma20, color=TEAL, linewidth=1.5, label="SMA20")
    if analysis.get("bbUpper") and analysis.get("bbLower"):
        axes[0].plot(dates, bb_upper, color=ORANGE, linestyle="--", linewidth=1.2, label="布林上轨(最新)")
        axes[0].plot(dates, bb_lower, color=ORANGE, linestyle=":", linewidth=1.2, label="布林下轨(最新)")
    axes[0].set_title("第 9 章：固定样本上的指标同屏", loc="left", fontsize=15, fontweight="semibold", color=INK)
    axes[0].legend(frameon=False, ncol=4, loc="upper left")
    axes[0].set_ylabel("价格")

    axes[1].bar(dates, [float(row.get("volume") or 0) for row in candles], color="#94A3B8", width=0.8)
    axes[1].set_ylabel("成交量")

    latest_rsi = analysis.get("rsi")
    axes[2].axhspan(70, 100, color="#FEE2E2", alpha=0.55)
    axes[2].axhspan(0, 30, color="#DCFCE7", alpha=0.55)
    axes[2].plot(dates, [latest_rsi] * len(dates), color=PURPLE, linewidth=1.8, label=f"最新 RSI={latest_rsi}")
    axes[2].set_ylim(0, 100)
    axes[2].set_ylabel("RSI")
    axes[2].legend(frameon=False, loc="upper left")
    axes[2].set_xlabel("日期")

    for ax in axes:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.text(
        0.125,
        0.02,
        "来源：data/dashboard/market_candles.json。图中指标只描述固定样本状态，不构成交易方向或仓位建议。",
        fontsize=9.5,
        color=MUTED,
    )
    output = OUT / "chapter-09-indicators-panel.png"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    print(output)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_indicator_boundary_cards()
    save_conflict_card()
    save_indicators_panel()


if __name__ == "__main__":
    main()
