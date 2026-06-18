"""Render 图 21-5 — factor mining industry pipeline vs teaching sandbox."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "chapter-21-factor-mining-pipeline.png"

FONT_REGULAR = Path("C:/Windows/Fonts/msyh.ttc")
FONT_BOLD = Path("C:/Windows/Fonts/msyhbd.ttc")


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    if path.exists():
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _center(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fnt: ImageFont.ImageFont, fill: str) -> None:
    x, y = xy
    bbox = draw.textbbox((0, 0), text, font=fnt)
    draw.text((x - (bbox[2] - bbox[0]) / 2, y), text, font=fnt, fill=fill)


def _arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], fill: str = "#334155") -> None:
    draw.line([start, end], fill=fill, width=4)
    x1, y1 = start
    x2, y2 = end
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 >= x1 else -1
        points = [(x2, y2), (x2 - 14 * direction, y2 - 7), (x2 - 14 * direction, y2 + 7)]
    else:
        direction = 1 if y2 >= y1 else -1
        points = [(x2, y2), (x2 - 7, y2 - 14 * direction), (x2 + 7, y2 - 14 * direction)]
    draw.polygon(points, fill=fill)


def _box(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    *,
    fill: str,
    outline: str,
    title: str,
    subtitle: str,
    text_fill: str,
    dashed: bool = False,
) -> None:
    if dashed:
        x0, y0, x1, y1 = rect
        for edge in (
            [(x0, y0, x1, y0), (x0, y1, x1, y1)],
            [(x0, y0, x0, y1), (x1, y0, x1, y1)],
        ):
            for seg in edge:
                draw.line(seg, fill=outline, width=2)
        draw.rectangle(rect, fill=fill)
    else:
        draw.rounded_rectangle(rect, radius=14, fill=fill, outline=outline, width=3)
    cx = (rect[0] + rect[2]) // 2
    _center(draw, (cx, rect[1] + 34), title, _font(20, True), text_fill)
    _center(draw, (cx, rect[1] + 68), subtitle, _font(15), "#1f2937")


def render(path: Path = OUT) -> Path:
    image = Image.new("RGB", (1200, 680), "#f7f9fc")
    draw = ImageDraw.Draw(image)

    draw.text((48, 36), "图 21-5  因子挖掘：业界流水线与本沙箱覆盖范围", font=_font(28, True), fill="#14213d")
    draw.text(
        (48, 82),
        "实线框 = 业界常见工序；橙色虚线框 = src/factor_mining/ 已实现子集",
        font=_font(16),
        fill="#4b5563",
    )

    industry = [
        ((48, 130, 248, 250), "#dbeafe", "#2563eb", "数据层", "价量 / 基本面 / 另类", "#1e3a8a"),
        ((278, 130, 478, 250), "#dcfce7", "#16a34a", "搜索层", "GP / ML / LLM", "#14532d"),
        ((508, 130, 708, 250), "#fef3c7", "#d97706", "评估层", "IC · 分层 · 换手 · 去相关", "#78350f"),
        ((738, 130, 938, 250), "#ede9fe", "#7c3aed", "落地层", "walk-forward · 组合 · 执行", "#4c1d95"),
    ]
    for rect, fill, outline, title, subtitle, text_fill in industry:
        _box(draw, rect, fill=fill, outline=outline, title=title, subtitle=subtitle, text_fill=text_fill)

    _arrow(draw, (248, 190), (278, 190))
    _arrow(draw, (478, 190), (508, 190))
    _arrow(draw, (708, 190), (738, 190))

    sandbox = [
        ((120, 320, 320, 430), "#fff7ed", "#ea580c", "特征矩阵", "12 维 OHLCV+指标", "#9a3412"),
        ((380, 320, 580, 430), "#fff7ed", "#ea580c", "GP / ML 搜索", "训练段 70%", "#9a3412"),
        ((640, 320, 840, 430), "#fff7ed", "#ea580c", "时序 IC", "测试段 + overfit_gap", "#9a3412"),
        ((900, 320, 1100, 430), "#fff7ed", "#ea580c", "mined_factor", "回测 PnL 证据", "#9a3412"),
    ]
    for rect, fill, outline, title, subtitle, text_fill in sandbox:
        _box(
            draw,
            rect,
            fill=fill,
            outline=outline,
            title=title,
            subtitle=subtitle,
            text_fill=text_fill,
            dashed=True,
        )

    _arrow(draw, (320, 375), (380, 375), fill="#ea580c")
    _arrow(draw, (580, 375), (640, 375), fill="#ea580c")
    _arrow(draw, (840, 375), (900, 375), fill="#ea580c")

    draw.text((48, 460), "未纳入沙箱（业界常见、本课仅作对照）", font=_font(18, True), fill="#7f1d1d")
    gaps = "截面 IC · 行业中性 · 万级 fields · PnL 相关去重 · 多年 walk-forward"
    draw.text((48, 492), gaps, font=_font(16), fill="#991b1b")

    draw.rounded_rectangle((48, 540, 1152, 630), radius=12, fill="#fee2e2", outline="#dc2626", width=2)
    _center(
        draw,
        (600, 562),
        "停止线：训练 IC 高而测试 IC 低 → 不得外推；IC 高而 PnL 差 → 须查换手与成本",
        _font(17, True),
        "#7f1d1d",
    )
    _center(draw, (600, 596), "交付：因子挖掘报告 = 表达式 + 双段 IC + mined_factor 回测 + 与 compare 对照", _font(15), "#1f2937")

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)
    return path


if __name__ == "__main__":
    out = render()
    print(out)
