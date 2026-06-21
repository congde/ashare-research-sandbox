"""Generate Chapter 06 publication figures."""

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
TINY = font(18)

BG = "#F7F9FC"
INK = "#111827"
MUTED = "#64748B"
BLUE = "#2563EB"
TEAL = "#0F9B8E"
ORANGE = "#F59E0B"
RED = "#DC2626"
GREEN = "#2E7D32"
PURPLE = "#7C3AED"
PANEL = "#FFFFFF"
GRID = "#D8DEE9"


def wrapped(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=True))


def rounded_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    body: str,
    color: str,
    *,
    body_font: ImageFont.FreeTypeFont = BODY,
) -> None:
    draw.rounded_rectangle(box, radius=18, fill=PANEL, outline=color, width=4)
    x1, y1, _, _ = box
    draw.text((x1 + 24, y1 + 22), title, font=HEAD, fill=color)
    draw.multiline_text((x1 + 24, y1 + 72), body, font=body_font, fill=INK, spacing=7)


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


def save_evidence_gates() -> None:
    img = Image.new("RGB", (1850, 900), BG)
    draw = ImageDraw.Draw(img)

    draw.text((80, 58), "第 6 章：数据证据门", font=TITLE, fill=INK)
    draw.text(
        (80, 118),
        "行情、资金、链上与情绪数据进入结论前，必须先证明来源、时间、口径和用途。",
        font=BODY,
        fill=MUTED,
    )

    boxes = [
        ((80, 270, 300, 470), "原始数据", "行情\n资金\n链上\n情绪", BLUE),
        ((390, 270, 610, 470), "来源门", "origin\nsource\npath", TEAL),
        ((700, 270, 920, 470), "时间门", "observed_at\nupdated_at\n窗口重叠", TEAL),
        ((1010, 270, 1230, 470), "口径门", "字段定义\n采样频率\n缺失处理", ORANGE),
        ((1320, 270, 1540, 470), "用途门", "能回答什么\n不能回答什么\n失败处理", RED),
    ]
    for box, title, body, color in boxes:
        rounded_box(draw, box, title, body, color)
    for x in (300, 610, 920, 1230):
        arrow(draw, (x, 370), (x + 90, 370))
    arrow(draw, (1540, 370), (1660, 370), GREEN)
    draw.rounded_rectangle((1660, 270, 1785, 470), radius=18, fill="#E8F5E9", outline=GREEN, width=4)
    draw.text((1688, 336), "指标\n摘要", font=HEAD, fill=INK, spacing=8)

    draw.rounded_rectangle((220, 610, 1630, 760), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((265, 638), "停止线", font=HEAD, fill=RED)
    draw.text(
        (265, 695),
        "来源不清、时间错配、字段口径不一致或用途越界时，只能退回来源卡；不能写成同一时点市场事实。",
        font=BODY,
        fill=INK,
    )

    img.save(OUT / "chapter-06-evidence-gates.png")
    print(OUT / "chapter-06-evidence-gates.png")


def save_data_map_path() -> None:
    img = Image.new("RGB", (1900, 980), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 6 章实战：市场数据地图怎么走", font=TITLE, fill=INK)
    draw.text(
        (80, 116),
        "读者不是只看 JSON，而是沿着文件、完整性检查、manifest、API 和页面解释一路追踪证据。",
        font=BODY,
        fill=MUTED,
    )

    top = [
        ((80, 250, 365, 430), "数据文件", "data/dashboard/\nfixtures\nsnapshots\nhistory", BLUE),
        ((470, 250, 755, 430), "完整性检查", "catalog.py\nis_complete()\ncompleteness_detail()", TEAL),
        ((860, 250, 1145, 455), "来源记录", "manifest.json\norigin\nupdated_at\ncomplete\npath", ORANGE),
        ((1250, 250, 1535, 430), "统一输出", "api.py\nfixture / snapshot / live\nfallback 状态", PURPLE),
        ((1640, 250, 1820, 430), "页面/LLM", "只能摘要\n不能补造\n不能下单", RED),
    ]
    for box, title, body, color in top:
        rounded_box(draw, box, title, body, color, body_font=SMALL)
    for x in (365, 755, 1145, 1535):
        arrow(draw, (x, 340), (x + 105, 340))

    draw.rounded_rectangle((140, 555, 1760, 820), radius=18, fill="#FFFFFF", outline=GRID, width=3)
    draw.text((180, 595), "最小走查记录", font=HEAD, fill=INK)
    rows = [
        ("1", "打开 manifest", "记录每个数据集的 origin、updated_at、complete、path"),
        ("2", "追到原始文件", "确认 path 指向的 fixture、snapshot 或 history 文件真实存在"),
        ("3", "查看检查函数", "确认 complete=True 来自规则，而不是作者主观判断"),
        ("4", "检查输出语义", "确认 API 和页面保留 fallback、离线或快照状态"),
    ]
    y = 645
    for number, title, body in rows:
        draw.ellipse((185, y - 3, 225, y + 37), fill="#EEF2FF", outline=BLUE, width=2)
        draw.text((198, y + 2), number, font=SMALL, fill=BLUE)
        draw.text((250, y), title, font=BODY, fill=INK)
        draw.text((470, y), body, font=BODY, fill=MUTED)
        y += 45

    draw.rounded_rectangle((470, 865, 1430, 935), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((505, 886), "任何一段追不到来源或时间，就不能进入“当前市场状态”的合并结论。", font=BODY, fill=RED)
    img.save(OUT / "chapter-06-data-map-path.png")
    print(OUT / "chapter-06-data-map-path.png")


def source_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    domain: str,
    source: str,
    can: str,
    cannot: str,
    color: str,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=18, fill=PANEL, outline=color, width=4)
    draw.rectangle((x1, y1, x2, y1 + 62), fill=color)
    draw.text((x1 + 24, y1 + 17), title, font=HEAD, fill="#FFFFFF")
    y = y1 + 88
    items = [
        ("数据域", domain),
        ("来源", source),
        ("能回答", can),
        ("不能回答", cannot),
    ]
    for label, value in items:
        draw.text((x1 + 24, y), label, font=SMALL, fill=color)
        draw.multiline_text((x1 + 112, y), wrapped(value, 14), font=TINY, fill=INK, spacing=5)
        y += 84 if label in {"能回答", "不能回答"} else 45


def save_source_card_examples() -> None:
    img = Image.new("RGB", (1900, 1060), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 6 章实战：四类来源卡示例", font=TITLE, fill=INK)
    draw.text(
        (80, 116),
        "来源卡把“能回答什么”和“不能回答什么”并排固定下来，避免数据被写成过度结论。",
        font=BODY,
        fill=MUTED,
    )

    cards = [
        ((80, 230, 510, 760), "market_tickers", "行情", "snapshot / live", "保存时点下的价格、涨跌幅和成交量字段", "资金真实流向、因果关系、未来收益", BLUE),
        ((540, 230, 970, 760), "token_fund", "资金", "snapshot / fixture", "样本内市值、流通量和资金线索分布", "可执行买卖方向或资金未来变化", ORANGE),
        ((1000, 230, 1430, 760), "onchain", "链上", "fixture / live", "公开账本或链上指标的观察结果", "交易所订单簿即时买盘或成交意图", TEAL),
        ((1460, 230, 1890, 760), "ai_picks", "情绪", "fixture / model", "候选叙事、热度和风险偏好线索", "真实订单、确定预测或投资建议", PURPLE),
    ]
    for args in cards:
        source_card(draw, *args)

    draw.rounded_rectangle((220, 850, 1680, 965), radius=18, fill="#FFF7ED", outline=ORANGE, width=4)
    draw.text((265, 878), "交付要求", font=HEAD, fill=ORANGE)
    draw.text(
        (265, 930),
        "四张卡都能写清来源、时间、字段和限制后，才允许进入指标计算或 LLM 摘要；缺一张，就先补证据。",
        font=BODY,
        fill=INK,
    )
    img.save(OUT / "chapter-06-source-cards.png")
    print(OUT / "chapter-06-source-cards.png")


def save_time_mismatch_case() -> None:
    img = Image.new("RGB", (1800, 960), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 6 章实战：时间错配反例", font=TITLE, fill=INK)
    draw.text(
        (80, 116),
        "同一资产、同一页面、同一摘要，不代表数据来自同一时间窗口；时间不重叠时必须降级表述。",
        font=BODY,
        fill=MUTED,
    )

    draw.line((180, 360, 1560, 360), fill=GRID, width=6)
    draw.text((180, 310), "09:00", font=SMALL, fill=MUTED)
    draw.text((650, 310), "12:00", font=SMALL, fill=MUTED)
    draw.text((1120, 310), "15:00", font=SMALL, fill=MUTED)
    draw.text((1500, 310), "18:00", font=SMALL, fill=MUTED)

    bars = [
        ((230, 390, 760, 470), "情绪指数", "09:00-10:00 采样", PURPLE),
        ((650, 510, 1180, 590), "链上事件", "12:30 索引完成", TEAL),
        ((1060, 630, 1540, 710), "行情快照", "15:00 保存", BLUE),
    ]
    for box, title, body, color in bars:
        draw.rounded_rectangle(box, radius=18, fill="#FFFFFF", outline=color, width=4)
        draw.text((box[0] + 25, box[1] + 14), title, font=HEAD, fill=color)
        draw.text((box[0] + 220, box[1] + 22), body, font=BODY, fill=INK)
        arrow(draw, ((box[0] + box[2]) // 2, box[1]), ((box[0] + box[2]) // 2, 365), color)

    draw.rounded_rectangle((220, 790, 1580, 900), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((265, 818), "被拦下的结论", font=HEAD, fill=RED)
    draw.text(
        (265, 868),
        "“当前市场同时恐慌、链上活跃、价格下跌”不能发布；只能写成“三个来源分别显示……，时间窗口不同”。",
        font=BODY,
        fill=INK,
    )
    img.save(OUT / "chapter-06-time-mismatch-case.png")
    print(OUT / "chapter-06-time-mismatch-case.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_evidence_gates()
    save_data_map_path()
    save_source_card_examples()
    save_time_mismatch_case()


if __name__ == "__main__":
    main()
