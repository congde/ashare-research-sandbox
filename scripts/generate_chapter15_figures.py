"""Generate Chapter 15 publication figures."""

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

from factor_mining.evaluate import evaluate_factor  # noqa: E402


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
GREEN = "#15803D"
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


def card(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], title: str, body: str, color: str, fill: str = PANEL) -> None:
    x1, y1, _, _ = xy
    draw.rounded_rectangle(xy, radius=18, fill=fill, outline=color, width=4)
    draw.text((x1 + 24, y1 + 22), title, font=HEAD, fill=color)
    draw.multiline_text((x1 + 24, y1 + 78), wrap(body, 17), font=BODY, fill=INK, spacing=7)


def save_scoring_rubric() -> None:
    img = Image.new("RGB", (1840, 980), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 15 章：LLM 信号评分规程", font=TITLE, fill=INK)
    draw.text((80, 116), "样本和权重先冻结，再比较提示词、模型或上下文版本；关键失败不被平均分抵消。", font=BODY, fill=MUTED)

    boxes = [
        ((95, 270, 365, 470), "固定样本", "正常样本\n边界样本\n失败样本", BLUE, PANEL),
        ((460, 270, 730, 470), "固定权重", "结构 20\n证据 25\n边界 20", TEAL, PANEL),
        ((825, 270, 1095, 470), "逐条评分", "稳定 15\n解释 20\n人工备注", ORANGE, PANEL),
        ((1190, 205, 1515, 370), "放行候选", "分数达标\n无关键失败\n证据可追溯", GREEN, "#ECFDF5"),
        ((1190, 510, 1515, 675), "复测或拒绝", "补造价格\n使用未来信息\n越权下单建议", RED, "#FEF2F2"),
    ]
    for xy, title, body, color, fill in boxes:
        card(draw, xy, title, body, color, fill)
    for x in (365, 730):
        arrow(draw, (x, 370), (x + 95, 370))
    arrow(draw, (1095, 345), (1190, 290), GREEN)
    arrow(draw, (1095, 395), (1190, 590), RED)

    draw.rounded_rectangle((260, 770, 1580, 875), radius=18, fill="#FFFFFF", outline=TEAL, width=4)
    draw.text((300, 800), "pass = score >= 75 且没有关键失败；分数说明输出过程质量，不直接证明交易收益。", font=BODY, fill=TEAL)
    GEN.mkdir(parents=True, exist_ok=True)
    img.save(GEN / "chapter-15-scoring-rubric.png")
    print(GEN / "chapter-15-scoring-rubric.png")


def save_factor_metrics_chart() -> None:
    signal = [float(i % 5 - 2) for i in range(60)]
    labels = [float((i % 7) - 3) * 0.01 for i in range(60)]
    metrics = evaluate_factor(signal, labels, min_samples=20)
    if metrics is None:
        raise RuntimeError("expected factor metrics")
    values = {
        "IC 均值": metrics.ic_mean,
        "命中率": metrics.hit_rate,
        "五分位差": metrics.quintile_spread,
        "换手率": metrics.turnover_rate,
    }

    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(10.5, 5.8), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor("#FFFFFF")
    colors = [BLUE, TEAL, ORANGE, RED]
    bars = ax.bar(values.keys(), values.values(), color=colors, width=0.58)
    ax.axhline(0, color="#334155", linewidth=1.1)
    ax.set_title("结构化信号进入量化评估后的示例指标", fontsize=17, pad=14)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, values.values()):
        y = value + 0.03 if value >= 0 else value - 0.03
        ax.text(bar.get_x() + bar.get_width() / 2, y, f"{value:.3f}", ha="center", va="bottom" if value >= 0 else "top", fontsize=10)
    ax.text(
        0.01,
        -0.16,
        f"sample_count={metrics.sample_count}；数据来自 tests/test_quant_upgrade.py 的固定示例序列。",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-15-factor-metrics.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-15-factor-metrics.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_scoring_rubric()
    save_factor_metrics_chart()


if __name__ == "__main__":
    main()
