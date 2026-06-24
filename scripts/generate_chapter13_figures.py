"""Generate Chapter 13 publication figures."""

from __future__ import annotations

from pathlib import Path
import sys
import textwrap

import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets"
FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dashboard.llm_signal import SIGNAL_KEYS  # noqa: E402


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if FONT_PATH.exists():
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
    sign = 1 if ex >= sx else -1
    pts = [(ex, ey), (ex - sign * 18, ey - 11), (ex - sign * 18, ey + 11)]
    draw.polygon(pts, fill=color)


def card(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], title: str, body: str, color: str) -> None:
    x1, y1, _, _ = xy
    draw.rounded_rectangle(xy, radius=18, fill=PANEL, outline=color, width=4)
    draw.text((x1 + 24, y1 + 22), title, font=HEAD, fill=color)
    draw.multiline_text((x1 + 24, y1 + 78), wrap(body, 18), font=BODY, fill=INK, spacing=7)


def save_recon_loop() -> None:
    img = Image.new("RGB", (1840, 980), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 13 章：结构化信号勘察闭环", font=TITLE, fill=INK)
    draw.text((80, 116), "结构化字段只解决能否读取，信号仍要进入复核、实验设计和风险检查。", font=BODY, fill=MUTED)

    boxes = [
        ((90, 285, 360, 485), "上下文", "market\nkline\nevidence\nruleSignal", BLUE),
        ((455, 285, 725, 485), "模型输出", "JSON\nsignal\nscore\nlogicFlow", TEAL),
        ((820, 285, 1090, 485), "结构门禁", "枚举\n数值范围\n证据引用", ORANGE),
        ((1185, 285, 1455, 485), "人工复核", "保留\n降级\n拒绝", PURPLE),
        ((1550, 285, 1770, 485), "后续验证", "回测\n成本\n风控", RED),
    ]
    for xy, title, body, color in boxes:
        card(draw, xy, title, body, color)
    for x in (360, 725, 1090, 1455):
        arrow(draw, (x, 385), (x + 90, 385))

    draw.rounded_rectangle((310, 700, 1530, 805), radius=18, fill="#EEF2FF", outline=BLUE, width=4)
    draw.text((350, 732), "BUY / SELL 只是研究标签，不是下单动作；进入交易研究前还要经过成本、回撤和风控。", font=BODY, fill=BLUE)
    img.save(OUT / "chapter-13-recon-loop.png")
    print(OUT / "chapter-13-recon-loop.png")


def save_rejection_gate() -> None:
    img = Image.new("RGB", (1840, 1040), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 13 章：结构化信号拒绝机制", font=TITLE, fill=INK)
    draw.text((80, 116), "结构化系统不是相信模型，而是把错误输出暴露成可处理状态。", font=BODY, fill=MUTED)

    rows = [
        ("格式失败", "非 JSON、字段缺失", "解析失败并记录错误", RED),
        ("枚举失败", 'signal="BUY_NOW"', "回退规则基线", ORANGE),
        ("数值失败", "confidence=130", "降级并人工复核", PURPLE),
        ("证据失败", "引用未提供价格", "停止进入结论", RED),
        ("状态失败", "任务失败但无错误", "标记实现问题", BLUE),
    ]
    y = 235
    for title, example, action, color in rows:
        draw.rounded_rectangle((140, y, 1700, y + 110), radius=16, fill=PANEL, outline=color, width=4)
        draw.text((180, y + 35), title, font=HEAD, fill=color)
        draw.text((520, y + 37), example, font=BODY, fill=INK)
        draw.text((1110, y + 37), action, font=BODY, fill=color)
        y += 135

    img.save(OUT / "chapter-13-rejection-gate.png")
    print(OUT / "chapter-13-rejection-gate.png")


def save_signal_enum_chart() -> None:
    order = ["STRONG_BUY", "BUY", "WEAK_BUY", "HOLD", "WEAK_SELL", "SELL", "STRONG_SELL"]
    values = [2, 1, 0.5, 0, -0.5, -1, -2]
    valid = [item in SIGNAL_KEYS for item in order]
    colors = [TEAL if value > 0 else RED if value < 0 else ORANGE for value in values]

    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(11.5, 5.8), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor("#FFFFFF")
    ax.bar(order, values, color=colors, width=0.58)
    ax.axhline(0, color="#334155", linewidth=1.1)
    ax.set_title("结构化信号枚举与研究评分映射", fontsize=17, pad=14)
    ax.set_ylabel("研究评分示例", fontsize=12)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", labelrotation=22)
    for index, (value, ok) in enumerate(zip(values, valid)):
        ax.text(index, value + (0.12 if value >= 0 else -0.18), "合法" if ok else "非法", ha="center", va="bottom" if value >= 0 else "top", fontsize=9)
    ax.text(
        0.01,
        -0.24,
        "映射只用于后续研究评估；枚举合法不代表方向正确，也不代表可以交易。",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-13-signal-enum-chart.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-13-signal-enum-chart.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_recon_loop()
    save_rejection_gate()
    save_signal_enum_chart()


if __name__ == "__main__":
    main()
