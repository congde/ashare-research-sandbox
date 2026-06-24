"""Generate Chapter 14 publication figures."""

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

from backtest.pollution import run_pollution_checks  # noqa: E402


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


def save_pollution_gate() -> None:
    img = Image.new("RGB", (1840, 980), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 14 章：LLM 污染拦截路径", font=TITLE, fill=INK)
    draw.text((80, 116), "污染不是模型答错，而是错误信息进入证据链后污染研究判断。", font=BODY, fill=MUTED)

    boxes = [
        ((95, 270, 365, 470), "输入", "行情\n链上\n新闻\n策略代码", BLUE),
        ((460, 270, 730, 470), "污染门禁", "幻觉诱因\n提示注入\n未来信息", ORANGE),
        ((825, 270, 1095, 470), "结构输出", "JSON\nsignal\nreason", TEAL),
        ((1190, 270, 1460, 470), "复核", "来源\n时间\n证据", PURPLE),
        ((1555, 270, 1775, 470), "决定", "继续\n复测\n拒绝", RED),
    ]
    for xy, title, body, color in boxes:
        card(draw, xy, title, body, color)
    for x in (365, 730, 1095, 1460):
        arrow(draw, (x, 370), (x + 90, 370))

    draw.rounded_rectangle((330, 690, 1510, 800), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((370, 725), "污染样本在进入结论前停止；如果已进入回测样本，相关实验记录作废并重建。", font=BODY, fill=RED)
    GEN.mkdir(parents=True, exist_ok=True)
    img.save(GEN / "chapter-14-pollution-gate.png")
    print(GEN / "chapter-14-pollution-gate.png")


def save_pollution_cases_chart() -> None:
    payload = run_pollution_checks()
    cases = payload["cases"]
    labels = [case["label"] for case in cases]
    dsl = [1 if case["dsl_valid"] else 0 for case in cases]
    lookahead = [1 if case["lookahead_clean"] else 0 for case in cases]
    ready = [1 if case["backtest_ready"] else 0 for case in cases]

    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(10.8, 5.8), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor("#FFFFFF")
    x = range(len(labels))
    width = 0.22
    ax.bar([i - width for i in x], dsl, width=width, label="DSL 安全", color=BLUE)
    ax.bar(list(x), lookahead, width=width, label="前视干净", color=TEAL)
    ax.bar([i + width for i in x], ready, width=width, label="可进回测", color=ORANGE)
    ax.set_ylim(0, 1.25)
    ax.set_yticks([0, 1], ["失败", "通过"])
    ax.set_xticks(list(x), labels)
    ax.set_title("三类污染样本的门禁结果", fontsize=17, pad=14)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper right", frameon=False)
    ax.text(
        0.01,
        -0.16,
        "lookahead_shift 说明：代码可安全执行，但 shift(-5) 仍会污染回测，因此不可进入回测。",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-14-pollution-cases.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-14-pollution-cases.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_pollution_gate()
    save_pollution_cases_chart()


if __name__ == "__main__":
    main()
