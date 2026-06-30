"""Add quant-rigor sections to every chapter.

The book is about LLM + quantitative trading, so each chapter must state the
calculation contract, assumptions, bias checks, and a manual replication task.
This script keeps that rigor reproducible after chapter regeneration.
"""

from __future__ import annotations

from pathlib import Path
import re

from rewrite_quant_course import CHAPTERS


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "v2"
MARKER = "<!-- quant-rigor-section -->"


PART_FORMULAS = {
    1: (
        "`H = (asset, window, trigger, benchmark, metric, reject_when)`",
        "研究假设只有在对象、窗口、触发条件、基准、评价指标和否定条件都明确时才可检验。",
    ),
    2: (
        "`r_t = P_t / P_(t-1) - 1`，`coverage = valid_rows / expected_rows`",
        "数据章节先检验价格、时间和覆盖率，再允许指标或 LLM 使用该输入。",
    ),
    3: (
        "`S_t = f_theta(C_t, D_t)`，`failure_rate = critical_failures / tasks`",
        "LLM 信号必须绑定数据、上下文和模型版本，并单独报告关键失败率。",
    ),
    4: (
        "`R_(t+1) = w_t * r_(t+1) - cost_t`，`MDD = max(1 - E_t / peak_t)`",
        "策略章节把信号转为仓位，再扣除成本，并同时报告收益和回撤。",
    ),
    5: (
        "`visible_claim = data_source + signal_version + assumption + risk_state`",
        "Web 章节要求页面上每个判断都能反向定位来源、版本、假设和风险状态。",
    ),
    6: (
        "`decision = reject if critical_failure else compare(metric_vector)`",
        "Skill、Automation 与 Eval 章节要求关键失败优先于平均分和自动化成功率。",
    ),
    7: (
        "`system_state = min(stage_status)`，任一关键阶段失败则端到端状态为停止",
        "综合实战章节用最弱环节决定系统能否交付，而不是用最终页面成功掩盖中间失败。",
    ),
}


PART_ASSUMPTIONS = {
    1: "固定研究对象、样本窗口、对照基准和否定条件；不得把模型语气强度当成概率。",
    2: "固定数据来源、保存时间、字段口径、缺失处理和快照版本；不得混用不同时间点证据。",
    3: "固定提示词、上下文字段、模型版本、温度和任务集；不得让模型补造未提供事实。",
    4: "固定成交时点、仓位函数、手续费、滑点、参数搜索范围和样本切分；不得回看未来。",
    5: "固定 API 字段、页面状态、数据来源标签和降级提示；不得把研究状态包装成交易建议。",
    6: "固定自动化权限、审批门、评分规程、版本号和审计字段；不得用平均分覆盖越权失败。",
    7: "固定端到端输入、模块合同、失败出口和验收命令；不得把单次演示当作系统可靠性。",
}


PART_BIASES = {
    1: "概念偷换、幸存者叙述、事后选择目标指标。",
    2: "时区错配、缺失填补过度、来源延迟、历史快照被覆盖。",
    3: "幻觉、提示泄漏、未来信息污染、任务集被反复调参污染。",
    4: "过拟合、前视偏差、数据窥探、费用低估、流动性约束缺失。",
    5: "视觉排序诱导、状态隐藏、过期数据伪装实时、置信度被误读成胜率。",
    6: "自动化沉默失败、审批门漂移、版本不可追溯、关键失败被均值掩盖。",
    7: "端到端缓存、模块字段语义不一致、失败只在日志中出现、验收范围被缩小。",
}


def block(chapter: dict[str, object]) -> str:
    n = int(chapter["num"])
    part = int(chapter["part"])
    title = str(chapter["title"])
    experiment = str(chapter["experiment"])
    failure = str(chapter["failure"])
    formula, formula_note = PART_FORMULAS[part]
    return f"""
{MARKER}
## {n}.10 量化严谨性检查

第 {n} 章“{title}”不能只交付一个流程说明，还必须交付可以被复算、反驳和复查的量化
合同。下面四项是本章进入出版稿前必须保留的硬内容。

### 变量与公式

第 {n} 章使用的最小量化表达是：{formula}。围绕“{title}”，{formula_note} 公式中的
每个变量都要能在本章输入、配置、代码或输出中找到对应位置；找不到来源的变量，不能
进入结论。

### 样本口径与成本假设

本章默认假设为：{PART_ASSUMPTIONS[part]} 执行“{experiment}”时，必须记录样本窗口、
数据频率、费用或成本口径、参数版本和失败状态。若本章暂不涉及真实成交，也要写明成本
为何不进入计算，不能把“未建模成本”误写成“成本为零”。

### 偏差来源与反例

本章最容易混入的偏差包括：{PART_BIASES[part]} 其中“{failure}”是本章必须主动注入或
人工构造的反例。若反例无法被系统识别，说明本章方法还没有达到可交付标准。

### 最小人工复核

完成第 {n} 章后，至少手工复核一个与“{experiment}”直接相关的数值或结构化判断：可以
是收益率、回撤、指标值、信号字段、评分项、页面状态或审批结果。复核记录必须写出原始
输入、代入公式、程序输出和差异解释。只有读者能够不依赖聊天记录复算“{title}”中的
关键结论，本章才算真正有干货。
"""


def main() -> None:
    for chapter in CHAPTERS:
        n = int(chapter["num"])
        paths = list(DOCS.glob(f"{n:02d}-*.md"))
        if len(paths) != 1:
            raise RuntimeError(f"expected one chapter {n}, found {paths}")
        path = paths[0]
        text = path.read_text(encoding="utf-8")
        text = re.sub(
            rf"\n{re.escape(MARKER)}\n.*?(?=\n## {n}\.\d+ 本章总结\n)",
            "\n",
            text,
            flags=re.DOTALL,
        )
        summary = re.search(rf"\n## {n}\.\d+ 本章总结\n", text)
        if summary is None:
            raise RuntimeError(f"missing summary in {path}")
        text = text[: summary.start()] + "\n" + block(chapter) + text[summary.start() :]
        text = re.sub(
            rf"^## {n}\.\d+ 本章总结\s*$",
            f"## {n}.11 本章总结",
            text,
            flags=re.MULTILINE,
        )
        text = re.sub(
            rf"^## {n}\.\d+ 课后题\s*$",
            f"## {n}.12 课后题",
            text,
            flags=re.MULTILINE,
        )
        path.write_text(text, encoding="utf-8")
        print(f"added quant rigor section to {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
