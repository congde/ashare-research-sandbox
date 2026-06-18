"""Canonical map: every PNG in docs/v2/assets → publishable chapter usage."""

from __future__ import annotations

# filename -> (chapter markdown basename prefix like "02-", alt text, figure caption suffix)
ASSET_USAGE: dict[str, tuple[str, str, str]] = {
    # --- 开篇词：课程总览 + 产品界面实拍 ---
    "chapter-00-delivery-chain.png": (
        "00-",
        "从模糊想法到可复用工作手册",
        "从模糊想法到标准作业手册（Playbook）的交付链",
    ),
    "codex-course-map.png": (
        "00-",
        "四篇三十三讲内容地图",
        "四篇三十三讲与调研—产品—实现—固化主线",
    ),
    "codex-learning-paths.png": (
        "00-",
        "三条学习路径对照",
        "表 0-1 三条学习路径在交付链上的位置",
    ),
    "codex-course-overview.png": (
        "00-",
        "课程总览与案例关系",
        "课程总览：创意交付与 Web3 教学沙盒",
    ),
    "codex-delivery-loop.png": (
        "00-",
        "委托到交接的工作闭环",
        "委托、验收、检查点与交接（总览版）",
    ),
    "chapter-00-项目首页.png": (
        "00-",
        "Web3 研究与模拟策略验证台项目首页",
        "项目首页：交易总览与教学沙箱边界",
    ),
    "数据源和接入状态.png": (
        "00-",
        "数据源与接入状态页",
        "侧栏「数据源」：接入顺序与离线回退",
    ),
    "回测详情.png": (
        "26-",
        "回测组合图表",
        "回测页：日 K、权益曲线与买卖标记（BacktestComboChart）",
    ),
    "策略DSL.png": (
        "00-",
        "策略 DSL 校验页",
        "侧栏「策略 DSL」：受限代码校验与风险提示",
    ),
    "风控中心.png": (
        "00-",
        "风控中心页",
        "侧栏「风控中心」：回测后模拟风控提示",
    ),
    "多策略比较.png": (
        "21-",
        "多策略比较表",
        "回测页五策略同屏比较（收益、回撤、Sharpe、交易数）",
    ),
    "成交明细.png": (
        "26-",
        "成交明细表",
        "回测页逐笔交易：入场/出场、PnL、平仓原因、持仓K",
    ),
    "雷达数据-今日机会.png": (
        "00-",
        "机会雷达页",
        "侧栏「雷达」：机会扫描与离线快照",
    ),
    "AI机会+资金异动+风险回避.png": (
        "00-",
        "雷达页机会与风险卡片",
        "雷达模块：机会、资金异动与风险回避信息",
    ),
    "市场情报-LLM信号分析.png": (
        "00-",
        "市场情报与 LLM 信号分析",
        "侧栏「市场情报」：信号摘要（教学样本）",
    ),
    "市场情报-K线分析.png": (
        "00-",
        "市场情报 K 线分析",
        "市场情报：K 线与来源说明",
    ),
    "代币资金+Dex数据.png": (
        "00-",
        "代币资金与 Dex 数据面板",
        "Dashboard 数据：代币资金与 Dex 快照",
    ),
    "chapter-20-checkpoint-loop.png": (
        "20-",
        "从委托到验收与交接的工作闭环",
        "长任务中的检查点与反馈闭环",
    ),
    # --- 第 1 讲 ---
    "chapter-01-idea-layers.png": (
        "01-",
        "从愿望到可执行任务的层次差异",
        "从愿望到可执行任务的层次差异",
    ),
    "chapter-01-assumption-chain.png": (
        "01-",
        "模糊想法如何放大未经授权的猜测",
        "模糊想法如何放大未经授权的猜测",
    ),
    "chapter-01-goal-funnel.png": (
        "01-",
        "从愿望到决策目标的收窄",
        "愿望如何收窄为可讨论的决策目标",
    ),
    "chapter-01-question-to-brief.png": (
        "01-",
        "从自然语言问题到 Brief 要素",
        "自然语言问题与 Brief 五要素的对应关系",
    ),
    "chapter-01-brief-anatomy.png": (
        "02-",
        "Brief 五要素结构",
        "Brief 五要素与合同文件字段对照",
    ),
    "chapter-01-brief-quality-gates.png": (
        "02-",
        "Brief 质量门",
        "Brief 放行前的质量门",
    ),
    "chapter-01-constraint-boundaries.png": (
        "02-",
        "边界与禁止项如何约束范围",
        "边界、禁止项与 Open questions 的约束关系",
    ),
    "chapter-01-lab-loop.png": (
        "01-",
        "假设清单与练习闭环",
        "从假设清单到第一讲交付物的练习闭环",
    ),
    "chapter-01-machine-human-review.png": (
        "03-",
        "机器检查与人工复核分工",
        "机器检查与人工判断的证明边界（补充）",
    ),
    # --- 第 2–7 讲：主图 + 补充流程图 ---
    "chapter-02-brief-conversion.png": (
        "02-",
        "从自然请求到可委托 Brief 的转换过程",
        "从自然请求到可委托 Brief 的转换过程",
    ),
    "chapter-02-brief-contract.png": (
        "02-",
        "Brief 五部分怎样共同限制任务漂移",
        "Brief 五部分怎样共同限制任务漂移",
    ),
    "chapter-02-design-loop.png": (
        "02-",
        "验收设计闭环",
        "从 Done when 反推的验收设计闭环",
    ),
    "chapter-02-acceptance-pipeline.png": (
        "03-",
        "从交付物到放行决定",
        "调研验收：从交付物到放行决定",
    ),
    "chapter-02-traceability-chain.png": (
        "03-",
        "主张追溯链",
        "来源—事实—推断—建议的追溯链",
    ),
    "chapter-02-three-layers.png": (
        "03-",
        "证明责任三层",
        "来源、主张与产品决定的三层证明责任",
    ),
    "chapter-02-decision-tree.png": (
        "07-",
        "方向决定决策树",
        "Go / Revise / No-Go 决策树（补充）",
    ),
    "chapter-03-evidence-ladder.png": (
        "03-",
        "从来源到产品决定的证明责任阶梯",
        "从来源到产品决定的证明责任阶梯",
    ),
    "chapter-03-acceptance-gates.png": (
        "03-",
        "调研验收的通过、拒绝与停止三道门",
        "调研验收的通过、拒绝与停止三道门",
    ),
    "chapter-03-capability-decision.png": (
        "05-",
        "入口能力决策",
        "按能力需求选择 Codex 入口",
    ),
    "chapter-04-context-layers.png": (
        "04-",
        "上下文包的六层资料分级",
        "上下文包的六层资料分级",
    ),
    "chapter-04-context-mapping.png": (
        "04-",
        "从验收条件反推资料与能力需求",
        "从验收条件反推资料与能力需求",
    ),
    "chapter-04-claim-ledger.png": (
        "06-",
        "主张台账流程",
        "主张台账：从来源到 F/I/R/U",
    ),
    "chapter-04-price-signal-equity.png": (
        "04-",
        "价格、信号与策略累计收益三面板",
        "3/7 双均线：价格+指标、规则信号、shift(1) 策略路径（参考 Qbot 01-strategy）",
    ),
    "chapter-05-entry-decision.png": (
        "05-",
        "任务能力到 Codex 入口的选择路径",
        "任务能力到 Codex 入口的选择路径",
    ),
    "chapter-05-workspace-boundary.png": (
        "05-",
        "受控工作区中的权限、规则与证据流",
        "受控工作区中的权限、规则与证据流",
    ),
    "chapter-05-publish-pipeline.png": (
        "04-",
        "可发版资料流水线",
        "资料进入工作区前的分层审查流水线",
    ),
    "chapter-06-claim-flow.png": (
        "06-",
        "事实、推断、建议与未知的流转关系",
        "事实、推断、建议与未知的流转关系",
    ),
    "chapter-06-research-rounds.png": (
        "06-",
        "分轮调研如何阻止证据升级",
        "分轮调研如何阻止证据升级",
    ),
    "chapter-06-evidence-gates.png": (
        "17-",
        "证据门推进流程",
        "计划里程碑中的证据门推进",
    ),
    "chapter-06-plan-anatomy.png": (
        "17-",
        "可执行计划四个支点",
        "可执行计划：Brief、证据门、停止与 Handoff",
    ),
    "chapter-07-decision-path.png": (
        "07-",
        "从调研证据到三类方向决定",
        "从调研证据到三类方向决定",
    ),
    "chapter-07-reversible-decision.png": (
        "07-",
        "方向决定的复核与撤销机制",
        "方向决定的复核与撤销机制",
    ),
    "chapter-07-mcp-audit.png": (
        "05-",
        "MCP 调用审计时序",
        "外部工具（MCP）调用的审计时序",
    ),
    "chapter-07-claim-ledger.png": (
        "06-",
        "主张台账与决策包对照",
        "主张台账字段与调研决策包对照",
    ),
    # --- 第二篇 8–13 ---
    "chapter-08-stakeholders.png": (
        "08-",
        "需求提出者、使用者、决策者与风险承担者关系图",
        "需求提出者、使用者、决策者与风险承担者关系图",
    ),
    "chapter-08-user-convergence.png": (
        "08-",
        "从调研证据收敛核心用户的过程",
        "从调研证据收敛核心用户的过程",
    ),
    "chapter-08-browser-state-machine.png": (
        "22-",
        "浏览器流程状态机",
        "浏览器用户路径的状态机（补充）",
    ),
    "chapter-09-problem-funnel.png": (
        "09-",
        "从功能请求到真实用户问题的追问漏斗",
        "从功能请求到真实用户问题的追问漏斗",
    ),
    "chapter-09-problem-structure.png": (
        "09-",
        "问题定义中的任务、阻碍、结果与风险",
        "问题定义中的任务、阻碍、结果与风险",
    ),
    "chapter-09-skill-extraction.png": (
        "29-",
        "从真实轨迹提炼 Skill",
        "从成功轨迹提炼 Skill 的流程（预告）",
    ),
    "chapter-09-indicators-panel.png": (
        "09-",
        "固定样本上的趋势动量波动指标",
        "SMA20、RSI、布林带与 ATR 同屏（参考 Qbot notebook 出图）",
    ),
    "chapter-10-solution-space.png": (
        "10-",
        "从问题定义到候选方案的展开与收敛",
        "从问题定义到候选方案的展开与收敛",
    ),
    "chapter-10-tradeoff-triangle.png": (
        "10-",
        "方案选择的价值—风险—可验证性三角",
        "方案选择的价值—风险—可验证性三角",
    ),
    "chapter-11-mvp-loop.png": (
        "11-",
        "功能清单与最小完整闭环的区别",
        "功能清单与最小完整闭环的区别",
    ),
    "chapter-11-scope-boundary.png": (
        "11-",
        "第一版范围内外与审批边界",
        "第一版范围内外与审批边界",
    ),
    "chapter-11-data-pipeline.png": (
        "14-",
        "数据处理三段流水线",
        "数据处理：剖析、转换与对账",
    ),
    "chapter-13-slice-vs-module.png": (
        "13-",
        "横向模块切分与用户竖切对照",
        "横向模块切分与用户竖切对照",
    ),
    "chapter-13-user-loop.png": (
        "13-",
        "主案例第一条用户闭环状态图",
        "主案例第一条用户闭环状态图",
    ),
    "chapter-13-recon-loop.png": (
        "18-",
        "假设驱动的仓库勘察循环",
        "开工前：假设驱动的仓库勘察循环",
    ),
    "chapter-12-prd-review.png": (
        "12-",
        "PRD 审查中的发现、建议与人工决定",
        "PRD 审查中的发现、建议与人工决定",
    ),
    "chapter-12-stress-test.png": (
        "12-",
        "从正常路径到边界与滥用场景的压力测试",
        "从正常路径到边界与滥用场景的压力测试",
    ),
    "chapter-12-rules-compile.png": (
        "21-",
        "把规则编译成执行清单",
        "把 AGENTS 与 verify 规则编译成执行清单（对照）",
    ),
    "chapter-15-automation-envelope.png": (
        "15-",
        "第一版权限包络线",
        "第一版实现方式的权限包络线",
    ),
    "chapter-15-vertical-slice.png": (
        "13-",
        "可审查竖切",
        "可审查竖切与模块切分的对照（补充）",
    ),
    "chapter-16-migration-path.png": (
        "16-",
        "上游基线到课程实现的选择性迁移路径",
        "上游基线到课程实现的选择性迁移路径",
    ),
    "chapter-16-fusion-boundary.png": (
        "16-",
        "双上游能力融合与隔离边界",
        "双上游能力融合与隔离边界",
    ),
    "chapter-16-review-priority.png": (
        "20-",
        "按风险优先级做 Review",
        "Diff 审查：按风险优先级排序",
    ),
    "chapter-16-breakout-signal-equity.png": (
        "16-",
        "通道突破规则三面板",
        "价格/前高前低/信号/路径（参考 Qbot 01-strategy 第二段）",
    ),
    "chapter-17-milestones.png": (
        "17-",
        "从用户闭环到证据门里程碑",
        "从用户闭环到证据门里程碑",
    ),
    "chapter-17-checkpoints.png": (
        "17-",
        "检查点、停止、恢复与交接关系",
        "检查点、停止、恢复与交接关系",
    ),
    "chapter-17-parallel-deps.png": (
        "17-",
        "并行任务依赖与所有权",
        "并行里程碑的依赖与所有权",
    ),
    "chapter-17-ma-crossover-trades.png": (
        "17-",
        "3/7 双均线交叉买卖点",
        "固定样本上的金叉/死叉标记（参考 Qbot average.ipynb）",
    ),
    "chapter-18-repo-map.png": (
        "18-",
        "从仓库入口到验证入口的工程地图",
        "从仓库入口到验证入口的工程地图",
    ),
    "chapter-18-ownership-boundary.png": (
        "18-",
        "产品规则、目录所有权与修改权限关系",
        "产品规则、目录所有权与修改权限关系",
    ),
    "chapter-18-eval-loop.png": (
        "31-",
        "评测改进循环",
        "Eval 改进循环（与第 31 讲呼应）",
    ),
    "chapter-18-event-backtest-combo.png": (
        "18-",
        "事件驱动回测组合图",
        "日 K 成交标记 + 权益曲线（参考 average.ipynb / BacktestComboChart）",
    ),
    "chapter-18-macd-trailing-backtest.png": (
        "18-",
        "MACD 事件回测三面板",
        "MACD 柱 + 成交 + 权益（参考 bitcoin_bt_example 叙事）",
    ),
    "chapter-18-backtrader-vs-local.png": (
        "18-",
        "Cerebro 装配 vs 本地事件引擎",
        "Qbot 03-backtrader.ipynb 装配顺序对照（概念图）",
    ),
    "chapter-19-data-pipeline.png": (
        "19-",
        "竖切实现中的输入保护与边界检查点",
        "竖切实现中的输入保护与边界检查点",
    ),
    "chapter-19-delivery-bundle.png": (
        "32-",
        "毕业交付包流转",
        "毕业交付包流转（对照）",
    ),
    "chapter-19-metrics-comparison.png": (
        "19-",
        "多策略收益与回撤对比",
        "同窗口五策略：累计收益 vs 最大回撤（参考 quantstats-rolling 思路）",
    ),
    "chapter-19-equity-drawdown.png": (
        "19-",
        "权益曲线与最大回撤",
        "权益路径、历史峰值与回撤阴影（参考 Qbot pandas.ipynb）",
    ),
    "chapter-20-checkpoint-loop.png": (
        "20-",
        "长任务中的检查点与反馈闭环",
        "长任务中的检查点与反馈闭环",
    ),
    "chapter-20-scope-drift.png": (
        "20-",
        "范围漂移从出现到纠偏的路径",
        "范围漂移从出现到纠偏的路径",
    ),
    "chapter-20-playbook-ladder.png": (
        "33-",
        "Playbook 推广阶梯",
        "Playbook 推广阶梯（对照）",
    ),
    "chapter-21-diagram.png": (
        "21-",
        "从代码运行到可靠交付的证据层级",
        "从代码运行到可靠交付的证据层级",
    ),
    "chapter-21-rules-compile.png": (
        "21-",
        "自动验收覆盖范围与人工判断缺口",
        "自动验收覆盖范围与人工判断缺口",
    ),
    "chapter-21-factor-mining-pipeline.png": (
        "21-",
        "因子挖掘工业流水线与本沙箱覆盖范围",
        "因子挖掘：业界流水线与本沙箱边界（图 21-5）",
    ),
    "chapter-21-factor-ic-panel.png": (
        "21-",
        "因子 IC 与 train/test 对比",
        "基线 IC + GP/ML leader train/test（参考 02-alphalens 精简）",
    ),
    "chapter-21-rolling-sharpe.png": (
        "21-",
        "滚动 Sharpe 曲线",
        "由权益序列推导的滚动 Sharpe（参考 quantstats-rolling）",
    ),
    "chapter-21-compare-windows.png": (
        "21-",
        "多窗口收益与回撤",
        "compare_windows 三分窗并排（稳定性检查）",
    ),
    "chapter-22-path-state.png": (
        "22-",
        "浏览器用户路径的状态机与证据点",
        "浏览器用户路径的状态机与证据点",
    ),
    "chapter-22-evidence-mix.png": (
        "22-",
        "自动测试、浏览器证据与人工复核的互补关系",
        "自动测试、浏览器证据与人工复核的互补关系",
    ),
    "chapter-23-fix-loop.png": (
        "23-",
        "从问题报告到回归验证的修复闭环",
        "从问题报告到回归验证的修复闭环",
    ),
    "chapter-23-bypass-fork.png": (
        "23-",
        "修复产品与绕过验收的分叉路径",
        "修复产品与绕过验收的分叉路径",
    ),
    "chapter-14-red-green.png": (
        "23-",
        "先红后绿的热修复闭环",
        "先红后绿：修复闭环与测试纪律",
    ),
    "chapter-14-data-chain.png": (
        "14-",
        "数据来源、处理、指标与解释的影响链",
        "数据来源、处理、指标与解释的影响链",
    ),
    "chapter-14-sample-tradeoff.png": (
        "14-",
        "固定样本如何换取可复现性，又失去实时性",
        "固定样本如何换取可复现性，又失去实时性",
    ),
    "chapter-24-handoff-pack.png": (
        "24-",
        "从实现结果到可接手交付包",
        "从实现结果到可接手交付包",
    ),
    "chapter-24-handoff-test.png": (
        "24-",
        "接手测试的信息流与失败反馈",
        "接手测试的信息流与失败反馈",
    ),
    "chapter-25-task-design.png": (
        "25-",
        "从产品问题到用户测试任务的转换",
        "从产品问题到用户测试任务的转换",
    ),
    "chapter-25-observation-roles.png": (
        "25-",
        "用户测试中的任务、观察与判断分工",
        "用户测试中的任务、观察与判断分工",
    ),
    "chapter-26-observation-layers.png": (
        "26-",
        "用户行为、观察记录与研究者解释的分层",
        "用户行为、观察记录与研究者解释的分层",
    ),
    "chapter-26-pattern-cluster.png": (
        "26-",
        "从单次问题到跨用户模式的归类过程",
        "从单次问题到跨用户模式的归类过程",
    ),
    "chapter-27-version-decision.png": (
        "27-",
        "从用户证据到版本决定的判断路径",
        "从用户证据到版本决定的判断路径",
    ),
    "chapter-27-decision-frame.png": (
        "27-",
        "价值、风险、成本与学习速度的版本决策框架",
        "价值、风险、成本与学习速度的版本决策框架",
    ),
    "chapter-28-automation-path.png": (
        "28-",
        "从重复任务到自动化边界的评估路径",
        "从重复任务到自动化边界的评估路径",
    ),
    "chapter-28-approval-gates.png": (
        "28-",
        "自动化等级与人工审批门",
        "自动化等级与人工审批门",
    ),
    "chapter-10-automation-envelope.png": (
        "28-",
        "自动化权限包络线",
        "自动化权限包络线（补充）",
    ),
    "chapter-29-skill-contract.png": (
        "29-",
        "从一次成功轨迹到 Skill 契约",
        "从一次成功轨迹到 Skill 契约",
    ),
    "chapter-29-skill-anatomy.png": (
        "29-",
        "Skill 的说明、资源、脚本与输出关系",
        "Skill 的说明、资源、脚本与输出关系",
    ),
    "chapter-30-automation-path.png": (
        "30-",
        "Automation 从触发到人工审批的执行路径",
        "Automation 从触发到人工审批的执行路径",
    ),
    "chapter-30-failure-states.png": (
        "30-",
        "失败、降级、暂停与恢复状态图",
        "失败、降级、暂停与恢复状态图",
    ),
    "chapter-31-diagram.png": (
        "31-",
        "轨迹记录、评分规程与样本驱动改进",
        "轨迹记录、评分规程与样本驱动改进",
    ),
    "chapter-31-eval-loop.png": (
        "31-",
        "平均分与关键失败门的差异",
        "平均分与关键失败门的差异",
    ),
    "chapter-32-diagram.png": (
        "32-",
        "毕业项目从想法到交付包的阶段门",
        "毕业项目从想法到交付包的阶段门",
    ),
    "chapter-32-delivery-bundle.png": (
        "32-",
        "毕业交付包中事实、产品、实现与验证证据关系",
        "毕业交付包中事实、产品、实现与验证证据关系",
    ),
    "chapter-33-diagram.png": (
        "33-",
        "从个人实践到可复用 Playbook 的知识阶梯",
        "从个人实践到可复用 Playbook 的知识阶梯",
    ),
    "chapter-33-playbook-ladder.png": (
        "33-",
        "Playbook 接手测试与持续改进循环",
        "Playbook 接手测试与持续改进循环",
    ),
}

# Legacy-only main diagrams: wire into matching publishable chapter as 补充图
for n in range(2, 21):
    key = f"chapter-{n:02d}-diagram.png"
    if key not in ASSET_USAGE:
        prefix = f"{n:02d}-"
        ASSET_USAGE[key] = (
            prefix,
            f"第 {n} 讲主图（补充）",
            f"第 {n} 讲核心概念总览",
        )

# drawio export artifacts — same target as non-drawio sibling
for key in list(ASSET_USAGE):
    if key.endswith(".png") and not key.endswith(".drawio.png"):
        drawio_key = key.replace(".png", ".drawio.png")
        if drawio_key not in ASSET_USAGE:
            ASSET_USAGE[drawio_key] = ASSET_USAGE[key]

# chapter-14-diagram special
ASSET_USAGE.setdefault(
    "chapter-14-diagram.png",
    ("14-", "数据与证据主图（补充）", "第 14 讲：数据链与证据优先"),
)

ASSET_USAGE.setdefault(
    "chapter-02-lab-loop.png",
    ("02-", "Brief 练习闭环", "从假设清单到 Brief 评审的练习闭环"),
)

ASSET_USAGE.setdefault(
    "chapter-02-evidence-loop.png",
    ("03-", "证据与验收闭环", "调研证据与验收合同的闭环"),
)

ASSET_USAGE.setdefault(
    "chapter-09-problem-frame.png",
    ("09-", "问题框架四象限", "问题定义：任务、阻碍、结果与风险（框架图）",
    ),
)

ASSET_USAGE.setdefault(
    "chapter-15-diagram.png",
    ("15-", "第一版实现方式总览", "第一版实现方式选择总览",
    ),
)

ASSET_USAGE.setdefault(
    "chapter-19-diagram.png",
    ("19-", "竖切实现总览", "第一条最小竖切实现总览",
    ),
)
