"""Generate Chapter 30 publication figures."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
from textwrap import fill

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from risk import DEFAULT_RULE_IDS, ExecutionBoundaryRequest, classify_execution_request, default_risk_manager  # noqa: E402


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


def save_approval_stop_gate() -> None:
    steps = [
        ("研究输出", "signal / draft\nsource card"),
        ("执行边界", "classify()\n先分类"),
        ("人工确认", "dry-run only\n显式确认"),
        ("风险规则", "RiskManager\n五条规则"),
        ("阈值补丁", "patch_threshold\n白名单字段"),
        ("停止线", "real_order / halt\n直接阻断"),
    ]
    colors = [BLUE, TEAL, ORANGE, PURPLE, "#0891B2", RED]
    fig, ax = plt.subplots(figsize=(13.8, 4.9), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "高风险动作先过执行边界，再过风险规则；真实交易动作直接停止", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    width = 0.13
    gap = 0.026
    for i, ((title, body), color) in enumerate(zip(steps, colors, strict=True)):
        x = 0.04 + i * (width + gap)
        ax.add_patch(Rectangle((x, 0.34), width, 0.38, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.text(x + 0.012, 0.64, title, transform=ax.transAxes, fontsize=10.6, color=color, weight="bold")
        ax.text(x + 0.012, 0.54, body, transform=ax.transAxes, fontsize=8.6, color=INK, va="top")
        if i < len(steps) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.005, 0.53), (x + width + gap - 0.006, 0.53), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=13, linewidth=1.6, color=MUTED))
    ax.text(0.04, 0.15, "对应代码：src/risk/execution_boundary.py、src/risk/manager.py、src/risk/config.py。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-30-approval-stop-gate.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-30-approval-stop-gate.png")


def _boundary_scenarios() -> list[dict[str, object]]:
    scenarios = [
        ExecutionBoundaryRequest("BTC/USDT", "BUY", "record_signal", capability="none"),
        ExecutionBoundaryRequest("BTC/USDT", "BUY", "dry_run_order", capability="none"),
        ExecutionBoundaryRequest("BTC/USDT", "BUY", "dry_run_order", capability="simulation_only", human_confirmed=False),
        ExecutionBoundaryRequest("BTC/USDT", "BUY", "dry_run_order", capability="simulation_only", human_confirmed=True),
        ExecutionBoundaryRequest("BTC/USDT", "BUY", "real_order", capability="simulation_only", human_confirmed=True),
        ExecutionBoundaryRequest("BTC/USDT", "BUY", "real_order", capability="real_order", human_confirmed=True),
    ]
    rows = []
    for request in scenarios:
        result = classify_execution_request(request)
        rows.append(
            {
                "label": f"{request.requested_action}\n{request.capability}\nconfirm={request.human_confirmed}",
                "score": {"research_record": 1, "dry_run": 2, "blocked": 3}[result.outcome],
                "outcome": result.outcome,
                "allowed": result.allowed,
            }
        )
    return rows


def save_boundary_outcomes() -> None:
    rows = _boundary_scenarios()
    colors = [TEAL if row["outcome"] == "research_record" else ORANGE if row["outcome"] == "dry_run" else RED for row in rows]
    fig, ax = plt.subplots(figsize=(12.8, 5.7), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    labels = [str(row["label"]) for row in rows]
    scores = [int(row["score"]) for row in rows]
    ax.bar(labels, scores, color=colors)
    ax.set_yticks([1, 2, 3])
    ax.set_yticklabels(["research_record", "dry_run", "blocked"])
    ax.set_ylim(0, 3.5)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", labelsize=8.2)
    for i, row in enumerate(rows):
        ax.text(i, scores[i] + 0.08, str(row["outcome"]), ha="center", fontsize=8.5, color=INK)
    ax.text(0.0, -0.24, "数据来自 classify_execution_request()：未确认 dry-run 会降级；real_order 无论是否确认都 blocked。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-30-boundary-outcomes.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-30-boundary-outcomes.png")


def save_risk_rule_stack() -> None:
    rule_ids = list(DEFAULT_RULE_IDS)
    severities = [5, 4, 3, 2, 2]
    colors = [RED, PURPLE, ORANGE, BLUE, TEAL]
    fig, ax = plt.subplots(figsize=(11.8, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    y = list(range(len(rule_ids)))
    ax.barh(y, severities, color=colors)
    ax.set_yticks(y)
    ax.set_yticklabels(rule_ids)
    ax.invert_yaxis()
    ax.set_xticks([1, 2, 3, 4, 5])
    ax.set_xticklabels(["提示", "异常", "成本", "敞口", "停止"])
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for i, value in enumerate(severities):
        ax.text(value + 0.08, i, "先命中先阻断" if i == 0 else "风险门", va="center", fontsize=9, color=INK)
    ax.text(0.0, -0.17, "default_risk_manager() 将 KillSwitch 放在第一位；RiskManager.check() 遇到第一条拒绝规则就短路返回。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-30-risk-rule-stack.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-30-risk-rule-stack.png")


def save_threshold_patch_gate() -> None:
    rows = [
        ("MAX_DAILY_LOSS_PCT.max_drawdown_pct", "允许", "Decimal > 0"),
        ("MAX_POSITION_PCT.max_notional_usd", "允许", "Decimal > 0"),
        ("MAX_SLIPPAGE_PCT.max_spread_pct", "允许", "Decimal > 0"),
        ("ABNORMAL_ORDERBOOK.max_price_jump_pct", "允许", "Decimal > 0"),
        ("UNKNOWN_RULE.max_drawdown_pct", "拒绝", "unknown rule"),
        ("MAX_DAILY_LOSS_PCT.bad_field", "拒绝", "not patchable"),
        ("MAX_DAILY_LOSS_PCT.max_drawdown_pct=-1", "拒绝", "must be positive"),
    ]
    fig, ax = plt.subplots(figsize=(12.4, 5.9), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.91, "风险阈值补丁不是任意写配置：规则、字段和值都要过门禁", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    col_x = [0.04, 0.53, 0.68]
    col_w = [0.45, 0.11, 0.24]
    headers = ["补丁请求", "结果", "原因"]
    y0 = 0.78
    row_h = 0.095
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.075, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.01, y0 + 0.049, header, transform=ax.transAxes, fontsize=10.2, color="#FFFFFF", weight="bold", va="center")
    for r, row in enumerate(rows):
        y = y0 - (r + 1) * row_h
        bg = "#FFFFFF" if r % 2 == 0 else "#F1F5F9"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=bg, edgecolor=GRID, linewidth=1))
            color = TEAL if value == "允许" else RED if value == "拒绝" else INK
            ax.text(x + 0.01, y + row_h * 0.58, fill(value, 36), transform=ax.transAxes, fontsize=9.4, color=color, va="center")
    ax.text(0.04, 0.04, "对应实现：RiskManager.patch_threshold() 只接受 _PATCHABLE_FIELDS 中的字段，并拒绝非正阈值。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-30-threshold-patch-gate.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-30-threshold-patch-gate.png")


def save_stopline_trigger_matrix() -> None:
    columns = ["自动", "审批", "停止"]
    rows = [
        ("读取离线样本", [1, 0, 0]),
        ("生成研究草稿", [1, 0, 0]),
        ("确认 dry-run", [0, 1, 0]),
        ("修改风险阈值", [0, 1, 0]),
        ("真实订单请求", [0, 0, 1]),
        ("KillSwitch 已触发", [0, 0, 1]),
        ("未知规则补丁", [0, 0, 1]),
    ]
    fig, ax = plt.subplots(figsize=(10.8, 6.0), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    for y, (_, values) in enumerate(rows):
        for x, value in enumerate(values):
            color = [TEAL, ORANGE, RED][x] if value else "#E2E8F0"
            ax.add_patch(Rectangle((x, y), 1, 1, facecolor=color, edgecolor="#FFFFFF", linewidth=2))
            ax.text(x + 0.5, y + 0.5, "yes" if value else "", ha="center", va="center", fontsize=9, color="#FFFFFF" if value else MUTED)
    ax.set_xlim(0, len(columns))
    ax.set_ylim(0, len(rows))
    ax.set_xticks([i + 0.5 for i in range(len(columns))])
    ax.set_xticklabels(columns)
    ax.set_yticks([i + 0.5 for i in range(len(rows))])
    ax.set_yticklabels([row[0] for row in rows])
    ax.invert_yaxis()
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.text(0.0, -0.14, "停止线比审批更强：real_order、KillSwitch、未知规则补丁不进入“补材料后通过”，而是直接阻断。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-30-stopline-trigger-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-30-stopline-trigger-matrix.png")


def save_verification_ladder() -> None:
    tests = [
        ("execution boundary", 4, "real_order blocked"),
        ("risk manager", 12, "5 rules + rejection"),
        ("approval contract", 4, "chapter gate"),
        ("course verify", 124, "repo-wide"),
    ]
    labels = [item[0] for item in tests]
    counts = [item[1] for item in tests]
    fig, ax = plt.subplots(figsize=(11.4, 5.5), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar(labels, counts, color=[TEAL, BLUE, ORANGE, PURPLE])
    ax.set_ylabel("覆盖点 / 测试数")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for i, (_, count, note) in enumerate(tests):
        ax.text(i, count + max(counts) * 0.03, note, ha="center", fontsize=9, color=INK)
    ax.text(0.0, -0.19, "局部测试覆盖边界和风险规则；最终仍以 python scripts/course.py verify 作为课程级验收。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-30-verification-ladder.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-30-verification-ladder.png")


def main() -> None:
    setup_matplotlib()
    OUT.mkdir(parents=True, exist_ok=True)
    # Touch default manager so figure generation fails if rule ids drift.
    assert tuple(rule.rule_id for rule in default_risk_manager(initial_capital=Decimal("10000")).rules) == DEFAULT_RULE_IDS
    save_approval_stop_gate()
    save_boundary_outcomes()
    save_risk_rule_stack()
    save_threshold_patch_gate()
    save_stopline_trigger_matrix()
    save_verification_ladder()


if __name__ == "__main__":
    main()
