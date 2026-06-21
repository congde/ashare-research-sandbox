"""Generate focused Chinese teaching figures for chapters 05, 07, 08, and 10."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
ASSET_OUT = ROOT / "docs" / "v2" / "assets"
FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


TITLE = font(42)
HEAD = font(29)
BODY = font(24)
SMALL = font(21)

BG = "#F7F9FC"
INK = "#111827"
MUTED = "#64748B"
BLUE = "#2563EB"
TEAL = "#0F9B8E"
ORANGE = "#F59E0B"
RED = "#DC2626"
PANEL = "#FFFFFF"
GRID = "#D8DEE9"


def rounded_box(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, body: str, color: str) -> None:
    draw.rounded_rectangle(box, radius=18, fill=PANEL, outline=color, width=4)
    x1, y1, x2, _ = box
    draw.text((x1 + 24, y1 + 22), title, font=HEAD, fill=color)
    draw.multiline_text((x1 + 24, y1 + 74), body, font=BODY, fill=INK, spacing=8)


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


def save_publish_pipeline() -> None:
    img = Image.new("RGB", (1950, 820), BG)
    draw = ImageDraw.Draw(img)
    draw.text((90, 60), "第 5 章：研究结果发布流水线", font=TITLE, fill=INK)
    draw.text((90, 120), "每个结论先过来源、计算、风险和表达四道门；过不了就退回研究记录。", font=BODY, fill=MUTED)

    boxes = [
        ((90, 270, 330, 430), "研究记录", "固定样本\n信号来源\n原始限制", BLUE),
        ((420, 270, 660, 430), "来源门", "数据路径\n快照时间\n字段口径", TEAL),
        ((750, 270, 990, 430), "计算门", "指标公式\n回测参数\n成本假设", TEAL),
        ((1080, 270, 1320, 430), "风险门", "仓位上限\n拒绝原因\n停止线", ORANGE),
        ((1410, 270, 1650, 430), "表达门", "研究表述\n限制说明\n无订单语义", RED),
    ]
    for box, title, body, color in boxes:
        rounded_box(draw, box, title, body, color)
    for x in (330, 660, 990, 1320):
        arrow(draw, (x, 350), (x + 90, 350))
    arrow(draw, (1650, 350), (1770, 350), color=TEAL)
    draw.rounded_rectangle((1770, 270, 1910, 430), radius=18, fill="#E8F5E9", outline="#2E7D32", width=4)
    draw.text((1795, 324), "页面\n报告", font=HEAD, fill=INK, spacing=8)

    draw.rounded_rectangle((250, 565, 1700, 700), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((295, 590), "退回条件", font=HEAD, fill=RED)
    draw.text(
        (295, 645),
        "来源不清、计算不可复算、风险未说明、表达像真实交易动作：全部退回研究记录，不进入页面或报告。",
        font=BODY,
        fill=INK,
    )
    img.save(ASSET_OUT / "chapter-05-publish-pipeline.png")


def save_execution_gate_case() -> None:
    img = Image.new("RGB", (1600, 940), BG)
    draw = ImageDraw.Draw(img)
    draw.text((70, 46), "第 5 章：个人量化研究的执行门案例", font=TITLE, fill=INK)
    draw.text((70, 106), "真实运行记录：规则信号可以进入研究记录，但不能自动升级为实盘动作。", font=BODY, fill=MUTED)

    boxes = [
        ((70, 225, 360, 420), "当前信号", "BTC 规则信号\nHOLD / 置信度 1.8%\n仅说明样本状态", BLUE),
        ((455, 225, 745, 420), "回测证据", "ma_crossover\n2 笔交易 / +6.92%\n固定样本结果", TEAL),
        ((840, 225, 1130, 420), "动作请求", "想立刻买入\n填写金额与方向\n准备 dry-run", ORANGE),
        ((1225, 225, 1515, 420), "执行门", "CONFIRM 门禁\nMAX_POSITION_PCT\n真实订单入口不存在", RED),
    ]
    for box, title, body, color in boxes:
        rounded_box(draw, box, title, body, color)
    for x in (360, 745, 1130):
        arrow(draw, (x, 322), (x + 95, 322))

    draw.rounded_rectangle((120, 520, 1480, 760), radius=18, fill="#FFFFFF", outline=GRID, width=3)
    draw.text((160, 550), "案例判定", font=HEAD, fill=INK)
    draw.multiline_text(
        (160, 610),
        "1. HOLD 信号与正收益回测同时存在时，只能写入研究记录。\n"
        "2. 如果方向与信号不一致，页面显示“信号未对齐 · 仅 dry-run”。\n"
        "3. 如果金额超过上限，RiskManager 模拟拒绝；真实账户、钱包和订单接口不在本仓库能力范围内。",
        font=BODY,
        fill=INK,
        spacing=10,
    )

    draw.rounded_rectangle((330, 805, 1270, 890), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((370, 828), "停止线：回测为正 ≠ 可以自动买入；执行动作必须另走实盘系统和人工审批。", font=BODY, fill=RED)
    img.save(ASSET_OUT / "chapter-05-execution-gate-case.png")


def save_snapshot_fallback() -> None:
    img = Image.new("RGB", (1600, 900), BG)
    draw = ImageDraw.Draw(img)
    draw.text((70, 48), "第 7 章：市场数据快照与回退路径", font=TITLE, fill=INK)
    draw.text((70, 108), "目标不是永远实时，而是每次使用数据时都能说明来源、时间和回退层级。", font=BODY, fill=MUTED)

    boxes = [
        ((80, 250, 360, 430), "实时接口", "live 请求\n可能成功，也可能失败", BLUE),
        ((455, 250, 735, 430), "保存快照", "history 归档\nlatest 指针更新", TEAL),
        ((830, 250, 1110, 430), "读取页面", "source=snapshot\nsaved_at 可见", TEAL),
        ((1205, 250, 1485, 430), "离线样本", "fixture 兜底\n必须显式标记", ORANGE),
    ]
    for box, title, body, color in boxes:
        rounded_box(draw, box, title, body, color)
    arrow(draw, (360, 340), (455, 340))
    arrow(draw, (735, 340), (830, 340))
    arrow(draw, (1110, 340), (1205, 340))

    draw.rounded_rectangle((290, 560, 1310, 720), radius=18, fill="#FFF7ED", outline=ORANGE, width=4)
    draw.text((330, 585), "停止线", font=HEAD, fill=ORANGE)
    draw.multiline_text(
        (330, 638),
        "接口失败可以接受；静默使用旧数据、却仍写成“实时市场”，必须停止并改正文案或字段。",
        font=BODY,
        fill=INK,
        spacing=8,
    )
    img.save(OUT / "chapter-07-snapshot-fallback.png")


def save_cleaning_gates() -> None:
    img = Image.new("RGB", (1600, 920), BG)
    draw = ImageDraw.Draw(img)
    draw.text((70, 48), "第 8 章：时间序列清洗门禁", font=TITLE, fill=INK)
    draw.text((70, 108), "清洗不是把数据变漂亮，而是决定哪些记录有资格进入指标和回测。", font=BODY, fill=MUTED)

    steps = [
        ((80, 245, 340, 425), "原始记录", "保留原字段\n不先改写含义", BLUE),
        ((430, 245, 690, 425), "字段契约", "date / close\n必需字段完整", TEAL),
        ((780, 245, 1040, 425), "时间顺序", "按时间排序\n拒绝乱序收益", TEAL),
        ((1130, 245, 1390, 425), "用途放行", "展示 / 指标 / 回测\n分层决定", ORANGE),
    ]
    for box, title, body, color in steps:
        rounded_box(draw, box, title, body, color)
    for x in (340, 690, 1040):
        arrow(draw, (x, 335), (x + 90, 335))

    draw.rounded_rectangle((160, 560, 1440, 760), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((205, 590), "不能为了连续曲线而自动补齐所有缺失值", font=HEAD, fill=RED)
    draw.multiline_text(
        (205, 650),
        "缺失、异常和错序本身就是证据。若补值改变了收益、指标或买卖点，必须记录补值规则，不能把未知伪装成事实。",
        font=BODY,
        fill=INK,
        spacing=8,
    )
    img.save(OUT / "chapter-08-cleaning-gates.png")


def save_claim_traceability() -> None:
    img = Image.new("RGB", (1600, 900), BG)
    draw = ImageDraw.Draw(img)
    draw.text((70, 48), "第 10 章：报告主张追溯路径", font=TITLE, fill=INK)
    draw.text((70, 108), "报告不是把结果写顺，而是让每个关键句子都能追到来源、计算和限制。", font=BODY, fill=MUTED)

    boxes = [
        ((90, 240, 340, 440), "报告主张", "一句结论\n先拆成主张", BLUE),
        ((430, 240, 680, 440), "来源字段", "source_id\n输入文件或快照", TEAL),
        ((770, 240, 1020, 440), "计算口径", "参数、公式\n样本窗口", ORANGE),
        ((1110, 240, 1360, 440), "限制声明", "unknowns\nwarnings", RED),
    ]
    for box, title, body, color in boxes:
        rounded_box(draw, box, title, body, color)
    for x in (340, 680, 1020):
        arrow(draw, (x, 340), (x + 90, 340))

    draw.rounded_rectangle((260, 570, 1340, 725), radius=18, fill="#EEF2FF", outline=BLUE, width=4)
    draw.text((300, 595), "发布判断", font=HEAD, fill=BLUE)
    draw.multiline_text(
        (300, 650),
        "能追溯、能复算、限制保留：通过。来源不清、语言越界、删除风险提示：退回修改或拒绝。",
        font=BODY,
        fill=INK,
        spacing=8,
    )
    img.save(OUT / "chapter-10-claim-traceability.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ASSET_OUT.mkdir(parents=True, exist_ok=True)
    save_publish_pipeline()
    save_execution_gate_case()
    save_snapshot_fallback()
    save_cleaning_gates()
    save_claim_traceability()
    for name in (
        "chapter-05-publish-pipeline.png",
        "chapter-05-execution-gate-case.png",
        "chapter-07-snapshot-fallback.png",
        "chapter-08-cleaning-gates.png",
        "chapter-10-claim-traceability.png",
    ):
        path = ASSET_OUT / name if name.startswith("chapter-05-") else OUT / name
        print(path)


if __name__ == "__main__":
    main()
