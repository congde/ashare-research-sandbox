"""Mechanical publishing fixes for table captions and exercise counts."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "docs" / "v2"


TABLE_SEPARATOR = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
TABLE_CAPTION = re.compile(r"^\*\*表\s+(\d+)-(\d+)[　 ].+\*\*\s*$")


def chapter_number(path: Path) -> int | None:
    match = re.match(r"^(\d+)-", path.name)
    return int(match.group(1)) if match else None


def table_title(num: int, index: int) -> str:
    names = {
        4: ["五个基础对象的区别", "价格、收益与仓位的复核口径"],
        9: ["技术指标的输入与输出", "市场状态判断的常见误读"],
        16: ["策略规则的组成要素", "信号到规则的转换边界", "参数约定与风险口径", "规则实现检查项", "策略验收记录"],
        18: ["事件驱动回测的核心对象", "事件流与状态变化", "回测引擎的验收口径"],
        19: ["收益与风险指标口径", "指标解释边界", "回撤与波动复核", "风险调整指标检查项"],
        20: ["过拟合风险来源", "前视偏差检查项", "数据窥探的停止线", "样本划分与复核口径"],
        21: ["滚动回测的窗口设置", "策略比较的输入口径", "窗口结果记录", "多策略比较维度", "因子挖掘记录", "训练验证拆分", "过拟合差距解释", "样本外复核", "组合比较检查", "结论降级条件", "后续研究记录"],
        22: ["仓位控制边界", "止损规则检查项", "组合风险复核"],
        34: ["端到端验收路径"],
    }
    chapter_names = names.get(num, [])
    if 1 <= index <= len(chapter_names):
        return chapter_names[index - 1]
    return "本章表格说明"


def fix_tables(path: Path) -> bool:
    num = chapter_number(path)
    if num is None:
        return False
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    out: list[str] = []
    i = 0
    table_index = 0
    changed = False

    while i < len(lines):
        if (
            i + 1 < len(lines)
            and lines[i].startswith("|")
            and TABLE_SEPARATOR.match(lines[i + 1])
        ):
            table_index += 1
            intro = f"表 {num}-{table_index} 汇总本处需要对照的关键口径："
            previous = len(out) - 1
            while previous >= 0 and not out[previous].strip():
                previous -= 1
            if previous < 0 or f"表 {num}-" not in out[previous]:
                out.append(intro)
                out.append("")
                changed = True

            while i < len(lines) and lines[i].startswith("|"):
                out.append(lines[i])
                i += 1

            cursor = i
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            expected = f"**表 {num}-{table_index}　{table_title(num, table_index)}**"
            if cursor < len(lines) and TABLE_CAPTION.match(lines[cursor]):
                match = TABLE_CAPTION.match(lines[cursor])
                assert match is not None
                old = lines[cursor]
                if (int(match.group(1)), int(match.group(2))) != (num, table_index):
                    lines[cursor] = expected
                    changed = True
                out.extend(lines[i : cursor + 1])
                i = cursor + 1
            else:
                out.append("")
                out.append(expected)
                changed = True
            continue

        out.append(lines[i])
        i += 1

    text = "\n".join(out).rstrip() + "\n"
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return changed


def trim_exercises(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    match = re.search(r"^## (?:\d+\.\d+\s+)?课后题\s*$", original, re.M)
    if not match:
        return False
    head = original[: match.end()]
    tail = original[match.end() :]
    next_heading = re.search(r"\n## ", tail)
    section = tail[: next_heading.start()] if next_heading else tail
    rest = tail[next_heading.start() :] if next_heading else ""
    items = list(re.finditer(r"(?m)^\d+\. \*\*.+", section))
    if len(items) <= 3:
        return False
    keep_end = items[3].start()
    new_section = section[:keep_end].rstrip() + "\n"
    text = head + new_section + rest
    path.write_text(text, encoding="utf-8")
    return True


def fix_00_intros() -> bool:
    path = V2 / "00-我有一个想法但不会做.md"
    if not path.exists():
        return False
    original = path.read_text(encoding="utf-8")
    text = original
    replacements = {
        "![全书构建的交易研究系统总览]": "图 0-1 概括全书构建的交易研究系统总览。\n\n![全书构建的交易研究系统总览]",
        "![回测组合图表，/backtests 页面]": "图 0-2 展示 /backtests 页面中的回测组合图表。\n\n![回测组合图表，/backtests 页面]",
        "![可审计自动化流程图]": "图 0-3 展示可审计自动化流程的边界。\n\n![可审计自动化流程图]",
        "| 角色 | 擅长完成什么 | 不能证明什么 |": "表 0-1 先固定三类角色的责任边界。\n\n| 角色 | 擅长完成什么 | 不能证明什么 |",
    }
    for old, new in replacements.items():
        if old in text and new not in text:
            text = text.replace(old, new, 1)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed = []
    for path in sorted(V2.glob("*.md")):
        if re.match(r"^(?:0[0-9]|[12][0-9]|3[0-5])-", path.name):
            table_changed = fix_tables(path)
            exercise_changed = trim_exercises(path)
            if table_changed or exercise_changed:
                changed.append(path.relative_to(ROOT))
    if fix_00_intros():
        changed.append((V2 / "00-我有一个想法但不会做.md").relative_to(ROOT))
    for path in changed:
        print(f"fixed {path}")
    print(f"done ({len(changed)} files changed)")


if __name__ == "__main__":
    main()
