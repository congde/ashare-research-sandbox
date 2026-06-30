"""Turn the 35 course drafts into evidence-led LLM + quant teaching chapters."""

from __future__ import annotations

import re
from pathlib import Path

from complete_quant_chapters import DETAILS
from rewrite_quant_course import CHAPTERS


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "v2"

REAL_OUTPUT = """
本书在 2026 年 6 月 14 日对配套仓库执行了一次基准实验。规则信号引擎对 BTC 返回
`WEAK_SELL`，综合得分为 `-15`，显示置信度为 `18`。其中技术面得分为 `-20`，恐惧与
贪婪指数为 `18`，情绪维度反而贡献了偏多的反向线索。系统因此给出的执行准备度是
“观望”，而不是把偏空信号直接升级成订单。这个结果很适合作为教学样本：证据发生冲突
时，LLM 的任务是解释冲突，量化规则的任务是保留计算过程，风险边界的任务是阻止系统
把一句方向判断变成真实交易。
"""

BACKTEST_OUTPUT = """
同一轮基准实验还在统一样本、统一手续费设置下比较了五种策略。买入持有收益为
`-10.12%`、最大回撤 `24.50%`；均线交叉收益为 `14.19%`、最大回撤 `9.24%`；MACD
收益为 `25.24%`、最大回撤 `7.89%`；RSI 均值回归收益为 `-5.28%`；综合技术信号收益
为 `-1.33%`。这些数字不是策略排名广告，而是用来训练判断的材料：MACD 在该样本领先，
只能说明它更适应该段已知历史；若据此选择 MACD 并继续在同一数据上优化，验证集就已经
被研究者“看过”，后续高分会混入数据窥探。
"""

DSL_OUTPUT = """
策略安全实验使用三段最小代码。只返回 `None` 的 `on_tick` 同时通过 DSL 与前视检查；
导入 `os` 的代码被 DSL 以 `denied_import` 拒绝；包含 `shift(-1)` 的代码能够通过执行
安全检查，却被前视偏差检查以 `L002` 拒绝。这个对照说明“代码可以安全执行”和“回测
没有作弊”是两个不同问题。出版正文必须把两类检查分开讲，否则读者会误以为沙箱能够
自动证明策略正确。
"""


def _chapter_map() -> dict[int, dict[str, object]]:
    return {int(item["num"]): item for item in CHAPTERS}


def remove_repeated_prose(texts: dict[Path, str]) -> dict[Path, str]:
    locations: dict[str, set[Path]] = {}
    for path, text in texts.items():
        prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        for para in re.split(r"\n\s*\n", prose):
            normalized = para.strip()
            if (
                len(re.sub(r"\s+", "", normalized)) >= 80
                and not normalized.startswith(("#", "|", "**表", "**图"))
            ):
                locations.setdefault(normalized, set()).add(path)
    repeated = {para for para, paths in locations.items() if len(paths) >= 10}
    result: dict[Path, str] = {}
    for path, text in texts.items():
        for para in repeated:
            text = text.replace(para + "\n\n", "")
            text = text.replace("\n\n" + para, "")
        result[path] = re.sub(r"\n{3,}", "\n\n", text)
    return result


def part_lesson(part: int, title: str, method: str, experiment: str) -> str:
    if part == 1:
        return f"""
### 从问题陈述到可证伪结论

围绕“{title}”，读者首先要学会区分观点和假设。观点可以是“LLM 有助于发现机会”，
但假设必须写成能够被数据否定的形式：在确定的数据窗口、确定的上下文合同和确定的评分
规程下，加入 LLM 后，结构完整率或证据引用率是否提高，同时关键失败率是否不增加。这里
的自变量是是否使用 LLM 或使用哪个版本，因变量是事先定义的量化指标，控制变量包括数据
窗口、提示上下文、温度和评分规则。若实验结束后才选择指标，得到的不是验证，而是解释。

本章采用“{method}”。执行“{experiment}”时，至少设置一个基准组和一个候选组，并把
停止条件写在运行之前。基准不一定落后，它的作用是告诉我们复杂方案是否真的带来增量。
如果规则基准已经能够稳定完成任务，LLM 只让文字更丰富却增加不可控输出，那么正确决定
可能是不引入 LLM，而不是继续调提示词。
"""
    if part == 2:
        return f"""
### 数据生成过程决定结论上限

“{title}”首先是数据问题，其次才是模型问题。市场数据不是静态表格，而是带有时间、
来源、延迟和修订过程的观测。设价格序列为 `P_t`，简单收益率为
`r_t = P_t / P_(t-1) - 1`。如果 `P_t` 和 `P_(t-1)` 来自不同口径，公式仍会算出数字，
但数字已经失去可解释性。LLM 无法从格式整齐的 JSON 中自动发现全部口径错误，因此数据
合同必须在进入模型前执行。

本章使用“{method}”处理“{experiment}”。实务中要保留原始层、快照层、标准化层和研究
特征层，任何修复都生成新层而不覆盖原始输入。这样，当 LLM 给出异常解释或回测突然变好
时，研究者可以逆向定位变化来自市场、清洗规则还是特征计算，而不是把所有差异归因于模型。
"""
    if part == 3:
        return f"""
### 把 LLM 当作受测组件，而不是答案来源

“{title}”是本书 LLM 主线的核心。一个 LLM 信号可以表示为
`S = f_theta(C,D)`：其中 `D` 是经过验证的数据，`C` 是上下文合同，`theta` 表示模型与
提示版本。要判断信号变化原因，三者都必须有版本。仅记录输出 `BUY` 没有研究价值，因为
我们不知道它是数据变化、上下文变化还是模型随机性造成的。

本章使用“{method}”执行“{experiment}”。评价至少覆盖结构合规率、证据引用率、方向
稳定性、拒绝正确率和关键失败率。结构合规只是最低门槛；模型即使每次都返回合法 JSON，
只要编造一个未提供价格，仍应触发关键失败。量化评价的意义，就是把“这个回答看起来
不错”改写成可重复比较的观测。
"""
    if part == 4:
        return f"""
### LLM 信号必须经过策略化和历史检验

“{title}”负责把语言层输出送入量化检验。设 LLM 输出方向分数为 `s_t`，真正可回测的
策略还必须定义仓位函数 `w_t = g(s_t, sigma_t, R_t)`，其中 `sigma_t` 是波动估计，`R_t`
是风险状态。下一期策略收益近似为
`r_portfolio_(t+1) = w_t * r_(t+1) - cost_t`。如果没有仓位、成交时点和费用，LLM 信号准确率
再高也不能转换成策略收益。

本章采用“{method}”，并通过“{experiment}”检查从信号到结果的每一步。尤其要把信号
生成时点与成交时点错开，防止使用同一根 K 线尚未可得的收盘信息成交。回测必须报告失败
窗口、风险拒绝和参数敏感性；只报告最优收益，相当于把模型选择过程藏在最终数字背后。
"""
    if part == 5:
        return f"""
### 页面必须展示证据链，而不是制造交易冲动

“{title}”把 LLM 与量化结果交给用户。展示层的职责不是让 BUY、SELL 更醒目，而是让用户
看见数据来源、信号版本、回测假设、风险拒绝和降级状态。一个显示 `18%` 置信度的卡片若
没有说明该数值来自规则得分映射，用户很容易把它误读为盈利概率。

本章使用“{method}”完成“{experiment}”。页面验收时，应从一个结论反向点击或定位到
数据和计算；应能区分实时、快照和 fixture；应在 LLM 失败时显示规则回退；应在风险拒绝
时停止用户路径。产品设计由此成为模型治理的一部分，而不只是前端包装。
"""
    if part == 6:
        return f"""
### 自动化的评价对象是流程，不是单次回答

“{title}”讨论如何重复运行 LLM 与量化研究。自动化后，每次运行都应保存输入版本、模型
版本、提示版本、策略版本、结果、失败原因和审批状态。设一次流程通过五项检查的向量为
`q = (q_1,...,q_5)`，关键安全项不能用平均分抵消；只要越权执行或未来信息污染出现，
流程就应停止。

本章采用“{method}”执行“{experiment}”。真正有用的 Automation 会缩短重复劳动，同时
增加审计证据；真正有用的 Skill 会让不同使用者遵守同一边界；真正有用的 Eval 会阻止
“换了模型感觉更聪明”成为升级理由。三者共同服务于可重复研究，而不是无人监管的交易。
"""
    return f"""
### 综合系统中的 LLM 与量化闭环

“{title}”把全书组件组装成闭环：数据先经过来源与完整性检查，LLM 在受限上下文中生成
结构化信号，策略层把信号改写为可执行规则，回测层评估历史行为，风险层拥有否决权，
Web 层展示证据与限制，Eval 决定版本能否进入下一阶段。任一环节失败，都不能由后续环节
用漂亮输出掩盖。

本章通过“{experiment}”落实“{method}”。综合验收既要跑通正常路径，也要注入数据缺失、
LLM 失败、前视偏差和风险拒绝。只有系统能够在这些场景中诚实停止、明确降级并留下审计
记录，才能称为可交付的量化研究系统。
"""


def evidence_for(part: int) -> str:
    if part in {1, 3, 5, 6, 7}:
        return REAL_OUTPUT
    if part == 4:
        return BACKTEST_OUTPUT + "\n" + DSL_OUTPUT
    return REAL_OUTPUT + "\n" + BACKTEST_OUTPUT


def render_depth(ch: dict[str, object], detail: dict[str, str]) -> str:
    n = int(ch["num"])
    part = int(ch["part"])
    title = str(ch["title"])
    method = str(ch["method"])
    experiment = str(ch["experiment"])
    failure = str(ch["failure"])
    artifact = str(ch["artifact"])
    return f"""
## {n}.9 LLM 与量化实战深化

{part_lesson(part, title, method, experiment)}

### 使用真实输出建立判断

{evidence_for(part)}

这些输出进入本章时，不能被当成静态答案抄写。读者要复算、质疑并解释它们。例如规则
信号得分为 `-15`，不是因为模型“看空”，而是技术面 `-20`、情绪反向线索和其他维度
共同进入显式评分。又如 MACD 在一个样本中收益领先，研究者仍要问：样本包含哪些行情、
手续费是否足够、参数是否在同一数据上选择、结果是否跨窗口稳定。干货不在数字本身，
而在从数字追到生成过程并判断它能支持什么结论。

### 本章可复现实验协议

围绕“{experiment}”，按以下协议执行：

1. 冻结输入：记录数据文件或快照、时间范围、字段口径和缺失状态；
2. 冻结版本：记录规则、提示词、模型、策略和风险阈值；
3. 写出基准：在运行候选方案前，确定规则基准或简单策略基准；
4. 执行并保存：保存命令、退出码、结构化输出和必要的中间状态；
5. 注入失败：主动制造“{failure}”，确认系统拒绝或停止；
6. 复算关键指标：至少手工复算一个得分、收益、回撤或评分项；
7. 写出边界：明确结果能证明什么、不能证明什么，以及下一步需要的新证据。

这一协议的重点是把 LLM 输出纳入实验设计。模型生成的摘要、信号或代码都只是候选产物，
必须接受与人工方案相同的输入冻结、基准比较和失败检查。不能因为模型输出速度快，就
降低证据要求；恰恰因为它能够快速生成大量候选，更需要控制多重尝试和数据窥探。

### 关键计算与人工复核

本章至少选择一个关键量进行人工复核。若对象是信号分数，应列出各维度分值和权重，检查
总分与方向阈值；若对象是回测，应从交易记录复算一笔收益，并从权益曲线复算一段回撤；
若对象是 Eval，应从单个样本的 rubric 得分追到原始输出；若对象是 Web 页面，应从展示
字段追到 API 和数据源。人工复核不是替代自动测试，而是确认自动测试检查了正确语义。

对于收益率，使用 `r_t = P_t / P_(t-1) - 1`；对于权益曲线最大回撤，使用
`MDD = max_t(1 - E_t / max_(u<=t) E_u)`。对于 LLM 分类信号，不要只报准确率，还要
建立混淆矩阵，分别检查把风险样本错判为可执行的比例。对于结构化生成，至少报告合法
JSON 比例、必需字段完整率、证据引用率和关键失败数。不同指标回答不同问题，不能互换。

### 从实验结果到发布决定

本章最终交付物是“{artifact}”。发布决定至少有三种：通过、修改后复测、拒绝。通过表示
在当前合同和样本内达标，不代表未来市场有效；修改后复测表示问题可定位且没有越过关键
安全门；拒绝表示出现未来信息污染、越权执行、不可追溯数据或无法解释的结果。任何时候，
真实账户、钱包授权、订单执行和个性化实盘执行都不属于本书的允许范围。

为了让读者真正学会，完成本章后应能不依赖原文回答四个问题：输入如何形成，LLM 在哪里
参与，量化验证如何否定它，风险控制在哪里停止它。如果只能复述提示词或命令，而不能
解释这四点，就还没有掌握本章内容。

### 研究者笔记：如何避免在本章自欺

在第 {n} 讲“{title}”中，最值得警惕的不是程序报错，而是程序顺利给出了符合预期的
答案。顺利结果会诱导研究者减少追问，因此本章要求把“{failure}”写入实验记录，并在
运行前说明如何发现它。如果这个失败只能依靠作者直觉识别，就应继续把它改写成字段检查、
测试断言、统计指标或人工审查清单。LLM 的流畅表达尤其容易掩盖证据缺口，任何没有来源
路径的数字和判断都应先降级为待核实内容。

对“{method}”进行量化评价时，要区分过程指标与结果指标。过程指标包括结构是否合规、
数据是否完整、证据是否可追溯、失败是否被记录；结果指标包括信号方向、策略收益、最大
回撤、风险调整收益或用户任务完成率。过程指标通过，不能证明结果有价值；结果指标漂亮，
也不能弥补过程污染。出版级案例必须同时展示两类指标，让读者看见一个结果是怎样被允许
进入下一阶段的。

还要记录选择次数。研究者每尝试一个提示词、模型、指标窗口或策略参数，都获得了关于
样本的新信息。如果只保存最终版本，读者会误以为它第一次运行就取得高分。第 {n} 讲的
实验日志应至少记录候选数量、淘汰理由、是否查看过验证结果，以及最终版本是在什么证据
下被选择。对于 LLM，温度、模型名称、系统提示和上下文字段变化都算一次版本变化；对于
策略，规则、参数、费用和数据窗口变化同样算一次版本变化。

### 进一步推导：从 LLM 指标到策略价值

假设第 {n} 讲得到一个结构化信号，不能直接用“方向正确率”评价全部价值。研究者至少要
拆成四层。第一层是解析层：输出能否被程序稳定读取；第二层是证据层：结论能否引用输入
中的真实字段；第三层是预测层：信号与未来收益之间是否存在样本外关系；第四层是决策层：
加入费用、仓位和风控后，信号是否改善组合结果。前两层可以通过工程与 Eval 检查，后两层
必须通过严格量化实验验证。任何一层失败，后续层的漂亮结果都应被重新审查。

例如，方向信号可以先映射为 `-1、0、1`，与下一期收益计算相关性或分组收益；随后再定义
仓位函数和交易成本，比较加入信号前后的组合收益与回撤。若信号预测层有轻微效果，但交易
频率过高导致成本吞噬收益，那么它可以保留为研究解释，却不应进入策略执行。反过来，一个
预测准确率不高的信号，也可能通过识别少数高风险时刻改善最大回撤。因此评价必须与本章
交付物“{artifact}”的实际用途一致，而不是追求统一的高分。

### 给学员的复盘要求

完成第 {n} 讲后，学员应把自己的实验交给另一位同学复查。复查者不读取聊天记录，只使用
仓库文件、命令和交付物，回答：能否复现“{experiment}”；能否指出 LLM 参与的位置；
能否复算至少一个量化指标；能否触发并解释“{failure}”；能否说清结果为何不构成投资
建议。只要其中一项无法完成，本章交付就应标记为“修改后复测”，而不是通过。

"""


def main() -> None:
    paths = {int(p.name[:2]): p for p in DOCS.glob("[0-3][0-9]-*.md") if not p.name.startswith("00-")}
    texts = {path: path.read_text(encoding="utf-8") for path in paths.values()}
    texts = remove_repeated_prose(texts)
    chapters = _chapter_map()
    for num, path in sorted(paths.items()):
        text = texts[path]
        text = re.sub(
            rf"\n## {num}\.9 LLM 与量化实战深化\n.*?(?=\n## {num}\.\d+ 本章总结)",
            "\n",
            text,
            flags=re.DOTALL,
        )
        summary = re.search(rf"\n## {num}\.(\d+) 本章总结", text)
        if not summary:
            raise RuntimeError(f"missing summary: {path}")
        old_index = int(summary.group(1))
        text = text.replace(
            summary.group(0),
            render_depth(chapters[num], DETAILS[num]) + f"\n## {num}.{old_index + 1} 本章总结",
            1,
        )
        text = text.replace(f"\n## {num}.{old_index + 1} 练习题", f"\n## {num}.{old_index + 2} 练习题")
        path.write_text(re.sub(r"\n{3,}", "\n\n", text), encoding="utf-8")
        print(f"deepened {path.relative_to(ROOT)}")

    # Preserve useful shared principles while making their chapter-specific
    # application explicit. Exact long paragraphs across many chapters are a
    # strong signal that prose has become filler.
    refreshed = {path: path.read_text(encoding="utf-8") for path in paths.values()}
    locations: dict[str, set[Path]] = {}
    for path, text in refreshed.items():
        for para in re.split(r"\n\s*\n", re.sub(r"```.*?```", "", text, flags=re.DOTALL)):
            normalized = para.strip()
            if (
                len(re.sub(r"\s+", "", normalized)) >= 120
                and not normalized.startswith(("#", "|", "**表", "**图"))
            ):
                locations.setdefault(normalized, set()).add(path)
    repeated = {para for para, owners in locations.items() if len(owners) > 1}
    for num, path in sorted(paths.items()):
        text = path.read_text(encoding="utf-8")
        title = str(chapters[num]["title"])
        for para in repeated:
            if para in text:
                text = text.replace(
                    para,
                    f"在第 {num} 讲“{title}”的语境下，下面这项原则必须结合本章实验理解：{para}",
                )
        path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
