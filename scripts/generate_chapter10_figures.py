"""Generate Chapter 10 publication figures."""

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
GRID = "#D8DEE9"


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


def save_claim_traceability() -> None:
    img = Image.new("RGB", (1760, 930), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 10 章：报告主张追溯路径", font=TITLE, fill=INK)
    draw.text((80, 116), "报告不是把结论写顺，而是让每个关键句子都能回到来源、计算和限制。", font=BODY, fill=MUTED)

    boxes = [
        ((90, 260, 360, 455), "报告主张", "一句结论\n先拆成主张", BLUE),
        ((475, 260, 745, 455), "来源字段", "source_id\n输入文件\n命令输出", TEAL),
        ((860, 260, 1130, 455), "计算口径", "参数\n公式\n样本窗口", ORANGE),
        ((1245, 260, 1515, 455), "限制声明", "unknowns\nwarnings\n禁止外推", RED),
    ]
    for xy, title, body, color in boxes:
        x1, y1, _, _ = xy
        draw.rounded_rectangle(xy, radius=18, fill=PANEL, outline=color, width=4)
        draw.text((x1 + 24, y1 + 22), title, font=HEAD, fill=color)
        draw.multiline_text((x1 + 24, y1 + 76), body, font=BODY, fill=INK, spacing=8)
    for x in (360, 745, 1130):
        arrow(draw, (x, 357), (x + 115, 357))

    draw.rounded_rectangle((245, 615, 1515, 760), radius=18, fill="#EEF2FF", outline=BLUE, width=4)
    draw.text((285, 645), "发布判断", font=HEAD, fill=BLUE)
    draw.text((285, 700), "能追源、能复算、限制保留：通过；来源不清、语言越界、删除风险提示：退回或拒绝。", font=BODY, fill=INK)
    img.save(OUT / "chapter-10-claim-traceability.png")
    print(OUT / "chapter-10-claim-traceability.png")


def save_report_layers() -> None:
    img = Image.new("RGB", (1840, 990), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 10 章实战：报告五层结构", font=TITLE, fill=INK)
    draw.text((80, 116), "事实、解释、信号、未知和来源要分层保存；自然语言越流畅，越要能拆回结构字段。", font=BODY, fill=MUTED)

    layers = [
        ("事实", "输入中真实存在的字段或记录\nresearch.facts[].source_id", BLUE),
        ("解释", "基于事实的谨慎说明\ninterpretation", TEAL),
        ("信号", "规则、回测或模型输出\nbacktest.metrics / verdict", ORANGE),
        ("未知", "样本、成本、执行未覆盖项\nunknowns", PURPLE),
        ("来源", "文件、字段、命令和警告\nsources / warnings", RED),
    ]
    y = 225
    for title, body, color in layers:
        draw.rounded_rectangle((180, y, 1660, y + 105), radius=18, fill=PANEL, outline=color, width=4)
        draw.text((220, y + 30), title, font=HEAD, fill=color)
        draw.multiline_text((440, y + 22), body, font=BODY, fill=INK, spacing=6)
        y += 122

    draw.rounded_rectangle((390, 860, 1450, 930), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((425, 882), "任何报告句子拆不回五层结构，就不能作为发布结论。", font=BODY, fill=RED)
    img.save(OUT / "chapter-10-report-layers.png")
    print(OUT / "chapter-10-report-layers.png")


def save_claim_ledger_review() -> None:
    img = Image.new("RGB", (1840, 1040), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 10 章实战：主张账本评审", font=TITLE, fill=INK)
    draw.text((80, 116), "从报告句子反向定位字段，决定保留、降级、删除或拒绝。", font=BODY, fill=MUTED)

    headers = [("报告句子", BLUE), ("来源路径", TEAL), ("处理方式", ORANGE)]
    xs = [100, 650, 1200]
    widths = [500, 500, 500]
    for (title, color), x, w in zip(headers, xs, widths):
        draw.rounded_rectangle((x, 230, x + w, 300), radius=14, fill=color)
        draw.text((x + 24, 249), title, font=HEAD, fill="#FFFFFF")

    rows = [
        ("固定样本包含 381 个日线收盘价", "research.facts[].source_id=S1", "可保留"),
        ("策略收益为 -15.35%", "backtest.metrics.strategy_return_pct", "保留并注明样本"),
        ("策略表现稳定", "需要更多窗口和样本", "降级或删除"),
        ("可以真实交易", "无来源且违反边界", "拒绝"),
    ]
    y = 335
    for sentence, source, action in rows:
        cells = [sentence, source, action]
        for idx, text in enumerate(cells):
            color = [BLUE, TEAL, ORANGE][idx]
            draw.rounded_rectangle((xs[idx], y, xs[idx] + widths[idx], y + 110), radius=14, fill=PANEL, outline=color, width=3)
            draw.multiline_text((xs[idx] + 22, y + 28), wrap(text, 18), font=BODY, fill=INK, spacing=5)
        y += 132

    draw.rounded_rectangle((325, 900, 1515, 975), radius=18, fill="#FFF7ED", outline=ORANGE, width=4)
    draw.text((365, 923), "账本的目的不是让报告更长，而是让每个关键句子都能被第二个人复核。", font=BODY, fill=ORANGE)
    img.save(OUT / "chapter-10-claim-ledger-review.png")
    print(OUT / "chapter-10-claim-ledger-review.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_claim_traceability()
    save_report_layers()
    save_claim_ledger_review()


if __name__ == "__main__":
    main()
