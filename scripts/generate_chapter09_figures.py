"""Generate Chapter 09 publication figures."""

from __future__ import annotations

from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets"
FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


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
        ((80, 230, 495, 610), "趋势 SMA", "描述：价格相对窗口均线的位置\n可写：短期均线线索偏多\n禁写：趋势必然延续", BLUE),
        ((525, 230, 940, 610), "动量 RSI", "描述：近期涨跌强弱\n可写：动量进入偏热区\n禁写：超买必然下跌", ORANGE),
        ((970, 230, 1385, 610), "波动布林带", "描述：价格相对波动通道的位置\n可写：接近上轨或下轨\n禁写：上轨就是卖点", TEAL),
        ((1415, 230, 1830, 610), "风险尺度 ATR", "描述：真实波幅变化\n可写：波动环境抬升\n禁写：风险已经可控", PURPLE),
    ]
    for args in cards:
        card(draw, *args)

    draw.rounded_rectangle((330, 735, 1510, 875), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((370, 765), "停止线", font=HEAD, fill=RED)
    draw.text((370, 820), "出现“应该买入”“必然回调”“风险可控”等交易动作语言时，必须退回指标解释卡。", font=BODY, fill=INK)
    img.save(OUT / "chapter-09-indicator-boundaries.png")
    print(OUT / "chapter-09-indicator-boundaries.png")


def save_conflict_card() -> None:
    img = Image.new("RGB", (1800, 960), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 9 章实战：指标冲突解释卡", font=TITLE, fill=INK)
    draw.text((80, 116), "冲突不是噪声，而是研究材料；成熟记录应保留冲突，再交给策略规则或人工复核。", font=BODY, fill=MUTED)

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
        "短线趋势线索偏多，\n但动量偏热且价格接近上轨；\n仅可继续观察或进入策略验证。",
        font=BODY,
        fill=INK,
        spacing=9,
    )

    draw.rounded_rectangle((1250, 245, 1665, 390), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((1285, 275), "错误解释", font=HEAD, fill=RED)
    draw.text((1285, 330), "“现在应该买入”", font=BODY, fill=INK)
    draw.rounded_rectangle((1250, 455, 1665, 600), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((1285, 485), "错误解释", font=HEAD, fill=RED)
    draw.text((1285, 540), "“马上要回调”", font=BODY, fill=INK)
    draw.rounded_rectangle((1250, 665, 1665, 810), radius=18, fill="#FFF7ED", outline=ORANGE, width=4)
    draw.text((1285, 695), "下一步", font=HEAD, fill=ORANGE)
    draw.text((1285, 750), "策略规则 / 回测 / 风控另行验证", font=SMALL, fill=INK)

    arrow(draw, (1120, 512), (1250, 320), RED)
    arrow(draw, (1120, 512), (1250, 530), RED)
    arrow(draw, (1120, 512), (1250, 735), ORANGE)

    img.save(OUT / "chapter-09-conflict-card.png")
    print(OUT / "chapter-09-conflict-card.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_indicator_boundary_cards()
    save_conflict_card()


if __name__ == "__main__":
    main()
