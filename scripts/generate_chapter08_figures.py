"""Generate Chapter 08 publication figures."""

from __future__ import annotations

import json
import textwrap
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from matplotlib import pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets"
DATA = ROOT / "data" / "dashboard" / "market_candles.json"
FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if FONT_PATH.is_file():
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


def box(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    title: str,
    body: str,
    color: str,
    *,
    body_font: ImageFont.ImageFont = BODY,
) -> None:
    x1, y1, _, _ = xy
    draw.rounded_rectangle(xy, radius=18, fill=PANEL, outline=color, width=4)
    draw.text((x1 + 24, y1 + 22), title, font=HEAD, fill=color)
    draw.multiline_text((x1 + 24, y1 + 74), body, font=body_font, fill=INK, spacing=7)


def save_cleaning_gates() -> None:
    img = Image.new("RGB", (1760, 940), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 8 章：时间序列清洗门禁", font=TITLE, fill=INK)
    draw.text((80, 116), "清洗不是美化数据，而是决定哪些记录有资格进入指标、大语言模型摘要或回测。", font=BODY, fill=MUTED)

    steps = [
        ((80, 260, 360, 455), "原始记录", "保留原字段\n不先改写含义", BLUE),
        ((475, 260, 755, 455), "字段契约", "时间、价格、来源\n缺一项要说明", TEAL),
        ((870, 260, 1150, 455), "时间顺序", "排序规则可复查\n重复不能静默覆盖", TEAL),
        ((1265, 260, 1545, 455), "用途放行", "展示 / 指标 / 回测\n分层决定", ORANGE),
    ]
    for xy, title, body, color in steps:
        box(draw, xy, title, body, color)
    for x in (360, 755, 1150):
        arrow(draw, (x, 358), (x + 115, 358))

    draw.rounded_rectangle((220, 610, 1540, 790), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((265, 638), "停止线", font=HEAD, fill=RED)
    draw.multiline_text(
        (265, 695),
        "为了画出连续曲线而自动填补所有缺失值，会把未知伪装成事实；若补值改变收益、指标或买卖点，先记录规则，再判断用途。",
        font=BODY,
        fill=INK,
        spacing=8,
    )
    output = OUT / "chapter-08-cleaning-gates.png"
    img.save(output)
    print(output)


def save_normalization_trace() -> None:
    img = Image.new("RGB", (1840, 980), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 8 章实战：标准化字段追溯路径", font=TITLE, fill=INK)
    draw.text((80, 116), "页面字段越友好，越要能反向追到原始字段、转换规则和缺失处理。", font=BODY, fill=MUTED)

    steps = [
        ((80, 245, 390, 445), "原始数据包", "ai_picks\nchance / funds / risk\ntoken_fund\nfund / sentiment / ratio", BLUE),
        ((505, 245, 815, 445), "normalize.py", "_to_float()\nnormalize_ai_picks()\nnormalize_token_fund()", TEAL),
        ((930, 245, 1240, 445), "展示字段", "title\nsummary\nnetInflow24h\nsentiment.score", ORANGE),
        ((1355, 245, 1665, 445), "接口 / 页面", "可读卡片\n缺失状态\n来源仍可追", PURPLE),
    ]
    for xy, title, body, color in steps:
        box(draw, xy, title, body, color, body_font=SMALL)
    for x in (390, 815, 1240):
        arrow(draw, (x, 345), (x + 115, 345))

    draw.rounded_rectangle((165, 585, 1675, 825), radius=18, fill="#FFFFFF", outline=GRID, width=3)
    draw.text((205, 615), "反向复核", font=HEAD, fill=INK)
    rows = [
        ("页面摘要", "回到接口输出，确认它不是模型补写"),
        ("接口字段", "回到标准化函数，确认转换规则"),
        ("标准化字段", "回到原始字段，确认来源和缺失状态"),
        ("无法追溯", "降级为展示文本，不进入研究结论"),
    ]
    y = 675
    for label, desc in rows:
        draw.text((215, y), label, font=BODY, fill=BLUE)
        draw.text((470, y), desc, font=BODY, fill=INK)
        y += 43

    draw.rounded_rectangle((390, 865, 1450, 935), radius=18, fill="#FFF7ED", outline=ORANGE, width=4)
    draw.text((425, 886), "标准化只改变表达形状，不创造新的市场事实。", font=BODY, fill=ORANGE)
    output = OUT / "chapter-08-normalization-trace.png"
    img.save(output)
    print(output)


def save_pollution_matrix() -> None:
    img = Image.new("RGB", (1840, 1020), BG)
    draw = ImageDraw.Draw(img)
    draw.text((80, 55), "第 8 章实战：污染样本处理矩阵", font=TITLE, fill=INK)
    draw.text((80, 116), "成功样本只能证明正常路径；污染样本才能证明系统知道何时降级或拒绝。", font=BODY, fill=MUTED)

    headers = ["污染输入", "错误处理", "合格处理", "结论边界"]
    xs = [100, 500, 900, 1300]
    widths = [360, 360, 360, 420]
    colors = [BLUE, RED, TEAL, ORANGE]
    for x, w, h, c in zip(xs, widths, headers, colors):
        draw.rounded_rectangle((x, 230, x + w, 300), radius=14, fill=c)
        draw.text((x + 22, 249), h, font=HEAD, fill="#FFFFFF")

    rows = [
        ("重复时间戳", "静默覆盖", "保留规则或拒绝原因", "不能直接计算收益"),
        ("逆序记录", "按原顺序算指标", "排序规则可复查", "排序前后都要记录"),
        ("close 缺失", "自动填 0", "保留缺失或拒绝", "可展示但不可回测"),
        ("N/A 字符串", "当作有效数字", "转换失败为 None", "不让模型猜值"),
    ]
    y = 335
    for row in rows:
        row_h = 118
        for idx, text in enumerate(row):
            x, w, c = xs[idx], widths[idx], colors[idx]
            draw.rounded_rectangle((x, y, x + w, y + row_h), radius=14, fill=PANEL, outline=c, width=3)
            draw.multiline_text((x + 22, y + 28), wrap(text, 14), font=BODY, fill=INK, spacing=5)
        y += row_h + 22

    draw.rounded_rectangle((300, 895, 1540, 970), radius=18, fill="#FEF2F2", outline=RED, width=4)
    draw.text((340, 918), "如果污染样本仍能产出漂亮图表，说明清洗流程正在隐藏证据缺口。", font=BODY, fill=RED)
    output = OUT / "chapter-08-pollution-matrix.png"
    img.save(output)
    print(output)


def moving_average(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            out.append(None)
            continue
        sample = values[index + 1 - window : index + 1]
        out.append(sum(sample) / window)
    return out


def save_kline_quality_curve() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    candles = sorted(payload.get("candles") or [], key=lambda row: row.get("tsSec") or 0)
    dates = [datetime.fromisoformat(str(row["date"])) for row in candles if row.get("date") and row.get("close") is not None]
    closes = [float(row["close"]) for row in candles if row.get("date") and row.get("close") is not None]
    ma3 = moving_average(closes, 3)
    ma7 = moving_average(closes, 7)

    plt.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans", "Arial", "sans-serif"],
            "axes.unicode_minus": False,
            "figure.facecolor": "#FCFCFD",
            "axes.facecolor": "#FFFFFF",
            "axes.edgecolor": "#D7DBE7",
            "axes.grid": True,
            "grid.color": "#E6E8F0",
        }
    )
    fig, ax = plt.subplots(figsize=(13, 7), dpi=160)
    ax.plot(dates, closes, color=BLUE, linewidth=1.8, label="标准化收盘价 close")
    ax.plot(dates, ma3, color=TEAL, linewidth=1.6, label="3 日均线")
    ax.plot(dates, ma7, color=ORANGE, linewidth=1.6, label="7 日均线")
    ax.scatter(dates, closes, color=BLUE, s=18, alpha=0.65)
    ax.set_title("第 8 章：K 线字段标准化后的收盘价与均线", loc="left", fontsize=15, fontweight="semibold", color=INK)
    ax.set_ylabel("价格")
    ax.set_xlabel("日期")
    ax.legend(frameon=False, ncol=3, loc="upper left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.text(
        0.125,
        0.02,
        "来源：data/dashboard/market_candles.json。曲线只证明字段可排序、可转换、可复算，不证明行情方向或交易机会。",
        fontsize=9.5,
        color=MUTED,
    )
    output = OUT / "chapter-08-kline-quality-curve.png"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    print(output)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_cleaning_gates()
    save_normalization_trace()
    save_pollution_matrix()
    save_kline_quality_curve()


if __name__ == "__main__":
    main()
