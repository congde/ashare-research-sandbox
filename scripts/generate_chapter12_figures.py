"""Generate Chapter 12 publication figures."""

from __future__ import annotations

import json
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

from dashboard.signal_analysis import run_signal_analysis  # noqa: E402


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
    if abs(ex - sx) >= abs(ey - sy):
        sign = 1 if ex >= sx else -1
        pts = [(ex, ey), (ex - sign * 18, ey - 11), (ex - sign * 18, ey + 11)]
    else:
        sign = 1 if ey >= sy else -1
        pts = [(ex, ey), (ex - 11, ey - sign * 18), (ex + 11, ey - sign * 18)]
    draw.polygon(pts, fill=color)


def block(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], title: str, body: str, color: str) -> None:
    x1, y1, _, _ = xy
    draw.rounded_rectangle(xy, radius=18, fill=PANEL, outline=color, width=4)
    draw.text((x1 + 24, y1 + 22), title, font=HEAD, fill=color)
    draw.multiline_text((x1 + 24, y1 + 78), wrap(body, 19), font=BODY, fill=INK, spacing=7)


def save_context_contract() -> None:
    img = Image.new("RGB", (1840, 1040), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 12 章实战：LLM 上下文合同", font=TITLE, fill=INK)
    draw.text(
        (80, 116),
        "上下文不是资料堆叠，而是把模型可见字段、时间口径和用途整理成可复查合同。",
        font=BODY,
        fill=MUTED,
    )

    boxes = [
        ((100, 235, 420, 430), "市场事实", "symbol\nprice / volume\nsource_time", BLUE),
        ((520, 235, 840, 430), "技术状态", "kline\nSMA / RSI / MACD\nwindow", TEAL),
        ((940, 235, 1260, 430), "证据列表", "evidence[]\n字段路径\n方向与权重", ORANGE),
        ((1360, 235, 1680, 430), "交易计划", "entry / stop\ninvalid_if\nresearch_only", PURPLE),
    ]
    for xy, title, body, color in boxes:
        block(draw, xy, title, body, color)

    for x in (420, 840, 1260):
        arrow(draw, (x, 332), (x + 90, 332))

    draw.rounded_rectangle((210, 565, 760, 820), radius=18, fill="#ECFDF5", outline=TEAL, width=4)
    draw.text((245, 600), "允许进入提示词", font=HEAD, fill=TEAL)
    draw.multiline_text(
        (245, 660),
        "有来源\n有时间口径\n有字段含义\n服务当前任务",
        font=BODY,
        fill=INK,
        spacing=8,
    )

    draw.rounded_rectangle((1080, 565, 1630, 820), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((1115, 600), "禁止进入提示词", font=HEAD, fill=RED)
    draw.multiline_text(
        (1115, 660),
        "未来标签\n无来源摘要\n完整原始历史\n真实下单指令",
        font=BODY,
        fill=INK,
        spacing=8,
    )

    draw.rounded_rectangle((360, 900, 1480, 970), radius=18, fill="#EEF2FF", outline=BLUE, width=4)
    draw.text((395, 922), "合格上下文 = 支持当前问题 + 可由程序裁剪 + 可由人工复核", font=BODY, fill=BLUE)
    img.save(OUT / "chapter-12-context-contract.png")
    print(OUT / "chapter-12-context-contract.png")


def save_visible_window() -> None:
    img = Image.new("RGB", (1840, 980), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 12 章实战：可见时间窗口", font=TITLE, fill=INK)
    draw.text(
        (80, 116),
        "只有决策时点之前已经可见的字段，才能进入模型信号解释上下文。",
        font=BODY,
        fill=MUTED,
    )

    y = 360
    x0 = 160
    step = 95
    dates = ["t-6", "t-5", "t-4", "t-3", "t-2", "t-1", "t", "t+1", "t+2"]
    for idx, label in enumerate(dates):
        x = x0 + idx * step
        color = TEAL if idx <= 6 else RED
        fill = "#ECFDF5" if idx <= 6 else "#FEF2F2"
        draw.rounded_rectangle((x, y, x + 72, y + 72), radius=12, fill=fill, outline=color, width=3)
        draw.text((x + 18, y + 22), label, font=SMALL, fill=color)
        if idx < len(dates) - 1:
            draw.line((x + 72, y + 36, x + step, y + 36), fill="#CBD5E1", width=3)

    draw.line((x0 + 6 * step + 36, 250, x0 + 6 * step + 36, 590), fill=BLUE, width=5)
    draw.text((x0 + 6 * step - 65, 210), "decision_time", font=HEAD, fill=BLUE)

    draw.rounded_rectangle((180, 660, 800, 835), radius=18, fill=PANEL, outline=TEAL, width=4)
    draw.text((215, 690), "允许", font=HEAD, fill=TEAL)
    draw.multiline_text((215, 748), "最近 limit 根 K 线\n已知指标窗口\n规则基线和证据字段", font=BODY, fill=INK, spacing=8)

    draw.rounded_rectangle((1040, 660, 1660, 835), radius=18, fill=PANEL, outline=RED, width=4)
    draw.text((1075, 690), "停止", font=HEAD, fill=RED)
    draw.multiline_text((1075, 748), "下一期收益\n未来收盘价\n事后人工总结或标签", font=BODY, fill=INK, spacing=8)

    img.save(OUT / "chapter-12-visible-window.png")
    print(OUT / "chapter-12-visible-window.png")


def save_context_shape() -> None:
    baseline = run_signal_analysis("BTC")
    context = {
        "market": baseline.get("market"),
        "kline": baseline.get("kline"),
        "evidence": baseline.get("evidence"),
        "onchainMetrics": baseline.get("onchainMetrics"),
        "tradePlan": baseline.get("tradePlan"),
        "ruleSignal": {
            "signal": baseline.get("signal"),
            "signalLabel": baseline.get("signalLabel"),
            "confidence": baseline.get("confidence"),
            "score": baseline.get("score"),
            "reasons": baseline.get("reasons"),
        },
    }
    rows = [(key, len(json.dumps(value, ensure_ascii=False))) for key, value in context.items()]
    labels = [row[0] for row in rows]
    values = [row[1] for row in rows]

    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(10.5, 5.8), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor("#FFFFFF")
    ax.barh(labels, values, color=[BLUE, TEAL, ORANGE, PURPLE, RED, "#334155"])
    ax.set_title("BTC 规则基线进入模型上下文的字段体量", fontsize=17, pad=14)
    ax.set_xlabel("JSON 字符数", fontsize=12)
    ax.grid(axis="x", color="#E5E7EB", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for index, value in enumerate(values):
        ax.text(value + max(values) * 0.02, index, str(value), va="center", fontsize=10)
    ax.text(
        0.01,
        -0.16,
        f"signal={baseline.get('signal')}，logicFlow={len(baseline.get('logicFlow') or [])}；数据来自 run_signal_analysis('BTC')。",
        transform=ax.transAxes,
        fontsize=10,
        color=MUTED,
    )
    fig.tight_layout()
    fig.savefig(OUT / "chapter-12-context-shape.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-12-context-shape.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_context_contract()
    save_visible_window()
    save_context_shape()


if __name__ == "__main__":
    main()
