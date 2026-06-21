"""Generate Chapter 11 publication figures."""

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
    x1, y1, _, _ = xy
    draw.rounded_rectangle(xy, radius=18, fill=PANEL, outline=color, width=4)
    draw.text((x1 + 24, y1 + 22), title, font=HEAD, fill=color)
    draw.multiline_text((x1 + 24, y1 + 78), wrap(body, 20), font=BODY, fill=INK, spacing=7)


def save_boundary_card() -> None:
    img = Image.new("RGB", (1840, 1040), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 11 章实战：LLM 使用边界卡", font=TITLE, fill=INK)
    draw.text(
        (80, 116),
        "模型只能加工已给证据；凡是补造事实、绕过规则或给出执行建议，都必须降级、回退或拒绝。",
        font=BODY,
        fill=MUTED,
    )

    card(draw, (100, 230, 520, 460), "允许", "整理已有 evidence、kline、tradePlan 和 ruleSignal，生成摘要、解释和风险提示。", BLUE)
    card(draw, (710, 230, 1130, 460), "必须来自规则", "signal、score、confidence、样本窗口、指标数值和交易计划。", TEAL)
    card(draw, (1320, 230, 1740, 460), "必须拒绝", "未提供价格、实时新闻、确定收益、个人仓位或直接买卖建议。", RED)
    arrow(draw, (530, 345), (700, 345))
    arrow(draw, (1140, 345), (1310, 345))

    rows = [
        ("结构合法", "JSON 可解析、字段完整、信号枚举合法", "失败则回退规则基线"),
        ("证据引用", "关键判断能回到输入字段", "找不到来源则降级"),
        ("事实边界", "不新增价格、新闻、链上指标或未来结果", "补造事实则停止"),
        ("人工复核", "至少复核一个方向判断和一个风险提示", "无复核不发布"),
    ]
    y = 560
    for title, condition, action in rows:
        draw.rounded_rectangle((160, y, 1680, y + 86), radius=14, fill=PANEL, outline="#CBD5E1", width=3)
        draw.text((190, y + 27), title, font=HEAD, fill=PURPLE)
        draw.text((470, y + 29), condition, font=BODY, fill=INK)
        draw.text((1220, y + 29), action, font=BODY, fill=RED if "停止" in action or "不发布" in action else ORANGE)
        y += 108

    img.save(OUT / "chapter-11-llm-boundary-card.png")
    print(OUT / "chapter-11-llm-boundary-card.png")


def save_fallback_merge() -> None:
    img = Image.new("RGB", (1840, 980), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 11 章实战：规则基线与 LLM 合并路径", font=TITLE, fill=INK)
    draw.text(
        (80, 116),
        "先生成可复查的规则基线，再让 LLM 只改写白名单字段；调用失败或枚举非法时，保留规则结果。",
        font=BODY,
        fill=MUTED,
    )

    boxes = [
        ((100, 250, 430, 455), "规则基线", "run_signal_analysis\nsignal / score\nconfidence / evidence", BLUE),
        ((565, 250, 895, 455), "上下文包", "market / kline\nevidence\ntradePlan / ruleSignal", TEAL),
        ((1030, 250, 1360, 455), "LLM 输出", "summary / analysis\nlogicFlow\n候选 signal", ORANGE),
        ((1495, 250, 1745, 455), "白名单合并", "_merge_llm\n合法字段才覆盖", PURPLE),
    ]
    for xy, title, body, color in boxes:
        card(draw, xy, title, body, color)
    for x in (430, 895, 1360):
        arrow(draw, (x, 352), (x + 125, 352))

    draw.rounded_rectangle((210, 610, 760, 820), radius=18, fill="#ECFDF5", outline=TEAL, width=4)
    draw.text((245, 642), "可接受降级", font=HEAD, fill=TEAL)
    draw.multiline_text(
        (245, 700),
        "未配置 OPENAI_API_KEY\n模型调用失败\n返回 baseline 并记录 engineMeta.note",
        font=BODY,
        fill=INK,
        spacing=8,
    )

    draw.rounded_rectangle((1080, 610, 1630, 820), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((1115, 642), "必须拦截", font=HEAD, fill=RED)
    draw.multiline_text(
        (1115, 700),
        "signal 不在枚举内\n引用输入不存在的事实\n把研究输出写成交易建议",
        font=BODY,
        fill=INK,
        spacing=8,
    )
    arrow(draw, (480, 610), (480, 520), TEAL)
    arrow(draw, (1355, 610), (1355, 520), RED)

    img.save(OUT / "chapter-11-fallback-merge.png")
    print(OUT / "chapter-11-fallback-merge.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_boundary_card()
    save_fallback_merge()


if __name__ == "__main__":
    main()
