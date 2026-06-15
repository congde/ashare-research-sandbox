"""Generate the 35-chapter Codex + LLM quantitative trading course drafts."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2"


PARTS = {
    1: "第一篇｜Codex、LLM 与量化交易基础",
    2: "第二篇｜市场数据与研究工作流",
    3: "第三篇｜使用 LLM 发现并验证交易信号",
    4: "第四篇｜策略实现、回测与风险控制",
    5: "第五篇｜构建交易研究 Web 应用",
    6: "第六篇｜Skill、Automation 与 Eval",
    7: "第七篇｜模拟交易系统综合实战",
}


def c(
    num: int,
    part: int,
    slug: str,
    title: str,
    question: str,
    artifact: str,
    modules: str,
    method: str,
    experiment: str,
    failure: str,
    command: str,
    next_step: str,
) -> dict[str, object]:
    return locals()


CHAPTERS = [
    c(1, 1, "Codex-LLM与量化交易分别解决什么问题", "Codex、LLM 与量化交易分别解决什么问题",
      "怎样避免把代码生成、语言分析和统计验证混成一种能力", "三者责任边界卡",
      "`src/dashboard/llm_signal.py`、`src/backtest/`、`src/risk/`",
      "把工程执行、语言推理、量化验证拆成三条独立证据链",
      "比较规则信号、LLM 信号和回测结论分别能证明什么",
      "把 LLM 的肯定语气当成统计优势", "py scripts/course.py verify", "把交易想法改写成可证伪假设"),
    c(2, 1, "从交易想法到可验证的研究假设", "从交易想法到可验证的研究假设",
      "怎样把“这个指标应该有效”改写成可以被数据否定的问题", "研究假设卡",
      "`research-brief.md`、`data/prices.csv`",
      "明确对象、条件、观察窗口、对照组、指标和否定条件",
      "把双均线上穿后的模糊预期改写成带对照组的研究假设",
      "只写成功条件，不允许研究结果为不成立", "python report_cli.py --format summary", "搭建可复现研究工作区"),
    c(3, 1, "搭建可复现的量化研究工作区", "搭建可复现的量化研究工作区",
      "怎样让另一位研究者在不同电脑上得到同样输入和运行入口", "工作区就绪记录",
      "`AGENTS.md`、`scripts/course.py`、`.env.example`、`tests/`",
      "固定目录、依赖、配置、样本和验证命令，并把密钥排除在仓库之外",
      "从全新工作区运行 setup、verify 和本地应用，记录失败与恢复",
      "只在作者电脑上运行成功就宣布环境可复现", "py scripts/course.py setup", "学习价格、收益、信号与仓位"),
    c(4, 1, "读懂价格收益信号与仓位", "读懂价格、收益、信号与仓位",
      "怎样建立后续策略与回测共享的最小量化语言", "基础量化计算记录",
      "`data/prices.csv`、`src/backtest/metrics.py`、`src/backtest/runner.py`",
      "区分价格水平、期间收益、交易信号、持仓数量和资金曲线",
      "手工复算一个收益率、一次仓位变化和一段最大回撤",
      "用价格上涨百分比直接代替策略收益", "python report_cli.py --format json --short 3 --long 7", "建立交易研究安全边界"),
    c(5, 1, "建立第一条安全边界研究不等于投资建议", "建立第一条安全边界：研究不等于投资建议",
      "怎样阻止研究系统悄悄升级为交易决策系统", "交易研究边界清单",
      "`prd.md`、`src/risk/manager.py`、`src/web/src/pages/trading/LiveTradingPage.tsx`",
      "用允许、审批、禁止三层边界约束数据、信号和执行动作",
      "审查一份含买卖建议的输出，并将其降级为研究结论",
      "只添加免责声明，却保留真实账户和订单执行能力", "py scripts/course.py verify", "认识市场数据类型"),
    c(6, 2, "认识行情资金链上与情绪数据", "认识行情、资金、链上与情绪数据",
      "不同数据回答什么问题，又会引入哪些偏差", "市场数据地图",
      "`data/dashboard/`、`src/dashboard/catalog.py`、`src/dashboard/api.py`",
      "按来源、频率、口径、延迟和用途为数据分类",
      "对行情、资金、链上和情绪四类样本建立来源卡",
      "把来源不同、时间不同的数据直接拼成同一时点证据", "py scripts/course.py courseware-check", "构建数据采集与快照流程"),
    c(7, 2, "用Codex构建市场数据采集与快照流程", "用 Codex 构建市场数据采集与快照流程",
      "怎样在实时接口不稳定时保留可复现研究输入", "数据快照与回退记录",
      "`src/dashboard/snapshot.py`、`src/dashboard/refresh.py`、`data/dashboard/snapshots/`",
      "采用实时层、快照层、固定样本层的分级回退结构",
      "保存一次快照，断开实时来源后验证系统回退行为",
      "接口失败后静默使用旧数据，却不标记数据来源", "py scripts/course.py snapshot", "清洗并验证时间序列"),
    c(8, 2, "清洗标准化并验证时间序列数据", "清洗、标准化并验证时间序列数据",
      "怎样防止缺失、重复、乱序和错误类型污染后续结论", "数据质量报告",
      "`src/dashboard/normalize.py`、`src/dashboard/catalog.py`、`tests/test_dashboard_normalize.py`",
      "先定义数据契约，再检查完整性、时间顺序、唯一性和字段范围",
      "向样本注入重复时间戳和缺失字段，验证检查器拒绝输入",
      "为了让图表显示而自动填补所有缺失值", "py -m pytest tests/test_dashboard_normalize.py -q", "用技术指标描述市场"),
    c(9, 2, "用技术指标描述市场状态", "用技术指标描述市场状态",
      "怎样把价格序列转换成可解释但不过度承诺的市场描述", "指标计算与解释卡",
      "`src/dashboard/indicators.py`、`src/dashboard/kline_analysis.py`、`tests/test_kline_analysis.py`",
      "使用均线、RSI、布林带和 ATR 描述趋势、动量和波动",
      "在同一段 K 线上计算多个指标，并解释它们为何可能冲突",
      "看到超买就直接推断价格即将下跌", "py -m pytest tests/test_kline_analysis.py -q", "生成可追溯研究报告"),
    c(10, 2, "生成可追溯的市场研究报告", "生成可追溯的市场研究报告",
      "怎样让每个市场判断都能回到数据与计算过程", "市场研究报告",
      "`src/research/report.py`、`src/research/summary.py`、`research-report.md`",
      "分开记录事实、解释、信号、未知和数据来源",
      "生成一份市场摘要，并反向定位每个关键结论的来源",
      "报告结构完整，却没有保留未知和来源", "python report_cli.py --format summary", "理解 LLM 在交易研究中的边界"),
    c(11, 3, "LLM在交易研究中能做什么不能做什么", "LLM 在交易研究中能做什么、不能做什么",
      "怎样使用 LLM 的语言能力，又不把它当作价格预测器", "LLM 使用边界卡",
      "`src/dashboard/llm_signal.py`、`src/dashboard/signal_analysis.py`",
      "让 LLM 解释和组织已有证据，不允许它补造市场事实",
      "比较规则引擎与 LLM 对同一份市场上下文的输出",
      "让模型凭常识补充输入中不存在的实时价格", "py -m pytest tests/test_llm_signal.py -q", "组织 LLM 市场上下文"),
    c(12, 3, "把市场数据转换成LLM可理解的上下文", "把市场数据转换成 LLM 可理解的上下文",
      "怎样在信息不足和上下文过载之间取得平衡", "LLM 上下文契约",
      "`src/dashboard/llm_signal.py` 中的 `_build_prompt`、`src/dashboard/dataset_views.py`",
      "只提供支持任务的结构化字段，并声明缺失、时间与来源",
      "比较完整原始数据和精简结构化上下文的输出稳定性",
      "把全部历史数据塞入提示词并期待模型自行筛选", "py -m pytest tests/test_llm_signal.py -q", "输出结构化交易信号"),
    c(13, 3, "让LLM输出结构化交易信号", "让 LLM 输出结构化交易信号",
      "怎样让模型输出可检查、可降级、可进入后续系统的信号", "结构化信号契约",
      "`src/dashboard/llm_signal.py`、`src/dashboard/signal_tasks.py`、`tests/test_signal_tasks.py`",
      "使用枚举、数值范围、证据字段和人工门定义输出模式",
      "生成 BUY、HOLD 和失败三类信号，并验证字段契约",
      "把自由文本中的模糊措辞直接转换成交易动作", "py -m pytest tests/test_llm_signal.py tests/test_signal_tasks.py -q", "识别 LLM 信号污染"),
    c(14, 3, "识别幻觉提示泄漏与未来信息污染", "识别幻觉、提示泄漏与未来信息污染",
      "怎样发现让 LLM 信号看似准确的隐蔽污染", "信号失败样本集",
      "`src/strategy_engine/dsl/lookahead.py`、`src/dashboard/llm_signal.py`",
      "用反例分别检查编造数据、越权指令和未来信息",
      "向上下文注入未来收盘价和诱导指令，观察系统如何拒绝",
      "模型输出与结果一致就忽略它是否看到了未来", "py -m pytest tests/test_llm_signal.py -q", "评测 LLM 信号"),
    c(15, 3, "用样本和评分规程验证LLM信号", "用样本和评分规程验证 LLM 信号",
      "怎样判断一次漂亮输出是否能够稳定重复", "LLM 信号 Eval 报告",
      "`eval-rubric.md`、`data/llm_signal_tasks/`、`tests/test_signal_analysis.py`",
      "建立正常、边界、失败样本和不可被平均掩盖的关键失败项",
      "比较两版提示词在结构、证据、边界和稳定性上的得分",
      "只挑选最成功的一次输出展示模型能力", "py -m pytest tests/test_signal_analysis.py tests/test_llm_signal.py -q", "把信号写成策略规则"),
    c(16, 4, "把研究信号写成明确的策略规则", "把研究信号写成明确的策略规则",
      "怎样把语言信号转换成无歧义、可回测的进入与退出条件", "策略规则卡",
      "`src/backtest/rolling/strategies/technical_signal.py`、`src/strategy_engine/strategies/ma_crossover.py`",
      "明确触发、仓位、退出、冷却、失效和禁止条件",
      "把“趋势偏多时买入”改写为可以逐根 K 线执行的规则",
      "策略规则仍依赖人工阅读自然语言作决定", "py scripts/course.py verify", "用 Codex 实现策略"),
    c(17, 4, "用Codex实现第一条量化策略", "用 Codex 实现第一条量化策略",
      "怎样委托 Codex 写策略而不让范围和交易语义漂移", "可测试策略实现",
      "`src/strategy_engine/strategies/ma_crossover.py`、`src/backtest/rolling/strategies/`",
      "先写策略契约和测试，再实现最小规则并审查差异",
      "实现双均线策略，并用固定样本检查首次买卖信号",
      "让 Codex 顺便重构回测引擎和数据层", "py -m pytest tests/test_project.py -q", "构建事件驱动回测"),
    c(18, 4, "构建事件驱动回测引擎", "构建事件驱动回测引擎",
      "怎样按时间顺序模拟信号、订单、成交、持仓和资金变化", "事件驱动回测结果",
      "`src/strategy_engine/backtest/engine.py`、`portfolio.py`、`protocol.py`",
      "让每根 K 线只使用当时可见信息，并记录完整执行轨迹",
      "运行一次策略，逐步解释订单意图、成交和净值变化",
      "只保留最终收益，无法解释中间发生了什么", "py -m pytest tests/test_project.py -q", "评估回测表现"),
    c(19, 4, "正确评估收益回撤与风险调整表现", "正确评估收益、回撤与风险调整表现",
      "怎样避免用单一累计收益掩盖策略风险", "回测指标解释报告",
      "`src/backtest/metrics.py`、`src/backtest/rolling/metrics.py`、`src/backtest/runner.py`",
      "联合阅读收益、最大回撤、Sharpe、Calmar、胜率和交易次数",
      "比较高收益高回撤与低收益低回撤两条资金曲线",
      "收益更高就直接判定策略更好", "python report_cli.py --format json --short 3 --long 7", "检查回测污染"),
    c(20, 4, "防止过拟合前视偏差与数据窥探", "防止过拟合、前视偏差与数据窥探",
      "怎样识别回测中最容易制造虚假优势的错误", "回测污染检查报告",
      "`src/strategy_engine/dsl/lookahead.py`、`src/strategy_engine/dsl/validator.py`",
      "分离训练与验证，禁止未来访问，并限制策略 DSL 能力",
      "提交包含负向 shift 和危险导入的策略代码，验证系统拒绝",
      "反复查看测试集并继续调参", "py scripts/course.py verify", "进行滚动回测与策略比较"),
    c(21, 4, "从单次回测走向滚动回测与多策略比较", "从单次回测走向滚动回测与多策略比较",
      "怎样检查策略是否只在一个窗口和一组参数上有效", "滚动回测比较报告",
      "`src/backtest/rolling/service.py`、`src/backtest/rolling/registry.py`、`strategies/`",
      "跨窗口、跨策略、跨参数比较稳定性和失败区间",
      "比较买入持有、均线、MACD、RSI 和技术信号策略",
      "只报告最优策略和最优参数", "py scripts/course.py verify", "建立风险控制"),
    c(22, 4, "建立仓位止损与组合风险控制", "建立仓位、止损与组合风险控制",
      "怎样让风险规则在策略信号之前拥有否决权", "风险控制与拒绝记录",
      "`src/risk/manager.py`、`src/risk/config.py`、`tests/test_risk_manager.py`",
      "使用最大仓位、最大回撤、滑点、异常行情和紧急停止规则",
      "构造超仓、宽价差和异常 K 线，验证风险管理器拒绝订单",
      "只在回测结束后查看回撤，不在运行时拦截风险", "py -m pytest tests/test_risk_manager.py -q", "设计 Web 应用"),
    c(23, 5, "设计交易研究应用的信息架构", "设计交易研究应用的信息架构",
      "怎样把复杂研究能力组织成用户可以理解的路径", "Web 信息架构图",
      "`src/web/src/App.tsx`、`src/web/src/layouts/MainLayout.tsx`",
      "按研究任务组织导航，而不是按后端模块堆页面",
      "绘制从市场总览到信号、回测和风险复核的用户路径",
      "每新增一个接口就新增一个孤立页面", "cd src/web; npm run build", "构建总览、雷达与数据源"),
    c(24, 5, "构建行情总览机会雷达与数据源面板", "构建行情总览、机会雷达与数据源面板",
      "怎样让用户先理解市场覆盖范围与数据状态", "市场入口页面",
      "`DashboardPage.tsx`、`RadarPage.tsx`、`DataSourcesPage.tsx`",
      "同时展示机会、风险、来源、更新时间和回退状态",
      "断开实时数据后，验证页面仍展示快照来源与状态",
      "页面继续显示旧数据却让用户以为是实时数据", "cd src/web; npm run build", "构建 K 线与 LLM 信号页面"),
    c(25, 5, "构建K线分析与LLM信号页面", "构建 K 线分析与 LLM 信号页面",
      "怎样在一个页面中同时展示市场证据、模型解释和限制", "K 线与信号页面",
      "`KlineAnalysisChart.tsx`、`ResearchPage.tsx`、`src/dashboard/llm_signal.py`",
      "让图表、指标、信号证据、模型状态和失败说明彼此对应",
      "切换规则引擎与 LLM 输出，检查页面是否明确标注来源",
      "把置信度做成醒目数字，却隐藏证据和失败原因", "cd src/web; npm run build", "构建策略、回测与风险中心"),
    c(26, 5, "构建策略回测与风险中心", "构建策略、回测与风险中心",
      "怎样让用户从策略规则进入回测结果并看到风险拒绝", "策略回测风险页面",
      "`StrategyPage.tsx`、`BacktestsPage.tsx`、`RiskPage.tsx`",
      "把策略输入、回测假设、指标、交易记录和风险发现连成一条路径",
      "运行一条策略并从结果页定位一次风险拒绝",
      "只展示收益卡片，不展示假设、交易记录和风险", "cd src/web; npm run build", "验证完整研究路径"),
    c(27, 5, "用浏览器验证完整研究路径", "用浏览器验证完整研究路径",
      "怎样证明页面不仅好看，而且用户能够完成研究任务", "浏览器路径验收记录",
      "`tests/test_app_server.py`、`src/web/`、`app.py`",
      "从约定起点验证操作、状态变化、可见结果和异常出口",
      "从数据源页进入信号、回测和风险页面，完成一次端到端复核",
      "用最终截图代替完整操作路径", "py -m pytest tests/test_app_server.py -q", "把稳定流程写成 Skill"),
    c(28, 6, "把稳定研究流程写成Codex-Skill", "把稳定研究流程写成 Codex Skill",
      "怎样把一次成功研究过程沉淀为可重复契约", "研究检查 Skill",
      "`skills/`、`AGENTS.md`、`scripts/course.py`",
      "定义触发、输入、步骤、输出、停止线和验证方式",
      "把市场报告检查流程写成 Skill，并测试成功与拒绝案例",
      "把一段长提示词直接命名为 Skill", "py scripts/course.py verify", "自动生成快照与研究草稿"),
    c(29, 6, "自动生成市场快照与研究草稿", "自动生成市场快照与研究草稿",
      "怎样自动重复低风险、可验证的研究步骤", "受控研究 Automation",
      "`dashboard_snapshot.py`、`scripts/build_dashboard_fixtures.py`、`src/dashboard/refresh.py`",
      "只自动读取、保存、检查和生成草稿，不自动发布结论",
      "运行一次快照任务，并验证失败时回退到完整样本",
      "自动化失败后继续使用不完整数据生成报告", "py scripts/course.py save-offline-data", "设置审批门与停止线"),
    c(30, 6, "为高风险动作设置审批门与停止线", "为高风险动作设置审批门与停止线",
      "怎样阻止自动化跨越研究、发布和交易执行边界", "审批门与停止线合同",
      "`src/risk/manager.py`、`playbook.md`、`.env.example`",
      "按动作影响设置允许、审批、暂停、禁止和升级路径",
      "评审模型切换、对外发布、风险阈值修改和真实账户请求",
      "人工批准过一次后永久取消审批门", "py scripts/course.py verify", "使用 Eval 比较版本"),
    c(31, 6, "用Eval比较提示词模型与策略版本", "用 Eval 比较提示词、模型与策略版本",
      "怎样判断一次改进是真提升还是样本偶然", "跨版本 Eval 报告",
      "`eval-rubric.md`、`data/llm_signal_tasks/`、`tests/`",
      "固定样本、评分规程和关键失败门，再比较候选版本",
      "比较两版提示词和两种策略在正常、边界、失败样本上的表现",
      "只比较平均分，忽略安全边界失败", "py scripts/course.py check", "监控失败与恢复"),
    c(32, 6, "监控失败降级恢复与审计记录", "监控失败、降级、恢复与审计记录",
      "怎样让无人值守流程失败后可见、可停、可恢复", "运行审计与恢复记录",
      "`src/dashboard/signal_tasks.py`、`src/dashboard/persist.py`、`src/dashboard/catalog.py`",
      "记录输入、版本、状态、失败原因、降级来源和人工处理",
      "模拟 LLM 调用失败与数据不完整，验证任务降级和审计记录",
      "捕获异常后返回空结果并标记成功", "py -m pytest tests/test_signal_tasks.py tests/test_dashboard_persist.py -q", "设计综合模拟交易系统"),
    c(33, 7, "设计端到端模拟交易系统", "设计端到端模拟交易系统",
      "怎样为完整系统定义边界、模块合同和验收路径", "综合系统设计合同",
      "`src/dashboard/`、`src/backtest/`、`src/risk/`、`src/web/`",
      "从研究任务反推数据、信号、策略、回测、风控和展示合同",
      "绘制系统数据流，并为每个阶段定义失败出口",
      "先连接所有模块，再考虑错误如何停止", "py scripts/course.py verify", "贯通端到端系统"),
    c(34, 7, "贯通信号策略回测风控与Web应用", "贯通信号、策略、回测、风控与 Web 应用",
      "怎样让各模块共享明确合同并形成一条可复现路径", "端到端模拟研究路径",
      "`app.py`、`src/dashboard/api.py`、`src/backtest/rolling/service.py`、`src/web/`",
      "按输入输出合同逐段接通，并在每段保留证据和停止条件",
      "从市场快照生成信号，运行策略回测，检查风险并在页面展示",
      "端到端演示成功一次就忽略中间模块的失败状态", "py scripts/course.py check", "完成系统验收与迭代"),
    c(35, 7, "完成系统验收复盘与下一轮迭代", "完成系统验收、复盘与下一轮迭代",
      "怎样判断综合系统当前能交付什么、仍不能承诺什么", "最终验收与迭代计划",
      "`verify.py`、`tests/`、`eval-rubric.md`、`playbook.md`",
      "联合检查功能、数据、信号、回测、风险、安全边界和接手能力",
      "运行全量检查，注入关键失败，并根据证据制定下一轮计划",
      "为了宣布完成而隐藏未通过项和已知限制", "py scripts/course.py check", "在真实研究中持续使用证据链"),
]


def table(num: int, ch: dict[str, object]) -> str:
    return f"""在进入实现前，先用表 {num}-1 固定本讲的检查合同。

| 检查维度 | 本讲要求 | 通过证据 | 必须拒绝 |
|---|---|---|---|
| 研究问题 | {ch['question']} | 问题、输入与判断标准已写入记录 | 用流畅答案替代问题定义 |
| 实现范围 | 仅修改或读取 {ch['modules']} | 差异和运行记录可复查 | 未说明理由地扩大范围 |
| 实验任务 | {ch['experiment']} | 命令、输出和人工解释同时保留 | 只展示最有利结果 |
| 风险边界 | 主动检查“{ch['failure']}” | 失败被识别、停止并留下原因 | 失败后静默继续 |

**表 {num}-1　本讲任务、证据与拒绝条件**
"""


def render(ch: dict[str, object], previous: str, next_title: str | None) -> str:
    n = int(ch["num"])
    next_line = (
        f"下一讲将进入“{next_title}”，继续使用本讲留下的 **{ch['artifact']}**。"
        if next_title
        else "全书到这里完成闭环，后续迭代仍应沿用相同的证据与风险纪律。"
    )
    return f"""# 第 {n} 讲｜{ch['title']}

{previous}本讲要解决的问题是：**{ch['question']}**。我们不会把答案停留在概念层，而会
围绕配套仓库中的 {ch['modules']} 完成一次可以运行、检查和拒绝错误输入的实践。

本讲结束时，你应留下 **{ch['artifact']}**。它不是聊天摘要，而是下一位研究者能够独立
读取、复现和质疑的阶段成果。

## {n}.1 从一个容易被误判的结果开始

在“{ch['title']}”这个环节，最常见的误判是：系统已经给出输出，于是任务似乎完成了。
但量化交易中的输出可能来自错误数据、模糊规则、未来信息、偶然参数或未经声明的人工
取舍。结果存在，只能证明某段流程运行过，不能证明研究结论成立。

本讲特别警惕一种诱人的错误路径：**{ch['failure']}**。它往往能够让演示更顺畅、指标
更漂亮或实现更省事，却会破坏后续证据链。学习重点不是永远不犯错，而是让错误能够在
进入下一阶段前被发现、停止并解释。

## {n}.2 核心方法：{ch['method']}

本讲采用的方法是：**{ch['method']}**。执行时需要把事实、计算、解释和决定分开记录。
事实说明输入中真实存在什么；计算说明规则怎样从输入得到结果；解释说明结果可能意味着
什么；决定则明确是否允许流程继续。LLM 可以参与解释，Codex 可以参与实现，但决定不能
因为输出看起来专业就自动升级。

方法落地时始终追问四个问题：

1. 当前输入来自哪里，时间与口径是否明确；
2. 规则是否能够由另一位研究者重复执行；
3. 输出实际证明了什么，又不能证明什么；
4. 哪种失败必须让流程停止，而不是降级成警告。

{table(n, ch)}

## {n}.3 在配套仓库中找到真实实现

本讲对应的主要实现位于 {ch['modules']}。阅读代码时，不要从文件数量判断完成度，而要
沿着输入、转换、输出和验证路径寻找责任边界。一个模块是否值得信任，取决于它是否明确
声明输入假设、是否保留失败状态、是否有测试覆盖关键错误，而不是取决于代码看起来多么
复杂。

建议先运行本讲窄口命令：

```powershell
{ch['command']}
```

命令通过只证明其覆盖的检查通过。若命令失败，应保留退出状态和错误信息，定位是环境、
数据、规则还是实现问题。不要为了继续阅读而把失败结果改写成“预计可通过”。

## {n}.4 完整实践：{ch['experiment']}

本讲完整实践是：**{ch['experiment']}**。开始前先保存输入版本和预期判断，再让 Codex
协助读取相关文件、执行命令或完成最小修改。这样做能避免看见结果后再倒推一个看似合理
的目标。

可以使用下面的委托结构：

```text
目标：完成“{ch['experiment']}”。
范围：只读取或修改 {ch['modules']}。
必须保留：输入来源、运行命令、输出、失败原因与人工判断。
必须拒绝：{ch['failure']}。
完成条件：形成“{ch['artifact']}”，并说明结果能证明什么、不能证明什么。
```

Codex 返回结果后，人工复核至少包括三步。第一步核对它是否遵守范围；第二步检查输出
是否能够回到输入与规则；第三步主动注入一个错误或边界输入，确认系统会拒绝、停止或
明确降级。只有成功案例而没有失败案例，无法证明流程可靠。

## {n}.5 怎样解释结果而不过度承诺

量化交易研究最容易发生的语义升级，是把“在当前样本中观察到”写成“未来将会发生”。
本讲的 **{ch['artifact']}** 必须同时记录支持证据与限制。若结果来自固定样本，就要写明
样本窗口；若结果来自 LLM，就要写明模型、上下文与失败状态；若结果来自回测，就要写明
手续费、仓位、退出规则和不可外推性。

当结果不符合预期时，不要立即修改标准。先判断失败属于哪一类：输入不完整、研究假设
不成立、实现偏离规则、验证覆盖不足，还是风险边界主动拒绝。最后一种失败通常意味着
系统正确工作，而不是需要绕过的障碍。

## {n}.6 翻车与恢复

假设实践过程中出现“{ch['failure']}”。恢复动作不是删除失败证据，而是回到最早能够
阻止错误的检查点：重新确认输入、规则和允许范围；补充能够稳定复现问题的最小样本；
修正实现后先运行窄口检查，再运行更完整的回归验证。

恢复记录至少包含：

- 失败怎样被发现；
- 哪项假设或实现造成失败；
- 修改了什么，没有修改什么；
- 哪条命令实际运行并通过；
- 仍然保留哪些未知与风险。

这份记录会成为后续章节判断系统是否值得扩展、自动化或交付的重要证据。

## {n}.7 本章总结

本讲围绕“{ch['question']}”建立了可执行方法，并将结论落实为 **{ch['artifact']}**。
真正的完成标准不是生成一个结果，而是让结果能够回到输入和规则，能够承认限制，也能
在“{ch['failure']}”出现时停止。

{next_line}

## {n}.8 课后题

1. **概念判断题：** 为什么“命令通过”不能自动证明本讲研究结论成立？请结合 Codex、LLM
   和人工判断的分工说明。

2. **证据解释题：** 如果出现“{ch['failure']}”，流程应该继续、降级还是停止？请说明
   本讲输出能够支持哪些判断，又明确不能支持哪些判断。

3. **实践复现题：** 独立完成“{ch['experiment']}”，形成一份 **{ch['artifact']}**，
   并主动注入一个边界或失败输入，记录系统的拒绝、停止或恢复过程。
"""


def main() -> None:
    for path in OUT.glob("[0-3][0-9]-*.md"):
        if path.name.startswith("00-"):
            continue
        path.unlink()

    previous = "前言已经建立了全书的交易安全边界。"
    for index, ch in enumerate(CHAPTERS):
        next_title = str(CHAPTERS[index + 1]["title"]) if index + 1 < len(CHAPTERS) else None
        text = render(ch, previous, next_title)
        filename = f"{int(ch['num']):02d}-{ch['slug']}.md"
        (OUT / filename).write_text(text, encoding="utf-8")
        previous = f"上一讲已经完成“{ch['artifact']}”。"
        print(f"wrote docs/v2/{filename}")

    assert len(CHAPTERS) == 35
    assert len(list(OUT.glob("[0-3][0-9]-*.md"))) == 36

    # The base renderer establishes the shared course spine. Complete every
    # chapter with its repository-specific walkthrough and worked case before
    # treating the generated files as publishable drafts.
    from complete_quant_chapters import main as complete_chapters
    from add_publishable_quant_depth import main as add_publishable_depth
    from add_chapter_visuals import main as add_visuals
    from add_quant_rigor_sections import main as add_quant_rigor
    from add_external_research_sources import main as add_external_sources

    complete_chapters()
    add_publishable_depth()
    add_visuals()
    add_quant_rigor()
    add_external_sources()


if __name__ == "__main__":
    main()
