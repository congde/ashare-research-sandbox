"""Generate Chapter 28 publication figures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys
from textwrap import fill
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SKILL_PATH = ROOT / "skills" / "research-report-check" / "SKILL.md"
AGENT_PATH = ROOT / "skills" / "research-report-check" / "agents" / "openai.yaml"

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


def read_skill() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def parse_skill_contract(text: str) -> dict[str, Any]:
    frontmatter = {}
    if text.startswith("---"):
        _, raw, _body = text.split("---", 2)
        for line in raw.strip().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                frontmatter[key.strip()] = value.strip()
    headings = re.findall(r"^##\s+(.+)$", text, re.MULTILINE)
    workflow = re.findall(r"^\d+\.\s+(.+)$", text, re.MULTILINE)
    bullets = re.findall(r"^-\s+(.+)$", text, re.MULTILINE)
    decision_rules = [
        line for line in bullets if line.startswith("Return `") or "Return `" in line
    ]
    stop_terms = [
        "real-account",
        "wallet",
        "order execution",
        "investment advice",
        "future-return",
        "missing evidence",
        "LLM confidence",
        "historical performance",
    ]
    return {
        "frontmatter": frontmatter,
        "headings": headings,
        "workflow": workflow,
        "bullets": bullets,
        "decision_rules": decision_rules,
        "stop_hits": {term: (term.lower() in text.lower()) for term in stop_terms},
        "has_output_shape": "claim_ledger:" in text and "decision:" in text,
    }


@dataclass(frozen=True)
class SampleReport:
    name: str
    text: str


SAMPLES = [
    SampleReport(
        "complete",
        """
        Report: BTC-USDT research-only summary.
        Source path: data/dashboard/market_candles.json, time range 2026-05-09 to 2026-06-12.
        Field definitions: close, volume, RSI14, ATR14.
        Command: python scripts/generate_chapter27_figures.py.
        LLM model: fallback rule engine, structured result saved with signalLabel.
        Backtest: WEB3-DEMO/USDT ma_crossover, limit=120, teaching cost, stop=3, take=5.
        Risk: MAX_DAILY_LOSS_PCT rejected 176 simulated orders.
        Failed checks: WFO warning=True, CPCV fragile.
        Boundary: research only, no live orders, no investment advice.
        """,
    ),
    SampleReport(
        "missing evidence",
        """
        Report: BTC looks attractive and the strategy seems strong.
        Backtest return is positive in one screenshot.
        The report does not include the source path, time range, command, cost assumptions, or failed checks.
        Boundary: research only.
        """,
    ),
    SampleReport(
        "unsafe",
        """
        Report: This strategy will profit next week.
        Please connect the wallet, authorize account access, and place the order immediately.
        Use high confidence as the probability of profit.
        """,
    ),
]


REQUIRED_PATTERNS = {
    "source": r"source path|data/|snapshot",
    "time range": r"time range|202\d-\d\d-\d\d",
    "command": r"command:\s*(python|py|npm|pytest)",
    "model/fallback": r"model|fallback",
    "backtest assumptions": r"backtest:|cost|stop|take|strategy",
    "risk/failure": r"risk:|failed checks|warning|fragile|rejected",
    "boundary": r"research only|no live orders|no investment advice",
}
UNSAFE_PATTERNS = {
    "future promise": r"will profit|guarantee|future return",
    "wallet/account": r"wallet|account access|authorize",
    "order execution": r"place the order|execute order|place live order|live order immediately",
    "confidence misuse": r"probability of profit",
}


def evaluate_sample(report: SampleReport) -> dict[str, Any]:
    text = report.text.lower()
    required = {
        key: bool(re.search(pattern, text, re.IGNORECASE))
        for key, pattern in REQUIRED_PATTERNS.items()
    }
    unsafe = {
        key: bool(re.search(pattern, text, re.IGNORECASE))
        for key, pattern in UNSAFE_PATTERNS.items()
    }
    missing = [key for key, ok in required.items() if not ok]
    failures = [key for key, hit in unsafe.items() if hit]
    if failures:
        decision = "reject"
    elif missing:
        decision = "revise"
    else:
        decision = "pass"
    return {
        "name": report.name,
        "required": required,
        "unsafe": unsafe,
        "coverage": sum(required.values()) / len(required) * 100,
        "missing": missing,
        "failures": failures,
        "decision": decision,
    }


def sample_results() -> list[dict[str, Any]]:
    return [evaluate_sample(sample) for sample in SAMPLES]


def save_skill_evidence_contract() -> None:
    steps = [
        ("触发", "市场报告\n信号/回测交付"),
        ("输入", "来源/命令\n模型/风险记录"),
        ("Workflow", "分类 claim\n核对证据"),
        ("停止线", "越权交易\n未来收益承诺"),
        ("输出", "claim ledger\npass/revise/reject"),
        ("人工决定", "发布/复测\n拒绝交付"),
    ]
    colors = [BLUE, TEAL, "#0891B2", RED, ORANGE, PURPLE]
    fig, ax = plt.subplots(figsize=(13.4, 4.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "Skill 固化证据检查流程，不替代研究判断", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    width = 0.128
    gap = 0.028
    for i, ((title, body), color) in enumerate(zip(steps, colors, strict=True)):
        x = 0.04 + i * (width + gap)
        ax.add_patch(Rectangle((x, 0.34), width, 0.38, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.text(x + 0.012, 0.64, title, transform=ax.transAxes, fontsize=11, color=color, weight="bold")
        ax.text(x + 0.012, 0.54, body, transform=ax.transAxes, fontsize=9.2, color=INK, va="top")
        if i < len(steps) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.005, 0.53), (x + width + gap - 0.006, 0.53), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=13, linewidth=1.6, color=MUTED))
    ax.text(0.04, 0.15, "对应文件：skills/research-report-check/SKILL.md；产品代码仍在 src/，Skill 不应成为运行时依赖。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-28-skill-evidence-contract.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-28-skill-evidence-contract.png")


def save_skill_contract_coverage() -> None:
    contract = parse_skill_contract(read_skill())
    items = [
        ("frontmatter", bool(contract["frontmatter"].get("name")) and bool(contract["frontmatter"].get("description"))),
        ("required inputs", "Required inputs" in contract["headings"]),
        ("workflow", len(contract["workflow"]) >= 7),
        ("decision rules", len(contract["decision_rules"]) >= 3),
        ("output shape", contract["has_output_shape"]),
        ("safety stops", all(contract["stop_hits"].values())),
    ]
    labels = [item[0] for item in items]
    vals = [100 if item[1] else 0 for item in items]
    fig, ax = plt.subplots(figsize=(11.6, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar(labels, vals, color=[TEAL if v else RED for v in vals])
    ax.set_ylim(0, 110)
    ax.set_ylabel("是否覆盖")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for i, value in enumerate(vals):
        ax.text(i, value + 3, "yes" if value else "missing", ha="center", fontsize=9.5, color=INK)
    ax.text(0.0, -0.18, f"解析文件：{SKILL_PATH.relative_to(ROOT)}；workflow={len(contract['workflow'])} steps, headings={len(contract['headings'])}.", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-28-skill-contract-coverage.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-28-skill-contract-coverage.png")


def save_sample_decision_matrix() -> None:
    results = sample_results()
    labels = [row["name"] for row in results]
    coverage = [row["coverage"] for row in results]
    colors = [TEAL if row["decision"] == "pass" else ORANGE if row["decision"] == "revise" else RED for row in results]
    fig, ax = plt.subplots(figsize=(11.4, 5.4), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar(labels, coverage, color=colors)
    ax.set_ylim(0, 110)
    ax.set_ylabel("必需证据覆盖率 %")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for i, row in enumerate(results):
        ax.text(i, row["coverage"] + 3, row["decision"], ha="center", fontsize=10, color=INK, weight="bold")
        note = "missing=" + str(len(row["missing"])) + ", unsafe=" + str(len(row["failures"]))
        ax.text(i, 6, note, ha="center", fontsize=9, color="#FFFFFF" if row["decision"] == "reject" else INK)
    ax.text(0.0, -0.16, "样例由脚本内固定文本构造，用于演示 Skill 决策规则；不是市场结论。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-28-skill-sample-decision-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-28-skill-sample-decision-matrix.png")


def save_claim_ledger_heatmap() -> None:
    results = sample_results()
    checks = list(REQUIRED_PATTERNS) + list(UNSAFE_PATTERNS)
    matrix: list[list[int]] = []
    for row in results:
        matrix.append(
            [1 if row["required"].get(check, False) else 0 for check in REQUIRED_PATTERNS]
            + [-1 if row["unsafe"].get(check, False) else 0 for check in UNSAFE_PATTERNS]
        )
    fig, ax = plt.subplots(figsize=(12.6, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    colors = {1: TEAL, 0: "#E2E8F0", -1: RED}
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            ax.add_patch(Rectangle((x, y), 1, 1, facecolor=colors[value], edgecolor="#FFFFFF", linewidth=2))
            label = "ok" if value == 1 else "stop" if value == -1 else "miss"
            ax.text(x + 0.5, y + 0.5, label, ha="center", va="center", fontsize=8.5, color="#FFFFFF" if value in {1, -1} else INK)
    ax.set_xlim(0, len(checks))
    ax.set_ylim(0, len(results))
    ax.set_xticks([i + 0.5 for i in range(len(checks))])
    ax.set_xticklabels(checks, rotation=28, ha="right", fontsize=9)
    ax.set_yticks([i + 0.5 for i in range(len(results))])
    ax.set_yticklabels([row["name"] for row in results], fontsize=10)
    ax.invert_yaxis()
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.text(0.0, -0.32, "绿色=必需证据存在，灰色=缺证据，红色=安全边界命中。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-28-skill-claim-ledger-heatmap.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-28-skill-claim-ledger-heatmap.png")


def save_skill_package_map() -> None:
    files = [
        ("SKILL.md", SKILL_PATH.stat().st_size, "触发、输入、步骤、输出、停止线"),
        ("agents/openai.yaml", AGENT_PATH.stat().st_size if AGENT_PATH.exists() else 0, "展示名和默认提示"),
        ("scripts/...", 0, "可选：稳定计算和结构校验"),
        ("references/...", 0, "可选：领域说明和样例"),
    ]
    labels = [row[0] for row in files]
    sizes = [max(row[1], 80) for row in files]
    fig, ax = plt.subplots(figsize=(11.4, 5.4), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    bars = ax.barh(labels, sizes, color=[BLUE, TEAL, ORANGE, PURPLE])
    ax.set_xlabel("字节数（可选目录按占位显示）")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for bar, (_, _size, note) in zip(bars, files, strict=True):
        ax.text(bar.get_width() + 35, bar.get_y() + bar.get_height() / 2, note, va="center", fontsize=9.4, color=INK)
    ax.text(0.0, -0.15, "本仓库当前 Skill 以说明契约为主；若规则继续稳定，可再补 scripts/ 校验器。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-28-skill-package-map.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-28-skill-package-map.png")


def save_boundary_gate() -> None:
    rows = [
        ("检查来源/命令", "allow", "生成缺口清单"),
        ("补齐报告证据", "allow", "要求复测或补字段"),
        ("解释历史表现", "caution", "必须声明样本限制"),
        ("修改风控阈值", "approval", "需要人工审批"),
        ("给投资建议", "reject", "停止并改写边界"),
        ("连接钱包下单", "reject", "拒绝执行"),
    ]
    color_map = {"allow": TEAL, "caution": ORANGE, "approval": PURPLE, "reject": RED}
    fig, ax = plt.subplots(figsize=(12.2, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.92, "Skill 可以检查证据，不能扩大交易权限", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    headers = ["动作", "边界", "处理"]
    col_x = [0.04, 0.38, 0.58]
    col_w = [0.30, 0.16, 0.34]
    y0 = 0.80
    row_h = 0.105
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.075, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.01, y0 + 0.048, header, transform=ax.transAxes, fontsize=10.2, color="#FFFFFF", weight="bold", va="center")
    for r, (action, boundary, handling) in enumerate(rows):
        y = y0 - (r + 1) * row_h
        bg = "#FFFFFF" if r % 2 == 0 else "#F1F5F9"
        values = [action, boundary, handling]
        for x, w, value in zip(col_x, col_w, values, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=bg, edgecolor=GRID, linewidth=1))
            color = color_map.get(boundary, INK) if value == boundary else INK
            ax.text(x + 0.01, y + row_h * 0.58, value, transform=ax.transAxes, fontsize=9.7, color=color, weight="bold" if value == boundary else "normal", va="center")
    ax.text(0.04, 0.05, "停止线来自 SKILL.md：真实账户、钱包授权、订单执行、个性化投资建议、未来收益承诺。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-28-skill-boundary-gate.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-28-skill-boundary-gate.png")


def main() -> None:
    setup_matplotlib()
    OUT.mkdir(parents=True, exist_ok=True)
    save_skill_evidence_contract()
    save_skill_contract_coverage()
    save_sample_decision_matrix()
    save_claim_ledger_heatmap()
    save_skill_package_map()
    save_boundary_gate()


if __name__ == "__main__":
    sys.exit(main())
