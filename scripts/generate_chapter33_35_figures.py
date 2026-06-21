"""Generate focused Chinese teaching figures for chapters 33 through 35."""

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
BG = "#F7F9FC"
INK = "#111827"
MUTED = "#64748B"
BLUE = "#2563EB"
TEAL = "#0F9B8E"
ORANGE = "#F59E0B"
RED = "#DC2626"
GREEN = "#15803D"
PANEL = "#FFFFFF"


def box(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], title: str, body: str, color: str, fill: str = PANEL) -> None:
    draw.rounded_rectangle(rect, radius=18, fill=fill, outline=color, width=4)
    x, y, _, _ = rect
    draw.text((x + 24, y + 20), title, font=HEAD, fill=color)
    draw.multiline_text((x + 24, y + 72), body, font=BODY, fill=INK, spacing=8)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str = MUTED) -> None:
    draw.line([start, end], fill=color, width=5)
    ex, ey = end
    sign = 1 if ex >= start[0] else -1
    draw.polygon([(ex, ey), (ex - sign * 18, ey - 11), (ex - sign * 18, ey + 11)], fill=color)


def flow(filename: str, title: str, subtitle: str, steps: list[tuple[str, str]], note: str) -> None:
    img = Image.new("RGB", (1600, 920), BG)
    draw = ImageDraw.Draw(img)
    draw.text((70, 48), title, font=TITLE, fill=INK)
    draw.text((70, 108), subtitle, font=BODY, fill=MUTED)
    rects = [(70, 270, 330, 440), (425, 270, 685, 440), (780, 270, 1040, 440), (1135, 210, 1510, 375), (1135, 485, 1510, 650)]
    colors = [BLUE, TEAL, ORANGE, GREEN, RED]
    fills = [PANEL, PANEL, PANEL, "#ECFDF5", "#FEF2F2"]
    for rect, (title_i, body_i), color, fill in zip(rects, steps, colors, fills):
        box(draw, rect, title_i, body_i, color, fill)
    arrow(draw, (330, 355), (425, 355))
    arrow(draw, (685, 355), (780, 355))
    arrow(draw, (1040, 330), (1135, 292), GREEN)
    arrow(draw, (1040, 390), (1135, 565), RED)
    draw.rounded_rectangle((190, 715, 1410, 845), radius=18, fill="#FFFFFF", outline=BLUE, width=4)
    draw.text((235, 740), "读图要点", font=HEAD, fill=BLUE)
    draw.text((235, 795), note, font=BODY, fill=INK)
    img.save(OUT / filename)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    items = [
        (
            "chapter-33-sim-trading-boundary.png",
            "第 33 讲：端到端模拟交易边界",
            "模拟交易验证流程完整性，不验证真实可交易收益。",
            [("数据", "快照、样本\n来源状态"), ("信号策略", "规则、仓位\n禁止真实订单"), ("回测风控", "成本、拒绝\n权益曲线"), ("研究通过", "流程可复查"), ("停止", "越过实盘\n证据缺失")],
            "模拟系统的价值是让数据、信号、回测、风险和页面能互相对账。",
        ),
        (
            "chapter-34-research-path-contracts.png",
            "第 34 讲：贯通研究路径合同",
            "全链路不是一次跑通，而是每一段都有输入、输出、指标和停止线。",
            [("信号", "score\nevidence"), ("策略回测", "trades\nequity"), ("审计风控", "DSR、PBO\nrisk_id"), ("页面验收", "字段一致"), ("退回修复", "合同断裂")],
            "端到端验收要能从页面字段反查到 API、回测结果和风险记录。",
        ),
        (
            "chapter-35-acceptance-retro-loop.png",
            "第 35 讲：验收复盘与下一轮迭代",
            "最终验收看可接手性；复盘要把失败转成下一轮任务。",
            [("全量检查", "verify\ncourse check"), ("验收包", "报告、截图\n命令记录"), ("复盘", "保留问题\n下一轮"), ("交付通过", "可接手"), ("拒绝发布", "硬门禁失败")],
            "硬门禁失败不能被平均分抵消；复盘输出应成为下一轮可执行任务。",
        ),
    ]
    for item in items:
        flow(*item)
        print(OUT / item[0])


if __name__ == "__main__":
    main()
