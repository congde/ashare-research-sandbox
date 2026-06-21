"""Generate focused Chinese teaching figures for chapters 22 through 25."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


TITLE = font(42)
HEAD = font(29)
BODY = font(24)
SMALL = font(20)

BG = "#F7F9FC"
INK = "#111827"
MUTED = "#64748B"
BLUE = "#2563EB"
TEAL = "#0F9B8E"
ORANGE = "#F59E0B"
RED = "#DC2626"
GREEN = "#15803D"
PANEL = "#FFFFFF"


def rounded_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    body: str,
    color: str,
    fill: str = PANEL,
) -> None:
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=color, width=4)
    x1, y1, _, _ = box
    draw.text((x1 + 24, y1 + 20), title, font=HEAD, fill=color)
    draw.multiline_text((x1 + 24, y1 + 72), body, font=BODY, fill=INK, spacing=8)


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


def base(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (1600, 920), BG)
    draw = ImageDraw.Draw(img)
    draw.text((70, 48), title, font=TITLE, fill=INK)
    draw.text((70, 108), subtitle, font=BODY, fill=MUTED)
    return img, draw


def save_risk_order_gate() -> None:
    img, draw = base("第 22 讲：仓位与风控下单门禁", "风险控制发生在下单前；被拒绝的订单必须留下规则、原因和状态。")
    rounded_box(draw, (80, 245, 350, 430), "订单意图", "方向、数量、价格\n来自策略规则", BLUE)
    rounded_box(draw, (445, 245, 715, 430), "组合状态", "现金、持仓、权益\n已有风险暴露", TEAL)
    rounded_box(draw, (810, 245, 1080, 430), "风险规则", "最大仓位\n止损/回撤\n滑点/异常 K", ORANGE)
    rounded_box(draw, (1175, 190, 1505, 355), "允许成交", "记录成本\n更新仓位\n刷新权益", GREEN, "#ECFDF5")
    rounded_box(draw, (1175, 465, 1505, 630), "拒绝订单", "写入 rule_id\n说明原因\n保留样本", RED, "#FEF2F2")
    arrow(draw, (350, 335), (445, 335))
    arrow(draw, (715, 335), (810, 335))
    arrow(draw, (1080, 310), (1175, 275), GREEN)
    arrow(draw, (1080, 370), (1175, 545), RED)
    draw.rounded_rectangle((190, 705, 1410, 845), radius=18, fill="#FFFFFF", outline=BLUE, width=4)
    draw.text((235, 730), "读图要点", font=HEAD, fill=BLUE)
    draw.text((235, 785), "风控不是回测后的解释，而是每个订单进入成交前的硬门禁。", font=BODY, fill=INK)
    draw.text((235, 818), "收益降低但回撤受控，可能正是风险系统发挥作用。", font=SMALL, fill=MUTED)
    img.save(OUT / "chapter-22-risk-order-gate.png")


def save_research_ia_path() -> None:
    img, draw = base("第 23 讲：交易研究应用路径", "页面不是模块堆叠，而是把数据、信号、回测和风险串成可复查路径。")
    boxes = [
        ((65, 285, 305, 455), "行情总览", "市场状态\n来源时间", BLUE),
        ((380, 285, 620, 455), "机会雷达", "候选理由\n风险标签", TEAL),
        ((695, 285, 935, 455), "K 线信号", "指标证据\n规则基线", ORANGE),
        ((1010, 285, 1250, 455), "回测中心", "成本假设\n绩效路径", TEAL),
        ((1325, 285, 1565, 455), "风险中心", "拒绝记录\n停止线", RED),
    ]
    for box, title, body, color in boxes:
        rounded_box(draw, box, title, body, color)
    for x in (305, 620, 935, 1250):
        arrow(draw, (x, 370), (x + 75, 370))
    draw.rounded_rectangle((250, 680, 1350, 820), radius=18, fill="#EEF2FF", outline=BLUE, width=4)
    draw.text((295, 705), "验证重点", font=HEAD, fill=BLUE)
    draw.text((295, 760), "每次跳转都要保留来源、状态和失败说明；不能让页面导航切断证据链。", font=BODY, fill=INK)
    img.save(OUT / "chapter-23-research-ia-path.png")


def save_market_candidate_path() -> None:
    img, draw = base("第 24 讲：行情候选的数据路径", "机会列表必须同时展示来源、更新时间、筛选理由和降级状态。")
    rounded_box(draw, (80, 245, 350, 430), "数据源", "在线接口\n离线快照\n更新时间", BLUE)
    rounded_box(draw, (445, 245, 715, 430), "行情总览", "价格\n涨跌\n成交量", TEAL)
    rounded_box(draw, (810, 245, 1080, 430), "机会雷达", "排名分数\n入选原因\n风险标签", ORANGE)
    rounded_box(draw, (1175, 190, 1505, 355), "继续研究", "来源清楚\n候选可解释", GREEN, "#ECFDF5")
    rounded_box(draw, (1175, 465, 1505, 630), "降级或停止", "接口失败\n快照过旧\n来源缺失", RED, "#FEF2F2")
    arrow(draw, (350, 335), (445, 335))
    arrow(draw, (715, 335), (810, 335))
    arrow(draw, (1080, 310), (1175, 275), GREEN)
    arrow(draw, (1080, 370), (1175, 545), RED)
    draw.rounded_rectangle((190, 705, 1410, 845), radius=18, fill="#FFFFFF", outline=TEAL, width=4)
    draw.text((235, 730), "读图要点", font=HEAD, fill=TEAL)
    draw.text((235, 785), "候选不是建议；只有数据路径、筛选规则和风险状态同时可见，候选才有研究价值。", font=BODY, fill=INK)
    img.save(OUT / "chapter-24-market-candidate-path.png")


def save_kline_llm_binding() -> None:
    img, draw = base("第 25 讲：K 线与 LLM 信号绑定", "模型解释必须回到 K 线、指标、规则信号和证据字段。")
    rounded_box(draw, (80, 245, 350, 430), "K 线指标", "价格、均线\nRSI、成交量", BLUE)
    rounded_box(draw, (445, 245, 715, 430), "规则基线", "signal\nscore\nconfidence", TEAL)
    rounded_box(draw, (810, 245, 1080, 430), "LLM 解释", "summary\nanalysis\nlogicFlow", ORANGE)
    rounded_box(draw, (1175, 190, 1505, 355), "可发布观察", "证据匹配\n状态可见", GREEN, "#ECFDF5")
    rounded_box(draw, (1175, 465, 1505, 630), "降级或拒绝", "fallback 未标注\n补造事实\n越权建议", RED, "#FEF2F2")
    arrow(draw, (350, 335), (445, 335))
    arrow(draw, (715, 335), (810, 335))
    arrow(draw, (1080, 310), (1175, 275), GREEN)
    arrow(draw, (1080, 370), (1175, 545), RED)
    draw.rounded_rectangle((190, 705, 1410, 845), radius=18, fill="#FFFFFF", outline=ORANGE, width=4)
    draw.text((235, 730), "读图要点", font=HEAD, fill=ORANGE)
    draw.text((235, 785), "页面不能只显示最终结论；每个模型句子都要能回到页面字段或 API 输出。", font=BODY, fill=INK)
    img.save(OUT / "chapter-25-kline-llm-binding.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_risk_order_gate()
    save_research_ia_path()
    save_market_candidate_path()
    save_kline_llm_binding()
    for name in (
        "chapter-22-risk-order-gate.png",
        "chapter-23-research-ia-path.png",
        "chapter-24-market-candidate-path.png",
        "chapter-25-kline-llm-binding.png",
    ):
        print(OUT / name)


if __name__ == "__main__":
    main()
