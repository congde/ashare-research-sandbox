"""Generate Chapter 32 publication figures."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from textwrap import fill
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dashboard.catalog import SNAPSHOT_NAMES, offline_status  # noqa: E402
from dashboard.persist import annotate_cached  # noqa: E402
from dashboard.signal_eval import score_llm_signal  # noqa: E402
from dashboard.snapshot import list_snapshots  # noqa: E402
from risk import evaluate_backtest_risk  # noqa: E402


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


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def snapshot_health_rows() -> list[dict[str, Any]]:
    status = offline_status()
    snapshots = {row["name"]: row for row in list_snapshots()}
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for name in SNAPSHOT_NAMES:
        item = status["datasets"][name]
        snap = snapshots.get(name, {})
        saved_at = _parse_dt(snap.get("saved_at"))
        age_hours = (now - saved_at).total_seconds() / 3600 if saved_at else None
        rows.append(
            {
                "name": name,
                "complete": bool(item["snapshot"]["complete"] or item["fixture"]["complete"]),
                "active_layer": item["active_layer"],
                "origin": snap.get("origin") or "",
                "history_count": int(snap.get("history_count") or 0),
                "age_hours": age_hours,
            }
        )
    return rows


def save_failure_audit_loop() -> None:
    steps = [
        ("发现", "task failed\nlive_error"),
        ("分类", "data / LLM\nrisk / page"),
        ("降级", "snapshot\nfixture / baseline"),
        ("复测", "pytest\ncourse verify"),
        ("恢复", "done / cached\nrecovered"),
        ("审计", "原因 / 命令\n剩余风险"),
    ]
    colors = [RED, ORANGE, BLUE, TEAL, PURPLE, "#0891B2"]
    fig, ax = plt.subplots(figsize=(13.6, 4.9), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "运行期失败要形成闭环：发现、分类、降级、复测、恢复、审计", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    width = 0.13
    gap = 0.026
    for i, ((title, body), color) in enumerate(zip(steps, colors, strict=True)):
        x = 0.04 + i * (width + gap)
        ax.add_patch(Rectangle((x, 0.34), width, 0.38, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.text(x + 0.012, 0.64, title, transform=ax.transAxes, fontsize=10.8, color=color, weight="bold")
        ax.text(x + 0.012, 0.54, body, transform=ax.transAxes, fontsize=8.7, color=INK, va="top")
        if i < len(steps) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.005, 0.53), (x + width + gap - 0.006, 0.53), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=13, linewidth=1.6, color=MUTED))
    ax.text(0.04, 0.15, "对应代码：dashboard.signal_tasks、dashboard.snapshot、dashboard.persist、dashboard.signal_eval、risk.simulation。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-32-failure-audit-loop.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-32-failure-audit-loop.png")


def save_snapshot_recovery_health() -> None:
    rows = sorted(snapshot_health_rows(), key=lambda row: row["history_count"], reverse=True)
    labels = [row["name"] for row in rows]
    history = [row["history_count"] for row in rows]
    age = [float(row["age_hours"] or 0) for row in rows]
    colors = [TEAL if row["complete"] else RED for row in rows]
    fig, ax1 = plt.subplots(figsize=(12.8, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax1.set_facecolor("#FFFFFF")
    x = list(range(len(rows)))
    ax1.bar(x, history, color=colors, label="history_count")
    ax1.set_ylabel("历史快照数")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=24, ha="right")
    ax1.grid(axis="y", color=GRID, linewidth=0.8)
    ax1.spines[["top"]].set_visible(False)
    ax2 = ax1.twinx()
    ax2.plot(x, age, color=ORANGE, marker="o", linewidth=2, label="快照年龄（小时）")
    ax2.axhline(24, color=RED, linestyle="--", linewidth=1.2, label="24h 标记线")
    ax2.set_ylabel("小时")
    ax2.spines[["top"]].set_visible(False)
    ax1.legend(frameon=False, loc="upper left")
    ax2.legend(frameon=False, loc="upper right")
    ax1.text(0.0, -0.25, "数据来自 offline_status() 与 list_snapshots()。历史数量证明失败前后有留痕，年龄用于判断是否需要降级或标记 stale。", transform=ax1.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-32-snapshot-recovery-health.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-32-snapshot-recovery-health.png")


def save_degradation_path_matrix() -> None:
    rows = [
        ("live data timeout", "annotate_cached", "snapshot", "continue with cached"),
        ("snapshot incomplete", "load_offline", "fixture", "draft only"),
        ("LLM missing key", "run_llm_signal", "rule baseline", "research_record"),
        ("critical eval", "score_llm_signal", "reject", "stop delivery"),
        ("risk rejection", "evaluate_backtest_risk", "finding", "human review"),
        ("real order request", "execution boundary", "blocked", "stop"),
    ]
    fig, ax = plt.subplots(figsize=(12.4, 6.0), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.91, "降级路径必须诚实标记来源，不能把替代材料写成主路径成功", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    headers = ["失败", "处理函数", "降级/阻断", "审计动作"]
    col_x = [0.04, 0.31, 0.53, 0.70]
    col_w = [0.23, 0.18, 0.13, 0.22]
    y0 = 0.80
    row_h = 0.105
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.078, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.01, y0 + 0.05, header, transform=ax.transAxes, fontsize=10.2, color="#FFFFFF", weight="bold", va="center")
    for r, row in enumerate(rows):
        y = y0 - (r + 1) * row_h
        bg = "#FFFFFF" if r % 2 == 0 else "#F1F5F9"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=bg, edgecolor=GRID, linewidth=1))
            color = RED if value in {"reject", "blocked", "stop"} else INK
            ax.text(x + 0.01, y + row_h * 0.58, fill(value, 24), transform=ax.transAxes, fontsize=9.4, color=color, va="center")
    ax.text(0.04, 0.04, "审计口径：降级后可以继续研究，但必须显示 source、cached_at、criticalFailures、risk rule 或 blocked reason。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-32-degradation-path-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-32-degradation-path-matrix.png")


def incident_rows() -> list[dict[str, Any]]:
    cached = annotate_cached({"ok": True, "source": "snapshot", "snapshot": {"saved_at": "2026-06-13T00:00:00+00:00"}})
    eval_failure = score_llm_signal({field: True for field in ["json_valid", "evidence_refs", "admits_missing_data", "direction_stable", "clear_summary"]} | {"fabricated_price": True})
    risk_findings = evaluate_backtest_risk(
        {
            "metrics": {
                "maximum_drawdown_pct": -18.5,
                "strategy_return_pct": 4.0,
                "buy_hold_return_pct": 8.0,
                "trade_count": 8,
            },
            "curve": list(range(20)),
            "risk_rejections": [
                {"rule_id": "EMERGENCY_HALT", "reason": "manual incident halt"},
                {"rule_id": "EMERGENCY_HALT", "reason": "manual incident halt"},
            ],
        }
    )
    return [
        {"case": "data cache", "severity": "warning", "status": "fallback", "evidence": "live_error" if cached.get("live_error") else ""},
        {"case": "eval fail", "severity": "critical", "status": "reject", "evidence": ",".join(eval_failure["criticalFailures"])},
        {"case": "risk halt", "severity": "critical", "status": "blocked", "evidence": risk_findings[0]["rule_id"]},
        {"case": "post risk", "severity": "warning", "status": "review", "evidence": ",".join(sorted({row["rule_id"] for row in risk_findings}))},
        {"case": "task done", "severity": "info", "status": "done", "evidence": "result saved"},
    ]


def save_incident_severity_card() -> None:
    rows = incident_rows()
    severity_score = {"info": 1, "warning": 2, "critical": 3}
    colors = {"info": TEAL, "warning": ORANGE, "critical": RED}
    fig, ax = plt.subplots(figsize=(11.8, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    labels = [row["case"] for row in rows]
    scores = [severity_score[row["severity"]] for row in rows]
    ax.bar(labels, scores, color=[colors[row["severity"]] for row in rows])
    ax.set_yticks([1, 2, 3])
    ax.set_yticklabels(["info", "warning", "critical"])
    ax.set_ylim(0, 3.6)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for i, row in enumerate(rows):
        ax.text(i, scores[i] + 0.08, row["status"], ha="center", fontsize=9, color=INK)
    ax.text(0.0, -0.18, "示例由 annotate_cached()、score_llm_signal()、evaluate_backtest_risk() 产生。critical 不能自动关闭。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-32-incident-severity-card.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-32-incident-severity-card.png")


def save_recovery_sla_timeline() -> None:
    minutes = [0, 3, 8, 15, 24, 37, 45]
    states = ["failed", "classified", "fallback", "retest", "recovered", "audit", "closed"]
    score = [3, 3, 2, 2, 1, 1, 0]
    colors = [RED, RED, ORANGE, ORANGE, TEAL, BLUE, MUTED]
    fig, ax = plt.subplots(figsize=(12.2, 5.5), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.plot(minutes, score, color=BLUE, linewidth=2.2, marker="o")
    for x, y, state, color in zip(minutes, score, states, colors, strict=True):
        ax.scatter([x], [y], s=130, color=color, zorder=3)
        ax.text(x, y + 0.17, state, ha="center", fontsize=9, color=INK)
    ax.set_yticks([0, 1, 2, 3])
    ax.set_yticklabels(["closed", "recovered", "degraded", "failed"])
    ax.set_xlabel("分钟")
    ax.grid(color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(0.0, -0.18, "恢复不是覆盖失败文件；状态从 failed 到 closed 的每一步都要保留时间、原因、命令和人工决定。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-32-recovery-sla-timeline.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-32-recovery-sla-timeline.png")


def save_audit_record_completeness() -> None:
    fields = ["time", "input", "version", "reason", "fallback", "command", "owner", "residual"]
    cases = [
        ("good", [1, 1, 1, 1, 1, 1, 1, 1]),
        ("no command", [1, 1, 1, 1, 1, 0, 1, 1]),
        ("no reason", [1, 1, 1, 0, 1, 1, 1, 1]),
        ("silent fallback", [1, 1, 1, 1, 0, 1, 1, 0]),
        ("covered failure", [0, 0, 1, 0, 1, 1, 1, 0]),
    ]
    fig, ax = plt.subplots(figsize=(12.0, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    for y, (_, values) in enumerate(cases):
        for x, value in enumerate(values):
            color = TEAL if value else RED
            ax.add_patch(Rectangle((x, y), 1, 1, facecolor=color, edgecolor="#FFFFFF", linewidth=2))
            ax.text(x + 0.5, y + 0.5, "ok" if value else "miss", ha="center", va="center", fontsize=8, color="#FFFFFF")
    ax.set_xlim(0, len(fields))
    ax.set_ylim(0, len(cases))
    ax.set_xticks([i + 0.5 for i in range(len(fields))])
    ax.set_xticklabels(fields, rotation=18, ha="right")
    ax.set_yticks([i + 0.5 for i in range(len(cases))])
    ax.set_yticklabels([case[0] for case in cases])
    ax.invert_yaxis()
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.text(0.0, -0.18, "最小记录字段：时间、输入、版本、原因、降级路径、复测命令、处理人、剩余风险。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-32-audit-record-completeness.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-32-audit-record-completeness.png")


def main() -> None:
    setup_matplotlib()
    OUT.mkdir(parents=True, exist_ok=True)
    save_failure_audit_loop()
    save_snapshot_recovery_health()
    save_degradation_path_matrix()
    save_incident_severity_card()
    save_recovery_sla_timeline()
    save_audit_record_completeness()


if __name__ == "__main__":
    main()
