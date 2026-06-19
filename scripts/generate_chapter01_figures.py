from __future__ import annotations

from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont

from print_figure_config import PRINT_DPI, scale


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), scale(size))


def sb(*values: int) -> tuple[int, ...]:
    return tuple(scale(value) for value in values)


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str,
    width: int = 4,
    radius: int = 18,
) -> None:
    draw.rounded_rectangle(box, radius=scale(radius), fill=fill, outline=outline, width=scale(width))


def center(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int] = (15, 32, 64),
    spacing: int = 8,
) -> None:
    lines = text.split("\n")
    heights = [draw.textbbox((0, 0), line, font=text_font)[3] for line in lines]
    total = sum(heights) + scale(spacing) * (len(lines) - 1)
    y = (box[1] + box[3] - total) / 2
    for line, height in zip(lines, heights):
        bounds = draw.textbbox((0, 0), line, font=text_font)
        x = (box[0] + box[2] - (bounds[2] - bounds[0])) / 2
        draw.text((x, y), line, font=text_font, fill=fill)
        y += height + scale(spacing)


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int] = (45, 55, 72),
    width: int = 5,
) -> None:
    line_width = scale(width)
    draw.line([start, end], fill=color, width=line_width)
    x1, y1 = start
    x2, y2 = end
    angle = math.atan2(y2 - y1, x2 - x1)
    length = scale(16)
    spread = 0.55
    points = [
        end,
        (x2 - length * math.cos(angle - spread), y2 - length * math.sin(angle - spread)),
        (x2 - length * math.cos(angle + spread), y2 - length * math.sin(angle + spread)),
    ]
    draw.polygon(points, fill=color)


def proof_boundaries() -> None:
    image = Image.new("RGB", sb(1200, 760), "#f7f9fc")
    draw = ImageDraw.Draw(image)
    draw.text(sb(60, 45), "三条证据链：谁能证明什么", font=font(42), fill="#0f1e3a")
    draw.text(
        sb(62, 100),
        "Codex、LLM 与量化验证可以串联，但不能互相替代。",
        font=font(24),
        fill="#53627a",
    )

    boxes = [sb(70, 190, 330, 340), sb(470, 190, 730, 340), sb(870, 190, 1130, 340)]
    colors = [("#e8f1ff", "#2563eb"), ("#fff4db", "#d97706"), ("#e8fbef", "#059669")]
    titles = ["Codex\n工程证据", "LLM\n语言证据", "量化验证\n统计证据"]
    subtitles = ["文件差异 / 命令 / 测试", "上下文 / JSON / 解释", "样本 / 基准 / 回测 / 风险"]

    for box, (fill, outline), title, subtitle in zip(boxes, colors, titles, subtitles):
        rounded(draw, box, fill, outline)
        center(draw, (box[0], box[1] + scale(5), box[2], box[3] - scale(35)), title, font(30))
        center(
            draw,
            (box[0], box[3] - scale(45), box[2], box[3] - scale(10)),
            subtitle,
            font(18),
            fill=(74, 85, 104),
        )

    arrow(draw, sb(335, 265), sb(465, 265))
    arrow(draw, sb(735, 265), sb(865, 265))

    rounded(draw, sb(210, 500, 990, 650), "#eef2ff", "#7c3aed")
    center(draw, sb(210, 510, 990, 590), "人的发布决定", font(32), fill=(49, 24, 87))
    center(
        draw,
        sb(210, 585, 990, 640),
        "通过 / 修改后复测 / 拒绝：只由证据合同决定，不能由语气决定",
        font(22),
        fill=(74, 85, 104),
    )
    arrow(draw, sb(600, 345), sb(600, 495), color=(124, 58, 237))
    draw.text(
        sb(120, 700),
        "读图：三类工具产生三类证据；任何一类证据都不能单独升级为交易决定。",
        font=font(22),
        fill="#334155",
    )
    image.save(OUT / "chapter-01-proof-boundaries.png", dpi=(PRINT_DPI, PRINT_DPI))


def confidence_trap() -> None:
    image = Image.new("RGB", sb(1200, 760), "#fffdf7")
    draw = ImageDraw.Draw(image)
    draw.text(sb(60, 45), "confidence 不是未来盈利概率", font=font(42), fill="#111827")
    draw.text(
        sb(62, 100),
        "同一个词在规则、LLM 和回测中含义不同，混用会制造伪确定性。",
        font=font(24),
        fill="#6b7280",
    )

    steps = [
        (50, 230, 250, 350, "模型输出\nconfidence=90", "#fef3c7", "#d97706"),
        (310, 230, 510, 350, "误读为\n90%会盈利", "#fee2e2", "#dc2626"),
        (570, 230, 770, 350, "跳过样本\n与基准检验", "#fee2e2", "#dc2626"),
        (830, 230, 1030, 350, "错误升级为\n交易决定", "#fee2e2", "#dc2626"),
    ]
    for index, (x1, y1, x2, y2, text, fill, outline) in enumerate(steps):
        box = sb(x1, y1, x2, y2)
        rounded(draw, box, fill, outline)
        center(draw, box, text, font(24))
        if index < len(steps) - 1:
            next_box = sb(*steps[index + 1][:4])
            arrow(
                draw,
                (box[2] + scale(10), box[1] + (box[3] - box[1]) // 2),
                (next_box[0] - scale(10), next_box[1] + (next_box[3] - next_box[1]) // 2),
                color=(220, 38, 38),
            )

    rounded(draw, sb(110, 500, 1090, 640), "#ecfdf5", "#059669")
    center(draw, sb(110, 510, 1090, 575), "正确处理：只把 confidence 当成表达强度", font(30), fill=(6, 95, 70))
    center(
        draw,
        sb(110, 580, 1090, 632),
        "必须补充：数据来源、样本窗口、基准、成本、回撤、失败状态",
        font(22),
        fill=(55, 65, 81),
    )
    draw.text(sb(120, 700), "读图：高置信度先触发复核，而不是触发下单。", font=font(22), fill="#374151")
    image.save(OUT / "chapter-01-confidence-trap.png", dpi=(PRINT_DPI, PRINT_DPI))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    proof_boundaries()
    confidence_trap()


if __name__ == "__main__":
    main()
