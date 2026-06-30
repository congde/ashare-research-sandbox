"""Generate Chapter 35 publication figures."""

from __future__ import annotations

from pathlib import Path
import re
from textwrap import fill

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"

BLUE = "#2563EB"
TEAL = "#0F9B8E"
ORANGE = "#F59E0B"
RED = "#DC2626"
PURPLE = "#7C3AED"
INK = "#111827"
MUTED = "#64748B"
GRID = "#E5E7EB"
PAPER = "#F7F9FC"


def setup_matplotlib() -> None:
    plt.rcParams["font.sans-serif"] = [
        "SimHei",
        "Microsoft YaHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def save_acceptance_retro_loop() -> None:
    steps = [
        ("验收\n命令", "verify / check"),
        ("证据\n归档", "report / rubric"),
        ("剩余\n风险", "known limits"),
        ("迭代\nbacklog", "fix before features"),
        ("复跑\n放行", "same command set"),
    ]
    colors = [BLUE, TEAL, ORANGE, RED, PURPLE]
    fig, ax = plt.subplots(figsize=(12.8, 5.2), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(
        0.04,
        0.9,
        "最终验收不是句号，而是把证据、风险和下一轮动作放进同一个闭环",
        transform=ax.transAxes,
        fontsize=15,
        color=INK,
        weight="bold",
    )
    width = 0.14
    for i, ((title, body), color) in enumerate(zip(steps, colors, strict=True)):
        x = 0.06 + i * 0.18
        ax.add_patch(
            Rectangle(
                (x, 0.38),
                width,
                0.28,
                transform=ax.transAxes,
                facecolor="#FFFFFF",
                edgecolor=color,
                linewidth=2,
            )
        )
        ax.text(x + width / 2, 0.56, title, transform=ax.transAxes, ha="center", va="center", fontsize=13, color=color, weight="bold")
        ax.text(x + width / 2, 0.43, body, transform=ax.transAxes, ha="center", va="center", fontsize=9.3, color=INK)
        if i < len(steps) - 1:
            ax.add_patch(
                FancyArrowPatch(
                    (x + width + 0.012, 0.52),
                    (x + 0.18 - 0.014, 0.52),
                    transform=ax.transAxes,
                    arrowstyle="-|>",
                    mutation_scale=13,
                    linewidth=1.6,
                    color=MUTED,
                )
            )
    ax.add_patch(
        FancyArrowPatch(
            (0.78, 0.32),
            (0.13, 0.32),
            transform=ax.transAxes,
            connectionstyle="arc3,rad=-0.35",
            arrowstyle="-|>",
            mutation_scale=14,
            linewidth=1.6,
            color=MUTED,
        )
    )
    ax.text(0.38, 0.18, "任一硬门禁失败，都回到修复和复跑；不能把未验证写成已通过。", transform=ax.transAxes, fontsize=10.5, color=MUTED)
    fig.savefig(OUT / "chapter-35-acceptance-retro-loop.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-35-acceptance-retro-loop.png")


def save_verification_stack() -> None:
    rows = [
        ("verify.py", "前端构建、交付物、报告边界、vendor 基线、pytest"),
        ("scripts/course.py verify", "跨平台调用 verify.py，统一虚拟环境和 PYTHONPATH"),
        ("scripts/course.py check", "verify + vendor-drift + asset-audit + courseware-check"),
        ("scripts/verify_courseware.py", "章节结构、图表编号、代码编号、本地链接"),
        ("eval-rubric.md", "来源、复算、风险、安全边界、接手评分"),
    ]
    fig, ax = plt.subplots(figsize=(12.6, 6.1), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.92, "验收栈要从产品可跑，一直查到章节可出版", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    y0 = 0.8
    for i, (name, desc) in enumerate(rows):
        y = y0 - i * 0.13
        color = [BLUE, TEAL, PURPLE, ORANGE, RED][i]
        ax.add_patch(Rectangle((0.05, y), 0.24, 0.09, transform=ax.transAxes, facecolor=color, edgecolor=color))
        ax.add_patch(Rectangle((0.29, y), 0.62, 0.09, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=GRID))
        ax.text(0.065, y + 0.047, name, transform=ax.transAxes, fontsize=10.6, color="#FFFFFF", va="center", weight="bold")
        ax.text(0.31, y + 0.047, desc, transform=ax.transAxes, fontsize=10.2, color=INK, va="center")
    ax.text(0.05, 0.08, "实战写法：报告只引用已运行命令的真实结果；未运行项进入 remaining risk。", transform=ax.transAxes, fontsize=10.5, color=MUTED)
    fig.savefig(OUT / "chapter-35-verification-stack.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-35-verification-stack.png")


def save_courseware_coverage() -> None:
    chapters = sorted((ROOT / "docs" / "v2").glob("[0-3][0-9]-*.md"))
    numbers: list[int] = []
    image_counts: list[int] = []
    table_counts: list[int] = []
    code_counts: list[int] = []
    for path in chapters:
        match = re.match(r"^(\d+)-", path.name)
        if not match:
            continue
        number = int(match.group(1))
        if number > 35:
            continue
        text = path.read_text(encoding="utf-8")
        numbers.append(number)
        image_counts.append(len(re.findall(r"^!\[[^\]]+\]\([^)]+\)\s*$", text, re.MULTILINE)))
        table_counts.append(len(re.findall(r"^\*\*表\s+\d+-\d+", text, re.MULTILINE)))
        code_counts.append(len(re.findall(r"^\*\*代码\s+\d+-\d+", text, re.MULTILINE)))
    fig, ax = plt.subplots(figsize=(13.2, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.plot(numbers, image_counts, color=BLUE, marker="o", linewidth=1.8, label="figures")
    ax.plot(numbers, table_counts, color=TEAL, marker="s", linewidth=1.8, label="tables")
    ax.plot(numbers, code_counts, color=ORANGE, marker="^", linewidth=1.8, label="code")
    ax.axvline(35, color=RED, linestyle="--", linewidth=1.2)
    ax.set_xlabel("章节")
    ax.set_ylabel("数量")
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=3)
    ax.text(0.0, -0.18, f"当前纳入统计的章节数：{len(numbers)}；最终验收章至少要保留命令、矩阵和复盘图。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-35-courseware-coverage.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-35-courseware-coverage.png")


def save_evidence_pack_matrix() -> None:
    rows = ["数据", "信号", "回测", "风控", "Eval", "Web", "接手"]
    cols = ["命令", "来源", "失败", "边界", "下一步"]
    values = np.array(
        [
            [1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1],
            [1, 1, 0.7, 1, 1],
            [1, 1, 1, 1, 1],
        ]
    )
    fig, ax = plt.subplots(figsize=(9.8, 6.3), dpi=160)
    fig.patch.set_facecolor(PAPER)
    im = ax.imshow(values, cmap="YlGnBu", vmin=0, vmax=1)
    ax.set_xticks(np.arange(len(cols)), cols)
    ax.set_yticks(np.arange(len(rows)), rows)
    for y in range(len(rows)):
        for x in range(len(cols)):
            label = "已写清" if values[y, x] >= 1 else "需复核"
            ax.text(x, y, label, ha="center", va="center", fontsize=9, color=INK)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("证据完整度")
    fig.tight_layout()
    fig.savefig(OUT / "chapter-35-evidence-pack-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-35-evidence-pack-matrix.png")


def save_risk_backlog_priority() -> None:
    items = [
        ("真实账户/下单", 0.95, 0.75, RED),
        ("样本外窗口", 0.82, 0.48, ORANGE),
        ("页面字段追源", 0.66, 0.34, BLUE),
        ("失败注入样本", 0.74, 0.42, PURPLE),
        ("出版图表复核", 0.45, 0.26, TEAL),
        ("Vite chunk 警告", 0.34, 0.38, MUTED),
    ]
    fig, ax = plt.subplots(figsize=(10.6, 6.4), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.axhspan(0, 0.45, color="#ECFDF5", alpha=0.7)
    ax.axhspan(0.45, 1, color="#FEF2F2", alpha=0.55)
    ax.axvspan(0, 0.55, color="#FFFFFF", alpha=0.65)
    ax.axvspan(0.55, 1, color="#F8FAFC", alpha=0.7)
    for label, impact, effort, color in items:
        ax.scatter(effort, impact, s=150, color=color, edgecolor="#FFFFFF", linewidth=1.5)
        ax.text(effort + 0.018, impact + 0.012, fill(label, 9), fontsize=9.5, color=INK)
    ax.set_xlim(0.15, 0.95)
    ax.set_ylim(0.25, 1.02)
    ax.set_xlabel("修复成本")
    ax.set_ylabel("对结论可信度的影响")
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(0.16, 0.98, "优先补证据", fontsize=10, color=RED, weight="bold")
    ax.text(0.16, 0.29, "可排期清理", fontsize=10, color=TEAL, weight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "chapter-35-risk-backlog-priority.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-35-risk-backlog-priority.png")


def save_handoff_command_card() -> None:
    commands = [
        ("python scripts/generate_chapter35_figures.py", "重画本章 6 张 Python 图"),
        ("python -m pytest tests/test_final_acceptance_contract.py -q", "复核最终验收入口"),
        ("python scripts/verify_courseware.py", "检查出版结构与本地链接"),
        ("python scripts/course.py verify", "跑产品、报告、前端和测试"),
        ("python scripts/course.py check", "跑完整仓库验收栈"),
    ]
    fig, ax = plt.subplots(figsize=(12.8, 6.0), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.92, "交接时不要只说“能跑”，要给下一位接手者一组可复制命令", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    y = 0.79
    for idx, (command, purpose) in enumerate(commands, start=1):
        bg = "#FFFFFF" if idx % 2 else "#F1F5F9"
        ax.add_patch(Rectangle((0.05, y), 0.88, 0.1, transform=ax.transAxes, facecolor=bg, edgecolor=GRID))
        ax.add_patch(Rectangle((0.05, y), 0.06, 0.1, transform=ax.transAxes, facecolor=BLUE if idx < 5 else RED, edgecolor=GRID))
        ax.text(0.08, y + 0.05, str(idx), transform=ax.transAxes, ha="center", va="center", color="#FFFFFF", weight="bold")
        ax.text(0.13, y + 0.063, command, transform=ax.transAxes, fontsize=10.3, color=INK, va="center", family="monospace")
        ax.text(0.13, y + 0.028, purpose, transform=ax.transAxes, fontsize=9.6, color=MUTED, va="center")
        y -= 0.12
    ax.text(0.05, 0.08, "验收报告只写本轮实际运行过的结果；没有运行的命令进入待复核项。", transform=ax.transAxes, fontsize=10.5, color=MUTED)
    fig.savefig(OUT / "chapter-35-handoff-command-card.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-35-handoff-command-card.png")


def main() -> None:
    setup_matplotlib()
    OUT.mkdir(parents=True, exist_ok=True)
    save_acceptance_retro_loop()
    save_verification_stack()
    save_courseware_coverage()
    save_evidence_pack_matrix()
    save_risk_backlog_priority()
    save_handoff_command_card()


if __name__ == "__main__":
    main()
