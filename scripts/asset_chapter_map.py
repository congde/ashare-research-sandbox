"""Canonical map: every PNG in docs/v2/assets → publishable chapter usage."""

from __future__ import annotations

# filename -> (chapter markdown basename prefix like "02-", alt text, figure caption suffix)
ASSET_USAGE: dict[str, tuple[str, str, str]] = {
    "chapter-20-lookahead-effect-curve.png": (
        "20-",
        "前视污染抬高权益曲线",
        "同一组收益下，偷看当日收益方向的污染规则会把回测权益曲线伪装得更好",
    ),
    "chapter-20-pbo-winner-decay.png": (
        "20-",
        "样本内冠军样本外掉队",
        "候选参数的样本内 Sharpe 与样本外 Sharpe 对比，展示样本内冠军可能只是选择过程制造出来的",
    ),
    "chapter-20-overfit-pollution-gate.png": (
        "20-",
        "过拟合与前视偏差拦截路径",
        "过拟合、前视偏差与数据窥探进入绩效解释前的拦截路径",
    ),
    "chapter-22-risk-order-gate.png": (
        "22-",
        "仓位与风控下单门禁",
        "订单意图、组合状态与风险规则共同决定是否允许成交",
    ),
    "chapter-23-research-ia-path.png": (
        "23-",
        "交易研究应用路径",
        "从行情总览到风险中心的交易研究应用信息架构路径",
    ),
    "chapter-24-market-candidate-path.png": (
        "24-",
        "行情候选的数据路径",
        "行情候选从数据源、总览、机会雷达到继续研究或降级停止的路径",
    ),
    "chapter-25-kline-llm-binding.png": (
        "25-",
        "K 线与 LLM 信号绑定",
        "K 线指标、规则基线与 LLM 解释之间的证据绑定关系",
    ),
    "chapter-26-backtest-risk-center.png": (
        "26-",
        "回测与风险中心联动",
        "回测结果、审计指标与风险拒绝记录之间的联动关系",
    ),
    "chapter-27-browser-research-path.png": (
        "27-",
        "浏览器验证研究路径",
        "从研究入口到风险复核的浏览器端到端验证路径",
    ),
    "chapter-28-skill-evidence-contract.png": (
        "28-",
        "Skill 证据合同",
        "Codex Skill 复用证据检查流程但保留人工发布责任",
    ),
    "chapter-29-snapshot-draft-path.png": (
        "29-",
        "快照到研究草稿",
        "自动化先冻结市场快照再生成研究草稿的证据路径",
    ),
    "chapter-30-approval-stop-gate.png": (
        "30-",
        "审批门与停止线",
        "高风险动作先分类审批再根据停止线决定是否执行",
    ),
    "chapter-31-eval-version-decision.png": (
        "31-",
        "Eval 版本决策",
        "固定评测样本后比较版本平均分与关键失败",
    ),
    "chapter-32-failure-audit-loop.png": (
        "32-",
        "失败降级与审计闭环",
        "失败、降级、恢复和审计记录之间的闭环",
    ),
    "chapter-33-sim-trading-boundary.png": (
        "33-",
        "端到端模拟交易边界",
        "端到端模拟交易系统只验证流程完整性不验证真实交易收益",
    ),
    "chapter-34-research-path-contracts.png": (
        "34-",
        "贯通研究路径合同",
        "信号、策略、回测、审计、风控与页面验收之间的合同路径",
    ),
    "chapter-35-acceptance-retro-loop.png": (
        "35-",
        "验收复盘与下一轮迭代",
        "最终验收、复盘和下一轮可执行任务之间的闭环",
    ),
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
    "chapter-04-return-formula-demo.png": (
        "04-",
        "价格水平与简单收益率示意图",
        "价格差值与简单收益率的区别",
    ),
    "chapter-04-drawdown-formula-demo.png": (
        "04-",
        "权益曲线最大回撤示意图",
        "权益峰值、谷值与最大回撤",
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
        "05-",
        "研究结果发布流水线",
        "研究结论进入页面或报告前的来源、计算、风险和表达门",
    ),
    "chapter-05-execution-gate-case.png": (
        "05-",
        "个人量化研究执行门案例",
        "BTC 规则信号、回测证据、动作请求与执行门的降级路径",
    ),
    "chapter-05-python-equity-curve.png": (
        "05-",
        "Python 价格与回测权益曲线",
        "BTC 收盘价、ma_crossover 回测权益、入场退出标记与执行门注释",
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
        "06-",
        "数据证据门",
        "行情、资金、链上与情绪数据进入指标或摘要前的来源、时间、口径和用途检查",
    ),
    "chapter-06-data-map-path.png": (
        "06-",
        "市场数据地图实战路径",
        "从原始数据、完整性检查、manifest、API 到页面或 LLM 摘要的证据追踪路径",
    ),
    "chapter-06-source-cards.png": (
        "06-",
        "四类来源卡示例",
        "行情、资金、链上和情绪来源卡的可回答问题与不能回答问题",
    ),
    "chapter-06-time-mismatch-case.png": (
        "06-",
        "时间错配反例",
        "不同观察窗口的数据被拦下，不能合并成同一时点市场事实",
    ),
    "chapter-06-python-source-timeline.png": (
        "06-",
        "Python 数据来源时间线",
        "BTC 收盘价、成交量、链上情绪观察日与 manifest 保存时间的同图复核",
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
    "chapter-07-snapshot-fallback.png": (
        "07-",
        "市场数据快照与回退路径",
        "实时接口、快照、latest 指针与 fixture 兜底",
    ),
    "chapter-07-python-snapshot-history.png": (
        "07-",
        "Python 快照历史累积曲线",
        "核心数据集 history 文件数量、latest 指针与保存时间的同图复核",
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
    "chapter-08-code-path.png": (
        "08-",
        "时间序列标准化代码路径关系图",
        "原始数据、标准化函数、完整性检查、来源卡片和测试文件之间的处理与验证路径",
    ),
    "chapter-08-kline-quality-curve.png": (
        "08-",
        "K 线字段标准化质量曲线",
        "固定 K 线样本按时间排序后的收盘价、3 日均线和 7 日均线",
    ),
    "chapter-08-gap-gate-example.png": (
        "08-",
        "K 线缺口与未收盘样本门禁示例",
        "缺失收盘价、展示占位线和未收盘样本在展示、指标、回测中的边界",
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
    "chapter-09-indicator-diagnostics.png": (
        "09-",
        "RSI、布林带和 ATR 诊断曲线",
        "RSI14、布林带位置、带宽与 ATR% 的维度拆分",
    ),
    "chapter-09-sma-window-comparison.png": (
        "09-",
        "SMA 窗口敏感性比较",
        "SMA5、SMA10 与 SMA20 的参数敏感性对照",
    ),
    "chapter-10-solution-space.png": (
        "10-",
        "方案空间",
        "方案空间",
    ),
    "chapter-10-tradeoff-triangle.png": (
        "10-",
        "权衡三角",
        "权衡三角",
    ),
    "chapter-10-report-metrics.png": (
        "10-",
        "固定样本报告关键指标",
        "固定样本报告关键指标",
    ),
    "chapter-10-equity-drawdown.png": (
        "10-",
        "权益曲线与回撤复核",
        "权益曲线与回撤复核",
    ),
    "chapter-11-mvp-loop.png": (
        "11-",
        "功能清单与最小完整闭环的区别",
        "功能清单与最小完整闭环的区别",
    ),
    "chapter-11-llm-gate-outcomes.png": (
        "11-",
        "模型输出门禁流程",
        "模型输出经过调用状态、schema、信号枚举、证据路径和执行建议检查后的处理去向",
    ),
    "chapter-11-data-pipeline.png": (
        "11-",
        "LLM 研究数据处理流水线",
        "规则基线、模型解释、结构化门禁和人工复核之间的数据处理路径",
    ),
    "chapter-11-scope-boundary.png": (
        "11-",
        "第一版范围内外与审批边界",
        "第一版范围内外与审批边界",
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
        "12-",
        "把规则编译成执行清单",
        "把 AGENTS 与 verify 规则编译成执行清单（对照）",
    ),
    "chapter-12-context-shape.png": (
        "12-",
        "BTC 规则基线进入模型上下文的字段体量",
        "市场、K 线、证据、交易计划和规则信号进入 LLM 上下文后的字段数量",
    ),
    "chapter-13-signal-enum-chart.png": (
        "13-",
        "结构化信号枚举与研究评分映射",
        "信号枚举与研究评分之间的映射关系",
    ),
    "chapter-14-pollution-cases.png": (
        "14-",
        "污染样本的拦截层级与处理动作",
        "安全空策略、危险导入和未来信息样本在 DSL、前视检查和人工复核中的处理路径",
    ),
    "chapter-15-factor-metrics.png": (
        "15-",
        "结构化信号进入量化评估后的示例指标",
        "固定示例序列上的覆盖率、方向命中率、平均置信度和关键失败数",
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
        "10-",
        "自动化权限包络线",
        "自动化权限包络线",
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

ASSET_USAGE.setdefault(
    "LLM信号分析.png",
    ("25-", "LLM 信号分析页面", "LLM 信号分析页面（补充素材）"),
)

ASSET_USAGE.setdefault(
    "币种K线.png",
    ("25-", "币种 K 线页面", "币种 K 线分析页面（补充素材）"),
)

ASSET_USAGE.setdefault(
    "chapter-00-safety-boundary.png",
    ("00-", "交易研究系统安全边界", "交易研究系统的安全边界"),
)

ASSET_USAGE.setdefault(
    "chapter-00-system-overview.png",
    ("00-", "全书构建的交易研究系统总览", "全书构建的交易研究系统总览"),
)

ASSET_USAGE.setdefault(
    "chapter-16-grid-position-function.png",
    ("16-", "网格仓位函数", "网格策略仓位函数（补充素材）"),
)

ASSET_USAGE.setdefault(
    "chapter-16-turning-state-machine.png",
    ("16-", "转向状态机", "策略转向状态机（补充素材）"),
)

ASSET_USAGE.setdefault(
    "chapter-21-pairs-zscore-threshold.png",
    ("21-", "配对交易 z-score 阈值", "配对交易 z-score 阈值（补充素材）"),
)

ASSET_USAGE.setdefault(
    "chapter-21-qbot-factor-pipeline.png",
    ("21-", "Qbot 因子流水线", "Qbot 因子流水线（补充素材）"),
)
for _asset_name, _chapter_prefix in {
    "chapter-11-llm-execution-curve.png": "11-",
    "chapter-12-visible-context-curve.png": "12-",
    "chapter-13-practical-contract-flow.png": "13-",
    "chapter-14-leakage-inflates-metrics.png": "14-",
    "chapter-14-lookahead-rules.png": "14-",
    "chapter-15-prompt-version-comparison.png": "15-",
    "chapter-15-sample-score-matrix.png": "15-",
    "chapter-16-action-distribution.png": "16-",
    "chapter-16-cost-sensitivity.png": "16-",
    "chapter-16-golden-cross-signal.png": "16-",
    "chapter-16-strategy-rule-card.png": "16-",
}.items():
    ASSET_USAGE.setdefault(
        _asset_name,
        (
            _chapter_prefix,
            "前视检查规则、风险与处理动作" if _asset_name == "chapter-14-lookahead-rules.png" else _asset_name.removesuffix(".png"),
            "前视检查样本对应的规则号、时间顺序风险和处理动作" if _asset_name == "chapter-14-lookahead-rules.png" else f"{_asset_name.removesuffix('.png')} supplemental teaching asset",
        ),
    )
ASSET_USAGE.setdefault(
    "首页概览.png",
    ("00-", "Web3 研究沙箱首页概览", "Web3 研究沙箱首页概览"),
)
