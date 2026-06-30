"""Apply known errata fixes to the Codex quick-start PDF."""
from __future__ import annotations

import glob
import shutil
from pathlib import Path

import fitz

DESKTOP = Path(r"c:\Users\54461\Desktop")
BACKUP_SUFFIX = ".bak-before-errata-fix"

# (old, new) pairs in application order.
REPLACEMENTS: list[tuple[str, str]] = [
    ("版 芯", "版 心"),
    ("版芯", "版心"),
    ("活 号", "货 号"),
    ("活号", "货号"),
    ("取取代", "取代"),
    ("将续修正", "继续修正"),
    ("Codex Weba", "Codex Web"),
    ("要注额外意什么", "要额外注意什么"),
    ("容易忽被视", "容易被忽视"),
    ("技术不够源", "技术不够，而是源"),
    ("异步评中", "异步评审"),
    ("最令人担忧的往往 “不理解逻辑”", "最令人担忧的往往不是“不理解逻辑”"),
    ("git diff--check", "git diff --check"),
    ("AGENTS. md", "AGENTS.md"),
    ("简单任务\t简单任务（", "简单任务（"),
    ("中等任务\t中等任务（", "中等任务（"),
    ("复杂任务\t复杂任务（", "复杂任务（"),
    ("避免重复执行\t避免重复执行：", "避免重复执行："),
    ("控制上下文长度\t控制上下文长度：", "控制上下文长度："),
    ("使用轻量级模型处理简单任务\t使用轻量级模型处理简单任务：", "使用轻量级模型处理简单任务："),
    ("监控用量\t监控用量：", "监控用量："),
    ("准备上下文（Context）\t准备上下文（Context）=", "准备上下文（Context）="),
    ("下达任务（Task）\t下达任务（Task）=", "下达任务（Task）="),
    ("验收结果（Acceptance）\t验收结果（Acceptance）=", "验收结果（Acceptance）="),
    ("表12-3 列出了值得开始团队化试点的信号", "表13-3 列出了值得开始团队化试点的信号"),
    ("阶段的权限边界都那么清晰", "阶段的权限边界都同样清晰"),
    ("测试已经是够了", "测试已经够了"),
    ("重复的髙噪声工作", "重复的高噪声工作"),
    ("仍能保持体稳定", "仍能保持稳定"),
    ("某次惊艳地对话", "某次惊艳的对话"),
    (
        "所以，电子版配套仓库不是营销附件，本书内容生命周期的重要组",
        "所以，电子版配套仓库不是营销附件，而是本书内容生命周期的重要组",
    ),
    (
        "本书按照“认知迁移→Harness 工程→高频实战→团队落地→领域应",
        "本书按照“认知迁移→Harness 工程→高频实战→团队落地”的路径组织内容；跨领域迁移见",
    ),
    ("用”的路径组织内容。", "后文案例与特色说明。"),
    ("从Codex 的任务地图", "读懂Codex 的任务地图"),
    ("张建飞", "袁从德"),
    (
        "# 启动三个并行 Codex 任务，每个都有自己的工作树和 tmux 面板",
        "# Codex App 支持 --worktree；CLI 需先 git worktree add 再 -C 指定目录",
    ),
    ("codex --worktree feature-feedback --tmux", "git worktree add ../wt-feedback -b feature-feedback"),
    ("codex --worktree fix-emotion-bug --tmux", "codex -C ../wt-feedback --tmux"),
    ("codex --worktree refactor-memory --tmux", "codex -C ../wt-memory --tmux"),
]


def find_source_pdf() -> Path:
    candidates = [
        p
        for p in DESKTOP.glob("A20261559-Codex*PDF-6.18.pdf")
        if "已勘误" not in p.name and "yuancongde" not in p.name.lower()
    ]
    if not candidates:
        raise FileNotFoundError("No source PDF found on Desktop")
    return candidates[0]


def replace_text_on_page(page: fitz.Page, old: str, new: str) -> int:
    count = 0
    while True:
        hits = page.search_for(old)
        if not hits:
            break
        for rect in hits:
            page.add_redact_annot(rect, text=new, fill=False, cross_out=False)
            count += 1
        page.apply_redactions()
    return count


def apply_replacements(doc: fitz.Document) -> dict[str, int]:
    stats: dict[str, int] = {}
    for old, new in REPLACEMENTS:
        total = 0
        for page in doc:
            total += replace_text_on_page(page, old, new)
        stats[old] = total
    return stats


def main() -> None:
    source = find_source_pdf()
    backup = source.with_suffix(source.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(source, backup)
        print(f"Backup created: {backup}")

    doc = fitz.open(source)
    stats = apply_replacements(doc)
    output = source.with_name(source.stem + "-已勘误" + source.suffix)
    doc.save(output, garbage=4, deflate=True)
    doc.close()

    print(f"Source: {source}")
    print(f"Output: {output}")
    print("Replacement counts:")
    for key, value in stats.items():
        if value:
            print(f"  [{value}] {key}")
    missing = [k for k, v in stats.items() if v == 0]
    if missing:
        print("Not found in PDF:")
        for key in missing:
            print(f"  - {key}")


if __name__ == "__main__":
    main()
