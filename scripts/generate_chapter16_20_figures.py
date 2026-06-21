"""Generate focused Chinese teaching figures for chapter 20."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


TITLE = font(42)
HEAD = font(29)
BODY = font(24)
SMALL = font(20)

BG = "#F7F9FC"
INK = "#111827"
MUTED = "#64748B"
BLUE = "#2563EB"
TEAL = "#0F9B8E"
ORANGE = "#F59E0B"
RED = "#DC2626"
GREEN = "#15803D"
PANEL = "#FFFFFF"


def rounded_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    body: str,
    color: str,
    fill: str = PANEL,
) -> None:
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=color, width=4)
    x1, y1, _, _ = box
    draw.text((x1 + 24, y1 + 20), title, font=HEAD, fill=color)
    draw.multiline_text((x1 + 24, y1 + 72), body, font=BODY, fill=INK, spacing=8)


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


def save_overfit_pollution_gate() -> None:
    img = Image.new("RGB", (1600, 920), BG)
    draw = ImageDraw.Draw(img)
    draw.text((70, 48), "第 20 讲：过拟合与前视偏差拦截", font=TITLE, fill=INK)
    draw.text((70, 108), "先检查研究过程是否作弊，再讨论收益、Sharpe 和回撤。", font=BODY, fill=MUTED)

    rounded_box(draw, (80, 245, 350, 430), "候选策略", "规则、参数、样本\n必须先冻结", BLUE)
    rounded_box(draw, (445, 245, 715, 430), "污染检查", "危险导入\nshift(-n)\n未来标签", RED, "#FEF2F2")
    rounded_box(draw, (810, 245, 1080, 430), "试验日志", "参数次数\n淘汰理由\n时间切分", ORANGE, "#FFF7ED")
    rounded_box(draw, (1175, 190, 1505, 355), "进入滚动回测", "无前视\n日志完整\n口径可复查", GREEN, "#ECFDF5")
    rounded_box(draw, (1175, 465, 1505, 630), "拒绝或重建样本", "未来信息\n窥探样本\n记录缺失", RED, "#FEF2F2")

    arrow(draw, (350, 335), (445, 335))
    arrow(draw, (715, 335), (810, 335))
    arrow(draw, (1080, 310), (1175, 275), GREEN)
    arrow(draw, (1080, 370), (1175, 545), RED)

    draw.rounded_rectangle((190, 705, 1410, 845), radius=18, fill="#FFFFFF", outline=TEAL, width=4)
    draw.text((235, 730), "读图要点", font=HEAD, fill=TEAL)
    draw.text((235, 785), "若策略读取未来收益或只保留多次尝试后的赢家，绩效指标再漂亮也不能发布为研究结论。", font=BODY, fill=INK)
    draw.text((235, 818), "被拒绝的样本同样是证据：它说明系统没有让作弊路径继续前进。", font=SMALL, fill=MUTED)

    img.save(OUT / "chapter-20-overfit-pollution-gate.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_overfit_pollution_gate()
    print(OUT / "chapter-20-overfit-pollution-gate.png")


if __name__ == "__main__":
    main()
