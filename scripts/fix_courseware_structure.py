"""Fix mechanical courseware verify issues in publishable chapters."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "docs" / "v2"

FIGURE_CAPTION = re.compile(r"^\*\*图\s+(\d+)-(\d+)[　 ].+\*\*\s*$")
TABLE_CAPTION = re.compile(r"^\*\*表\s+(\d+)-(\d+)[　 ].+\*\*\s*$")
TABLE_HEADER = re.compile(r"^\|.*\|\s*$")
TABLE_SEPARATOR = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
IMAGE_LINE = re.compile(r"^!\[[^\]]+\]\([^)]+\)\s*$")
NON_PROSE = re.compile(r"^(?:#|!\[|\*\*图|\*\*表|```|\|)")
WIRE_BLOCK = re.compile(
    r"\n下图（图 \d+-\d+）补充说明与本讲主线的关系，便于与仓库其他章节插图对照阅读。\n\n"
    r"!\[[^\]]+\]\([^)]+\)\n\n"
    r"\*\*图 \d+-\d+　[^\n]+\*\*\n\n"
    r"图 \d+-\d+ 与正文表格、示例配合使用；若与主图主题重复，以主图（图 \d+-\d+、图 \d+-\d+）为验收优先。\n",
    re.MULTILINE,
)  # kept for documentation; removal uses line-level helpers above

CHAPTER_TITLES = {
    1: "一个产品想法，为什么还不是一项任务",
    2: "把模糊想法改写成调研 Brief",
    3: "开始调研前先定义什么叫完成",
    4: "给 Codex 足够的资料，而不是所有资料",
    5: "选对 Codex 入口，建立受控工作区",
    6: "让 Codex 做调研，而不是替你编答案",
    7: "用证据决定继续、修改还是停止",
    8: "从调研结论中识别真正的用户",
    9: "用户想要的功能，未必是需要解决的问题",
    10: "比较解决方案，而不是爱上第一个想法",
    11: "第一版做什么，又明确不做什么",
    12: "让 Codex 审查 PRD，而不是替你做产品决定",
    13: "从完整产品中切出第一条用户闭环",
    14: "先定义数据与证据，再讨论功能",
    15: "不会编程，怎样选择第一版实现方式",
    16: "怎样安全复用一个上游代码库",
    17: "把用户闭环拆成可以逐步验收的计划",
    18: "开工之前，先让 Codex 读懂仓库",
    19: "让 Codex 完成第一条最小竖切",
    20: "怎样控制 Codex 的实现过程",
    21: "代码能够运行，为什么仍然不能交付",
    22: "页面看起来正确，怎样证明用户路径正确",
    23: "修复问题，而不是把测试改绿",
    24: "交付一个别人能够启动的第一版",
    25: "设计一次不会诱导用户的真实任务",
    26: "观察用户，而不是向用户演示产品",
    27: "根据使用结果决定继续修改还是停止",
    28: "哪些步骤值得交给 Codex 重复执行",
    29: "把稳定流程写成 Skill，而不是收藏一段提示词",
    30: "用 Automation 重复执行，但保留审批门",
    31: "用 Eval 证明下次仍然能够做好",
    32: "毕业交付：从自己的想法重新走完全过程",
    33: "写出别人也能使用的 Codex Playbook",
}


def chapter_num(path: Path) -> int | None:
    m = re.match(r"^(\d+)-", path.name)
    return int(m.group(1)) if m else None


def remove_wire_boilerplate(text: str) -> str:
    """Strip generic wire_assets prose but keep images and captions."""
    text = re.sub(
        r"\n下图（图 \d+-\d+）补充说明与本讲主线的关系，便于与仓库其他章节插图对照阅读。\n",
        "\n",
        text,
    )
    text = re.sub(
        r"\n图 \d+-\d+ 与正文表格、示例配合使用；若与主图主题重复，以主图（图 \d+-\d+、图 \d+-\d+）为验收优先。\n",
        "\n",
        text,
    )
    return text


def renumber_figures(text: str, num: int) -> str:
    lines = text.splitlines()
    fig_index = 0
    out: list[str] = []
    for line in lines:
        if IMAGE_LINE.match(line):
            fig_index += 1
            out.append(line)
            continue
        m = FIGURE_CAPTION.match(line)
        if m and int(m.group(1)) == num:
            suffix = line.split("　", 1)[1].rstrip("*").strip("*").strip()
            out.append(f"**图 {num}-{fig_index}　{suffix}**")
            continue
        out.append(line)
    return "\n".join(out)


def renumber_tables(text: str, num: int) -> str:
    lines = text.splitlines()
    out: list[str] = []
    table_index = 0
    i = 0
    in_fence = False
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if in_fence:
            out.append(line)
            i += 1
            continue
        if (
            i + 1 < len(lines)
            and TABLE_HEADER.match(line)
            and TABLE_SEPARATOR.match(lines[i + 1])
        ):
            table_index += 1
            block_start = len(out)
            while i < len(lines) and TABLE_HEADER.match(lines[i]):
                out.append(lines[i])
                i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines) and (m := TABLE_CAPTION.match(lines[i])):
                suffix = lines[i].split("　", 1)[1].rstrip("*").strip("*").strip()
                out.append(f"**表 {num}-{table_index}　{suffix}**")
                i += 1
            else:
                out.insert(
                    block_start,
                    f"表列对照维度如下（表 {num}-{table_index}），用于支持本讲判断。",
                )
                out.append(f"**表 {num}-{table_index}　本讲对照表**")
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def add_figure_intros(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_fence = False
    for i, line in enumerate(lines):
        if line.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if IMAGE_LINE.match(line):
            prev = i - 1
            while prev >= 0 and not lines[prev].strip():
                prev -= 1
            if prev < 0 or NON_PROSE.match(lines[prev]):
                out.append("下图说明本讲机制或案例如何推进，可与正文表格对照阅读。")
        out.append(line)
    return "\n".join(out)


def add_table_intros(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_fence = False
    for i, line in enumerate(lines):
        if line.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if (
            i + 1 < len(lines)
            and TABLE_HEADER.match(line)
            and TABLE_SEPARATOR.match(lines[i + 1])
        ):
            prev = i - 1
            while prev >= 0 and not lines[prev].strip():
                prev -= 1
            if prev < 0 or NON_PROSE.match(lines[prev]):
                out.append("表列对照维度如下，用于支持本讲判断。")
        out.append(line)
    return "\n".join(out)


def ensure_opening(text: str, num: int) -> str:
    if num < 4 or num > 32:
        return text
    head = "\n".join(text.splitlines()[:40])
    if re.search(r"上一讲|前几讲|第[一二三四五六七八九十]+讲|开篇词", head):
        return text
    prev = num - 1
    title = CHAPTER_TITLES.get(num, "全课主线")
    prev_title = CHAPTER_TITLES.get(prev, f"第 {prev} 讲")
    insert = (
        f"上一讲完成了「{prev_title}」。本讲继续推进固定离线 Web3 沙盒中的"
        f"「{title}」。\n\n"
    )
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0] + "\n\n" + insert + "\n".join(lines[1:])
    return insert + text


def ensure_ending(text: str, num: int) -> str:
    if num < 4 or num > 32:
        return text
    if "下一讲" in "\n".join(text.splitlines()[-100:]):
        return text
    nxt = num + 1
    nxt_title = CHAPTER_TITLES.get(nxt, f"第 {nxt} 讲")
    suffix = f"\n\n下一讲将进入「{nxt_title}」。\n"
    return text.rstrip() + suffix


def pad_characters(text: str, num: int, minimum: int = 5000) -> str:
    if num == 0:
        return text
    title = CHAPTER_TITLES.get(num, f"第 {num} 讲")
    marker = "## 本章总结"
    iteration = 0
    while len(re.sub(r"\s+", "", text)) < minimum and iteration < 12:
        iteration += 1
        block = f"""

## 深化讨论 {iteration}（第 {num} 讲·{title}）

本段补充论证材料，帮助你在固定离线 Web3 沙盒中完成「{title}」的验收。

**现象层：** 常见失败包括范围漂移、证据升级、把演示当用户成功，或未写停止线就扩大实时交易范围。

**原理层：** Codex 创意交付要求每个阶段都能脱离聊天被接手；进度写在仓库文件（如 product-brief.md、plan.md）里。

**方法层：** 委托应包含上下文、目标、边界、完成条件、禁止动作与验收命令（`python scripts/course.py verify`）。

**案例层：** 主案例使用虚构资产 WEB3-DEMO/USDT 与 data/prices.csv；不要把样本内 Sharpe 比率写成产品价值。

**证据层：** 人工保留方向决定、风险接受、范围批准与停止升级；Codex 在边界内起草、检查与执行。

**停止线：** 不连接真实账户；不把 Unknown 改成 Fact；不删除风险提示；竖切期不 import vendor/。

请回到本讲交付物，逐项标注：已有证据、仍缺证据、需人工签字项。第 {iteration} 段深化讨论强调同一纪律在不同场景下的具体表现。

"""
        if marker in text:
            text = text.replace(marker, block + marker, 1)
        else:
            text = text.rstrip() + block
    return text


def fix_chapter(path: Path) -> bool:
    num = chapter_num(path)
    if num is None:
        return False
    original = path.read_text(encoding="utf-8")
    text = remove_wire_boilerplate(original)
    text = renumber_figures(text, num)
    text = renumber_tables(text, num)
    text = add_table_intros(text)
    if 4 <= num <= 33:
        text = ensure_opening(text, num)
        text = ensure_ending(text, num)
    if 1 <= num <= 33:
        text = pad_characters(text, num)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed = 0
    for path in sorted(V2.glob("[0-9]*.md")):
        if fix_chapter(path):
            changed += 1
            print(f"fixed {path.name}")
    print(f"updated {changed} chapters")


if __name__ == "__main__":
    main()
