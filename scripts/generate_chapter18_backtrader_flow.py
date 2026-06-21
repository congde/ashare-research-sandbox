#!/usr/bin/env python3
"""PIL flow diagram: Qbot cerebro assembly vs local rolling engine (03-backtrader.ipynb)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from generate_chapter01_figures import OUT, arrow, center, font, rounded, sb
from print_figure_config import PRINT_DPI, scale

ROOT = Path(__file__).resolve().parents[1]


def backtrader_vs_local() -> Path:
    image = Image.new("RGB", sb(1600, 1040), "#f7f9fc")
    draw = ImageDraw.Draw(image)
    draw.text(sb(56, 36), "Backtrader Cerebro 装配 vs 本仓库事件引擎", font=font(40), fill="#0f172a")
    draw.text(
        sb(58, 92),
        "参考 vendor/Qbot/docs/notebook/03-backtrader.ipynb · 只借装配顺序，不迁入 backtrader 框架",
        font=font(22),
        fill="#64748b",
    )

    rounded(draw, sb(48, 150, 780, 210), "#eff6ff", "#2563eb", width=3)
    center(
        draw,
        sb(48, 150, 780, 210),
        "vendor/Qbot · cerebro 装配（只读对照 · 不 import 进 src/）",
        font(24),
        fill=(30, 64, 175),
    )

    qbot_steps = [
        "1. cerebro = bt.Cerebro()",
        "2. broker.setcash / setcommission / set_slippage",
        "3. cerebro.adddata(feed)",
        "4. cerebro.addstrategy(Strategy)",
        "5. addanalyzer(Sharpe, DrawDown, TimeReturn…)",
        "6. cerebro.run()  →  broker 撮合",
        "7. cerebro.plot() / analyzer 指标",
    ]
    y = scale(240)
    step_h = scale(62)
    gap = scale(78)
    for step in qbot_steps:
        box = (scale(70), y, scale(760), y + step_h)
        rounded(draw, box, "#ffffff", "#93c5fd", width=2, radius=14)
        center(draw, box, step, font(21), fill=(30, 41, 59))
        if y + step_h < scale(240) + (len(qbot_steps) - 1) * gap:
            arrow(draw, (scale(415), y + scale(64)), (scale(415), y + scale(76)), color=(37, 99, 235), width=4)
        y += gap

    rounded(draw, sb(820, 150, 1552, 210), "#ecfdf5", "#059669", width=3)
    center(
        draw,
        sb(820, 150, 1552, 210),
        "src/backtest/rolling · 事件驱动引擎（课程产品路径）",
        font(24),
        fill=(6, 95, 70),
    )

    local_steps = [
        "1. load_candles() 固定样本",
        "2. BacktestConfig + get_strategy()",
        "3. run_backtest() 逐 K 事件循环",
        "4. pending 挂单 · RiskManager 拒绝",
        "5. trades[] 成交明细",
        "6. equity_curve[] 盯市权益",
        "7. execute_backtest() / Web Backtests",
    ]
    y = scale(240)
    for step in local_steps:
        box = (scale(842), y, scale(1532), y + step_h)
        rounded(draw, box, "#ffffff", "#86efac", width=2, radius=14)
        center(draw, box, step, font(21), fill=(30, 41, 59))
        if y + step_h < scale(240) + (len(local_steps) - 1) * gap:
            arrow(
                draw,
                (scale(1187), y + scale(64)),
                (scale(1187), y + scale(76)),
                color=(5, 150, 105),
                width=4,
            )
        y += gap

    pairs = [
        (sb(760, 270), sb(842, 270), "数据"),
        (sb(760, 426), sb(842, 426), "策略"),
        (sb(760, 582), sb(842, 582), "运行"),
        (sb(760, 738), sb(842, 738), "证据"),
    ]
    for start, end, label in pairs:
        arrow(draw, start, end, color=(100, 116, 139), width=3)
        mid_x = (start[0] + end[0]) // 2 - scale(24)
        draw.text((mid_x, start[1] - scale(28)), label, font=font(18), fill="#475569")

    rounded(draw, sb(48, 860, 780, 980), "#fef2f2", "#dc2626", width=3)
    center(
        draw,
        sb(48, 870, 780, 975),
        "不能证明：cerebro 输出 = 本引擎输出\n"
        "backtrader 全栈不迁入 · 见 vendor/QBOT_AUDIT.md",
        font(22),
        fill=(153, 27, 27),
    )

    rounded(draw, sb(820, 860, 1552, 980), "#f0fdf4", "#16a34a", width=3)
    center(
        draw,
        sb(820, 870, 1552, 975),
        "能证明：装配顺序可对照阅读\n"
        "本仓库保留 trace / trades / equity 可审计路径",
        font(22),
        fill=(21, 128, 61),
    )

    draw.text(
        sb(56, 1000),
        "教学样本 · 不进入实盘执行 · 300 DPI 概念图（非运行时序图）",
        font=font(18),
        fill="#64748b",
    )

    out = OUT / "chapter-18-backtrader-vs-local.png"
    image.save(out, dpi=(PRINT_DPI, PRINT_DPI))
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    path = backtrader_vs_local()
    print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
