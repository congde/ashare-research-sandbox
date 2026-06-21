"""Generate focused Chinese teaching figures for chapters 14 and 15."""

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


def save_pollution_gate() -> None:
    img = Image.new("RGB", (1600, 920), BG)
    draw = ImageDraw.Draw(img)
    draw.text((70, 48), "第 14 讲：LLM 污染拦截路径", font=TITLE, fill=INK)
    draw.text((70, 108), "幻觉、提示泄漏和未来信息不是评分扣分项，而是进入研究结论前必须拦下的关键失败。", font=BODY, fill=MUTED)

    rounded_box(draw, (85, 245, 365, 425), "输入上下文", "行情、证据、规则信号\n必须带来源和时间", BLUE)
    rounded_box(draw, (470, 245, 750, 425), "污染注入", "缺失价格\n越权指令\n未来标签", ORANGE, "#FFF7ED")
    rounded_box(draw, (855, 245, 1135, 425), "门禁检查", "字段缺失\n禁用词\n可见时间", TEAL)
    rounded_box(draw, (1240, 190, 1515, 355), "通过", "只作为研究解释\n继续保留证据链", GREEN, "#ECFDF5")
    rounded_box(draw, (1240, 465, 1515, 630), "停止", "标记关键失败\n修改后复测", RED, "#FEF2F2")

    arrow(draw, (365, 335), (470, 335))
    arrow(draw, (750, 335), (855, 335))
    arrow(draw, (1135, 315), (1240, 275), GREEN)
    arrow(draw, (1135, 365), (1240, 545), RED)

    draw.rounded_rectangle((210, 710, 1390, 835), radius=18, fill="#EEF2FF", outline=BLUE, width=4)
    draw.text((250, 733), "复核要点", font=HEAD, fill=BLUE)
    draw.text((250, 785), "关键失败率 = 未拦截关键失败数 / 污染样本数；只要未拦截关键失败出现，就不能用平均分掩盖。", font=BODY, fill=INK)

    img.save(OUT / "chapter-14-pollution-gate.png")


def save_scoring_rubric() -> None:
    img = Image.new("RGB", (1600, 920), BG)
    draw = ImageDraw.Draw(img)
    draw.text((70, 48), "第 15 讲：LLM 信号评分规程", font=TITLE, fill=INK)
    draw.text((70, 108), "样本和权重要先冻结，再比较提示词、模型或上下文版本。关键失败不能被平均分抵消。", font=BODY, fill=MUTED)

    rounded_box(draw, (70, 240, 345, 430), "固定样本", "正常样本\n边界样本\n失败样本", BLUE)
    rounded_box(draw, (430, 240, 705, 430), "固定权重", "结构 20\n证据 25\n边界 20", TEAL)
    rounded_box(draw, (790, 240, 1065, 430), "逐条评分", "方向稳定 15\n解释质量 20\n人工备注", ORANGE)
    rounded_box(draw, (1150, 190, 1495, 355), "放行候选", "分数达标\n无关键失败\n证据可追溯", GREEN, "#ECFDF5")
    rounded_box(draw, (1150, 465, 1495, 630), "拒绝或复测", "补造价格\n使用未来信息\n越权下单建议", RED, "#FEF2F2")

    arrow(draw, (345, 335), (430, 335))
    arrow(draw, (705, 335), (790, 335))
    arrow(draw, (1065, 310), (1150, 275), GREEN)
    arrow(draw, (1065, 365), (1150, 545), RED)

    draw.rounded_rectangle((190, 700, 1410, 845), radius=18, fill="#FFFFFF", outline=TEAL, width=4)
    draw.text((235, 724), "评分公式", font=HEAD, fill=TEAL)
    draw.text(
        (235, 780),
        "score = 20I结构 + 25I证据 + 20I边界 + 15I稳定 + 20I解释；pass = score ≥ 75 且没有关键失败。",
        font=BODY,
        fill=INK,
    )
    draw.text((235, 815), "分数说明输出过程是否可靠，不直接证明交易收益。", font=SMALL, fill=MUTED)

    img.save(OUT / "chapter-15-scoring-rubric.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_pollution_gate()
    save_scoring_rubric()
    for name in ("chapter-14-pollution-gate.png", "chapter-15-scoring-rubric.png"):
        print(OUT / name)


if __name__ == "__main__":
    main()
