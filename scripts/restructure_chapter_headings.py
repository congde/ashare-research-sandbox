"""Restructure publishable chapter headings: group flat ### under ### parents as ####."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAPTER_DIR = ROOT / "docs" / "v2"

RIGOR_MARKERS = ("变量与公式", "样本口径与成本假设", "偏差来源与反例", "最小人工复核")
RIGOR_BIAS_EXTRAS = ("常见失败写法",)
RIGOR_RECORD_EXTRAS = (
    "安全边界记录",
    "工作区记录示例",
    "基础量化计算记录",
    "研究假设卡示例",
    "它怎样连接后续章节",
)

TOPIC_CHILDREN = ("代码走读", "实战推演", "结果解读")
CASE_FLOW = (
    "案例步骤一：保存输入与预期",
    "案例步骤二：沿代码路径执行",
    "案例步骤三：注入失败",
    "案例步骤四：形成判断",
)
LLM_DEEPENING_TAIL = (
    "使用真实输出建立判断",
    "本章可复现实验协议",
    "关键计算与人工复核",
    "从实验结果到发布决定",
    "研究者笔记：如何避免在本章自欺",
    "进一步推导：从 LLM 指标到策略价值",
    "给学员的复盘要求",
    "配套图解与代码示例",
)

# (chapter_num, section_key) -> list of (### group title, [#### titles])
MANUAL_GROUPS: dict[tuple[int, str], list[tuple[str, list[str]]]] = {
    (2, "2.1"): [
        (
            "界定研究假设",
            [
                "为什么交易想法不等于研究假设",
                "六个必填字段",
                "只写成功条件的危险",
            ],
        ),
    ],
    (2, "2.2"): [
        (
            "从代码到假设",
            ["代码走读", "实战推演", "从输出到假设修订"],
        ),
        (
            "判断与放行",
            ["结果解读", "放行、退回与拒绝"],
        ),
    ],
    (3, "3.1"): [
        ("复现边界", ["五个边界", "从安装步骤到复现协议"]),
    ],
    (3, "3.2"): [
        ("最小实践三步", ["代码走读", "运行验证", "结果解读"]),
    ],
    (4, "4.1"): [
        (
            "五个对象与基础公式",
            [
                "五个对象不能混用",
                "为什么这不是“基础课废话”",
                "从完整量化系统反推基础地图",
                "学习资料中的基础公式放在本章",
            ],
        ),
    ],
    (4, "4.2"): [
        (
            "实践与解读",
            [
                "代码走读",
                "实战推演",
                "结果解读",
                "完整案例：同一段行情的三种读法",
            ],
        ),
    ],
    (5, "5.1"): [
        (
            "认识边界",
            ["容易误判的输出", "三层边界", "为什么边界要落到代码里"],
        ),
    ],
    (5, "5.2"): [
        (
            "仓库中的边界",
            [
                "产品目标边界",
                "风险规则边界",
                "页面语义边界",
                "能力边界复核",
            ],
        ),
    ],
    (5, "5.3"): [
        ("最小实践", ["输入改写", "运行检查", "结果解读"]),
    ],
    (9, "9.2"): [
        (
            "指标知识准备",
            ["常见指标家族与学习顺序", "常用技术指标公式速查"],
        ),
    ],
    (16, "16.2"): [
        (
            "策略规则骨架",
            ["策略规则的最小骨架", "从指标公式到策略规则"],
        ),
        (
            "案例模板与典型策略",
            [
                "Qbot 案例拆解模板",
                "拐点交易：把策略写成状态机",
                "网格交易：把仓位写成价格函数",
            ],
        ),
    ],
    (18, "18.0"): [
        ("快速入门", ["一键运行"]),
    ],
    (18, "18.2"): [
        (
            "回测报告与卫生清单",
            ["回测基础卫生清单", "单次回测案例报告模板"],
        ),
    ],
    (20, "20.0"): [
        ("快速入门", ["一键运行"]),
    ],
    (20, "20.2"): [
        ("污染识别方法", ["三类污染的初学者识别法"]),
    ],
    (19, "19.0"): [
        ("快速入门", ["一键运行"]),
    ],
    (19, "19.2"): [
        (
            "指标与公式速查",
            ["指标不是排行榜", "回测评价公式速查"],
        ),
    ],
    (22, "22.2"): [
        (
            "风控分层与公式",
            ["风控规则的基础分层", "仓位与风控公式速查"],
        ),
    ],
    (21, "21.0.1"): [
        (
            "方法说明",
            ["两类方法"],
        ),
    ],
    (21, "21.2"): [
        (
            "比较方法与报告",
            ["多策略比较的公平性规则", "多窗口回测案例报告模板"],
        ),
    ],
    (21, "21.8"): [
        (
            "因子挖掘定位与问题类型",
            [
                "21.8.1 因子挖掘在研究流程中的位置",
                "21.8.2 截面 vs 时序：先选对问题",
                "21.8.2a 多因子选股资料的可借鉴结构",
                "21.8.2b 配对交易资料的可借鉴图形",
            ],
        ),
        (
            "技术路线与仓库对照",
            ["21.8.3 业界四条技术路线", "21.8.4 本仓库三层对照"],
        ),
        (
            "实操走读与验收",
            [
                "21.8.5 沙箱模块走读",
                "21.8.6 完整实操与验收",
                "21.8.7 Codex 委托模板",
                "21.8.8 常见翻车",
            ],
        ),
        (
            "风险因子与业界对标",
            [
                "21.8.10 风险因子挖掘（RIC → 仓位缩放）",
                "21.8.9 若要对标业界的升级顺序",
            ],
        ),
    ],
    (34, "34.0"): [
        ("快速入门", ["一键运行"]),
    ],
    (34, "34.2"): [
        ("路径边界地图", ["模拟交易路径的边界地图"]),
    ],
}


def split_sections(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    sections: list[tuple[str, str]] = []
    for part in parts:
        if not part.strip():
            continue
        match = re.match(r"^(## [^\n]+)\n", part)
        if match:
            sections.append((match.group(1), part[match.end() :]))
        else:
            sections.append(("", part))
    return sections


def heading_title(line: str) -> str:
    return re.sub(r"^#+\s+", "", line).strip()


def collect_h3_titles(body: str) -> list[str]:
    return [heading_title(line) for line in body.splitlines() if line.startswith("### ") and not line.startswith("#### ")]


def already_grouped(body: str) -> bool:
    return bool(re.search(r"^#### ", body, re.MULTILINE))


def demote_h3(body: str, title: str) -> str:
    pattern = rf"^### {re.escape(title)}\s*$"
    return re.sub(pattern, f"#### {title}", body, count=1, flags=re.MULTILINE)


def insert_group(body: str, group_title: str, child_titles: list[str]) -> str:
    if not child_titles:
        return body
    first = child_titles[0]
    pattern = rf"^### {re.escape(first)}\s*$"
    if not re.search(pattern, body, re.MULTILINE):
        return body
    replacement = f"### {group_title}\n\n#### {first}"
    body = re.sub(pattern, replacement, body, count=1, flags=re.MULTILINE)
    for child in child_titles[1:]:
        body = demote_h3(body, child)
    return body


def manual_group_key(chapter_num: int, section_heading: str) -> str | None:
    title = re.sub(r"^## ", "", section_heading).strip()
    matches = [
        key
        for num, key in MANUAL_GROUPS
        if num == chapter_num and title.startswith(key)
    ]
    if not matches:
        return None
    return max(matches, key=len)


def apply_manual_groups(chapter_num: int, section_heading: str, body: str) -> str:
    key = manual_group_key(chapter_num, section_heading)
    if key is None:
        return body
    groups = MANUAL_GROUPS[(chapter_num, key)]
    if already_grouped(body):
        return body
    for group_title, children in reversed(groups):
        body = insert_group(body, group_title, children)
    return body


def transform_rigor(body: str) -> str:
    titles = collect_h3_titles(body)
    if not titles or "变量与公式" not in titles:
        return body
    if already_grouped(body) or "口径定义与复算公式" in titles:
        return body

    body = insert_group(body, "口径定义与复算公式", ["变量与公式", "样本口径与成本假设"])

    bias_children = ["偏差来源与反例", "最小人工复核"]
    bias_children.extend(t for t in titles if t in RIGOR_BIAS_EXTRAS)
    body = insert_group(body, "偏差控制与人工复核", bias_children)

    record_children = [t for t in titles if t in RIGOR_RECORD_EXTRAS]
    if record_children:
        body = insert_group(body, "补充示例与记录", record_children)

    return body


def transform_topic(body: str) -> str:
    titles = collect_h3_titles(body)
    if not all(t in titles for t in TOPIC_CHILDREN):
        return body
    if already_grouped(body):
        return body
    return insert_group(body, "专题实践三步", list(TOPIC_CHILDREN))


def transform_case(body: str) -> str:
    titles = collect_h3_titles(body)
    if "案例步骤一：保存输入与预期" not in titles:
        return body
    if already_grouped(body):
        return body
    body = insert_group(body, "案例执行流程", list(CASE_FLOW))
    if "案例验收清单" in titles:
        body = insert_group(body, "案例验收", ["案例验收清单"])
    return body


def transform_llm_deepening(body: str) -> str:
    titles = collect_h3_titles(body)
    if "使用真实输出建立判断" not in titles or "配套图解与代码示例" not in titles:
        return body
    if already_grouped(body) or "组件定位与实验设计" in titles:
        return body

    first = titles[0]
    design_children = [first, "使用真实输出建立判断", "本章可复现实验协议"]
    body = insert_group(body, "组件定位与实验设计", design_children)
    body = insert_group(
        body,
        "复核与发布决定",
        ["关键计算与人工复核", "从实验结果到发布决定"],
    )
    body = insert_group(
        body,
        "复盘与配套资产",
        [
            "研究者笔记：如何避免在本章自欺",
            "进一步推导：从 LLM 指标到策略价值",
            "给学员的复盘要求",
            "配套图解与代码示例",
        ],
    )
    return body


def transform_section(chapter_num: int, heading: str, body: str) -> str:
    title = heading_title(heading) if heading else ""

    body = apply_manual_groups(chapter_num, heading, body)

    if "量化严谨性检查" in title:
        body = transform_rigor(body)
    elif "专题讲解：把本章方法落到真实系统" in title:
        body = transform_topic(body)
    elif "完整案例记录：从委托到验收" in title:
        body = transform_case(body)
    elif title.endswith("LLM 与量化实战深化"):
        body = transform_llm_deepening(body)

    return body


def chapter_number(path: Path) -> int | None:
    match = re.match(r"^(\d+)-", path.name)
    return int(match.group(1)) if match else None


def process_file(path: Path) -> bool:
    num = chapter_number(path)
    if num is None or num in {0, 1}:
        return False

    text = path.read_text(encoding="utf-8")
    sections = split_sections(text)
    changed = False
    rebuilt: list[str] = []

    for heading, body in sections:
        new_body = transform_section(num, heading, body)
        if new_body != body:
            changed = True
        rebuilt.append(f"{heading}\n{new_body}" if heading else new_body)

    if changed:
        path.write_text("".join(rebuilt), encoding="utf-8")
    return changed


def main() -> int:
    updated: list[str] = []
    for path in sorted(CHAPTER_DIR.glob("[0-9][0-9]-*.md")):
        if "修订对照" in path.name:
            continue
        if process_file(path):
            updated.append(path.name)
    if updated:
        print("Updated headings in:")
        for name in updated:
            print(f"  - {name}")
    else:
        print("No chapter files needed heading updates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
