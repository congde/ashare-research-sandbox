"""Generate Chapter 29 publication figures."""

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
from dashboard.snapshot import list_snapshots, load_fixture, load_snapshot  # noqa: E402


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


def snapshot_rows() -> list[dict[str, Any]]:
    status = offline_status()
    snapshots = {row["name"]: row for row in list_snapshots()}
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for name in SNAPSHOT_NAMES:
        item = status["datasets"][name]
        snap = snapshots.get(name, {})
        saved_at = _parse_dt(snap.get("saved_at"))
        age_min = (now - saved_at).total_seconds() / 60 if saved_at else None
        rows.append(
            {
                "name": name,
                "active_layer": item["active_layer"],
                "snapshot_complete": bool(item["snapshot"]["complete"]),
                "fixture_complete": bool(item["fixture"]["complete"]),
                "snapshot_reason": item["snapshot"].get("reason") or "",
                "fixture_reason": item["fixture"].get("reason") or "",
                "saved_at": snap.get("saved_at"),
                "origin": snap.get("origin"),
                "history_count": int(snap.get("history_count") or 0),
                "age_min": age_min,
            }
        )
    return rows


def save_snapshot_draft_path() -> None:
    steps = [
        ("触发", "手动 / 定时\ncourse.py snapshot"),
        ("抓取", "dashboard.refresh\n公开数据源"),
        ("保存", "latest + history\nsnapshot metadata"),
        ("完整性", "catalog checks\nfixture fallback"),
        ("草稿", "来源 / 时间\n缺失 / 失败"),
        ("人工复核", "发布 / 复测\n停止"),
    ]
    colors = [BLUE, TEAL, "#0891B2", ORANGE, PURPLE, RED]
    fig, ax = plt.subplots(figsize=(13.6, 4.9), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.9, "自动化先冻结快照，再生成研究草稿", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    width = 0.13
    gap = 0.026
    for i, ((title, body), color) in enumerate(zip(steps, colors, strict=True)):
        x = 0.04 + i * (width + gap)
        ax.add_patch(Rectangle((x, 0.34), width, 0.38, transform=ax.transAxes, facecolor="#FFFFFF", edgecolor=color, linewidth=2))
        ax.text(x + 0.012, 0.64, title, transform=ax.transAxes, fontsize=11, color=color, weight="bold")
        ax.text(x + 0.012, 0.54, body, transform=ax.transAxes, fontsize=8.9, color=INK, va="top")
        if i < len(steps) - 1:
            ax.add_patch(FancyArrowPatch((x + width + 0.005, 0.53), (x + width + gap - 0.006, 0.53), transform=ax.transAxes, arrowstyle="-|>", mutation_scale=13, linewidth=1.6, color=MUTED))
    ax.text(0.04, 0.15, "对应代码：dashboard_snapshot.py -> dashboard.refresh.refresh_all -> dashboard.snapshot.save_snapshot -> dashboard.catalog.offline_status。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-29-snapshot-draft-path.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-29-snapshot-draft-path.png")


def save_snapshot_age_history_chart() -> None:
    rows = snapshot_rows()
    rows = sorted(rows, key=lambda row: row["age_min"] if row["age_min"] is not None else 10**9, reverse=True)
    labels = [row["name"] for row in rows]
    ages = [float(row["age_min"] or 0) / 60 for row in rows]
    histories = [row["history_count"] for row in rows]
    colors = [RED if age > 24 else ORANGE if age > 6 else TEAL for age in ages]
    fig, ax1 = plt.subplots(figsize=(12.8, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax1.set_facecolor("#FFFFFF")
    x = list(range(len(labels)))
    ax1.bar(x, ages, color=colors, label="快照年龄（小时）")
    ax1.axhline(24, color=RED, linestyle="--", linewidth=1.3, label="24h 停止线")
    ax1.set_ylabel("小时")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=24, ha="right")
    ax1.grid(axis="y", color=GRID, linewidth=0.8)
    ax1.spines[["top"]].set_visible(False)
    ax2 = ax1.twinx()
    ax2.plot(x, histories, color=BLUE, marker="o", linewidth=2, label="history_count")
    ax2.set_ylabel("历史条数")
    ax2.spines[["top"]].set_visible(False)
    ax1.legend(frameon=False, loc="upper left")
    ax2.legend(frameon=False, loc="upper right")
    ax1.text(0.0, -0.26, "红色表示超过 24 小时草稿停止线；蓝线显示历史快照是否持续留存，而不是覆盖最新文件。", transform=ax1.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-29-snapshot-age-history.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-29-snapshot-age-history.png")


def save_completeness_matrix() -> None:
    rows = snapshot_rows()
    checks = ["snapshot", "fixture", "active=snapshot", "origin", "history"]
    matrix = []
    for row in rows:
        matrix.append(
            [
                1 if row["snapshot_complete"] else 0,
                1 if row["fixture_complete"] else 0,
                1 if row["active_layer"] == "snapshot" else 0,
                1 if row["origin"] else 0,
                1 if row["history_count"] > 0 else 0,
            ]
        )
    fig, ax = plt.subplots(figsize=(11.8, 6.2), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            color = TEAL if value else RED
            ax.add_patch(Rectangle((x, y), 1, 1, facecolor=color, edgecolor="#FFFFFF", linewidth=2))
            ax.text(x + 0.5, y + 0.5, "ok" if value else "miss", ha="center", va="center", fontsize=8.5, color="#FFFFFF")
    ax.set_xlim(0, len(checks))
    ax.set_ylim(0, len(rows))
    ax.set_xticks([i + 0.5 for i in range(len(checks))])
    ax.set_xticklabels(checks, rotation=20, ha="right")
    ax.set_yticks([i + 0.5 for i in range(len(rows))])
    ax.set_yticklabels([row["name"] for row in rows])
    ax.invert_yaxis()
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.text(0.0, -0.22, "数据来自 dashboard.catalog.offline_status() 与 dashboard.snapshot.list_snapshots()。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-29-snapshot-completeness-matrix.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-29-snapshot-completeness-matrix.png")


def save_offline_fallback_gate() -> None:
    rows = [
        ("完整 snapshot", "使用 snapshot", "source=snapshot"),
        ("snapshot 不完整 + fixture 完整", "回退 fixture", "保留降级说明"),
        ("snapshot 缺失 + fixture 完整", "使用 fixture", "标记教学样本"),
        ("两者都不完整", "停止草稿", "记录缺字段原因"),
        ("实时接口失败", "不伪装实时", "使用缓存并标 live_error"),
    ]
    fig, ax = plt.subplots(figsize=(12.2, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.92, "离线回退门禁：完整证据优先，残缺新数据不能覆盖完整旧样本", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    headers = ["场景", "处理", "草稿写法"]
    col_x = [0.04, 0.38, 0.63]
    col_w = [0.30, 0.22, 0.28]
    y0 = 0.80
    row_h = 0.12
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.078, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.01, y0 + 0.05, header, transform=ax.transAxes, fontsize=10.2, color="#FFFFFF", weight="bold", va="center")
    for r, row in enumerate(rows):
        y = y0 - (r + 1) * row_h
        bg = "#FFFFFF" if r % 2 == 0 else "#F1F5F9"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=bg, edgecolor=GRID, linewidth=1))
            color = RED if "停止" in value else INK
            ax.text(x + 0.01, y + row_h * 0.58, fill(value, 28), transform=ax.transAxes, fontsize=9.6, color=color, va="center")
    ax.text(0.04, 0.05, "对应实现：load_offline() 优先完整 snapshot，再完整 fixture；失败状态进入 cached/live_error 字段。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-29-offline-fallback-gate.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-29-offline-fallback-gate.png")


def save_automation_level_ladder() -> None:
    actions = [
        ("拉取公开数据", 1, TEAL),
        ("保存快照", 1, TEAL),
        ("完整性检查", 1, TEAL),
        ("生成研究草稿", 2, ORANGE),
        ("形成结论", 3, PURPLE),
        ("修改风控阈值", 4, RED),
        ("执行交易", 5, RED),
    ]
    labels = [item[0] for item in actions]
    levels = [item[1] for item in actions]
    colors = [item[2] for item in actions]
    fig, ax = plt.subplots(figsize=(11.8, 5.6), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor("#FFFFFF")
    ax.bar(labels, levels, color=colors)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["自动", "草稿", "审批", "高危审批", "停止"])
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", rotation=18)
    ax.text(0.0, -0.21, "29 讲只允许自动化到草稿层；结论、风控阈值和交易动作留给后续审批门。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "chapter-29-automation-level-ladder.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-29-automation-level-ladder.png")


def save_draft_gate_card() -> None:
    rows = snapshot_rows()
    stale = [row for row in rows if (row["age_min"] or 0) > 24 * 60]
    incomplete = [row for row in rows if not (row["snapshot_complete"] or row["fixture_complete"])]
    values = [
        ("数据集", f"{len(rows)} 个", "SNAPSHOT_NAMES"),
        ("完整材料", f"{sum(1 for r in rows if r['snapshot_complete'] or r['fixture_complete'])}/{len(rows)}", "offline_status"),
        ("超 24h", f"{len(stale)} 个", "草稿需标记或停止"),
        ("缺完整性", f"{len(incomplete)} 个", "不能进入草稿"),
        ("草稿结论", "draft only", "不得自动发布"),
    ]
    fig, ax = plt.subplots(figsize=(12.4, 5.8), dpi=160)
    fig.patch.set_facecolor(PAPER)
    ax.axis("off")
    ax.text(0.04, 0.90, "研究草稿门禁卡：来源、时间、完整性先过关", transform=ax.transAxes, fontsize=15, color=INK, weight="bold")
    col_x = [0.05, 0.33, 0.55]
    col_w = [0.23, 0.18, 0.35]
    headers = ["检查", "当前结果", "草稿处理"]
    y0 = 0.78
    row_h = 0.12
    for x, w, header in zip(col_x, col_w, headers, strict=True):
        ax.add_patch(Rectangle((x, y0), w, 0.08, transform=ax.transAxes, facecolor="#334155", edgecolor="#334155"))
        ax.text(x + 0.012, y0 + 0.052, header, transform=ax.transAxes, fontsize=10.5, color="#FFFFFF", weight="bold", va="center")
    for r, row in enumerate(values):
        y = y0 - (r + 1) * row_h
        bg = "#FFFFFF" if r % 2 == 0 else "#F1F5F9"
        for x, w, value in zip(col_x, col_w, row, strict=True):
            ax.add_patch(Rectangle((x, y), w, row_h, transform=ax.transAxes, facecolor=bg, edgecolor=GRID, linewidth=1))
            color = RED if ("缺" in row[0] and row[1] != "0 个") or ("超" in row[0] and row[1] != "0 个") else INK
            ax.text(x + 0.012, y + row_h * 0.58, fill(value, 30), transform=ax.transAxes, fontsize=9.8, color=color, va="center")
    ax.text(0.05, 0.05, "门禁结论：草稿可以生成，但必须携带 stale/missing/fallback 标记；自动化不能把草稿提升为交易结论。", transform=ax.transAxes, fontsize=10, color=MUTED)
    fig.savefig(OUT / "chapter-29-draft-gate-card.png", bbox_inches="tight")
    plt.close(fig)
    print(OUT / "chapter-29-draft-gate-card.png")


def main() -> None:
    setup_matplotlib()
    OUT.mkdir(parents=True, exist_ok=True)
    save_snapshot_draft_path()
    save_snapshot_age_history_chart()
    save_completeness_matrix()
    save_offline_fallback_gate()
    save_automation_level_ladder()
    save_draft_gate_card()


if __name__ == "__main__":
    main()
