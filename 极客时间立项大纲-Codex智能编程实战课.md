# 极客时间专栏立项大纲｜Codex 创意交付实战课

## 一、选题信息

**暂定名称**：Codex 创意交付实战课
**副标题**：从一个模糊想法，到可用、可验证、可复用的第一版
**作者**：袁从德
**交付形态**：极客时间专栏
**预计体量**：开篇词 + 20 讲 + 结束语，可增加少量实战加餐
**配套仓库**：https://github.com/congde/ashare-research-sandbox.git
**关联图书**：《Codex：AI 驱动的智能编程时代》（邮电出版社）
**写作大纲**：[docs/20讲详细写作大纲.md](docs/20讲详细写作大纲.md)
**立项卖点**：[docs/极客时间课程卖点一页纸.md](docs/极客时间课程卖点一页纸.md)

---

## 二、为什么要做这门课

大多数 AI 工具教程仍然把 Codex 讲成「更聪明的 Copilot」：会补全、会改代码、会聊天。用户学会的是提示词技巧，而不是 **委托一个能独立推进、又能被验收的助手**。

一位编辑分享过一个很有代表性的例子：他认识的一名高中生，已经借助 Codex 自己做出了某个中转服务的部分功能。这个案例说明，写代码和做产品原型正在从专业岗位能力，变成更多普通人可以调用的执行能力。未来越来越多人会在并不自称程序员的情况下，做出脚本、工具、网站和自动化流程。

但能够快速做出东西，不等于能够可靠地使用和维护它。需求是否真的值得做、外部服务与数据是否安全、结果是否验证、失败时如何停止、别人能否接手，这些问题反而会随着创造门槛降低而变得更加普遍。本课程要补上的，正是从「我让 AI 做出了一个东西」到「这是一份可以进入现实工作的交付」之间的能力。

实际使用中，人们普遍卡在四类问题：

1. **只会问，不会委托**：把 Codex 当搜索引擎或聊天框，任务边界、完成标准和验收方式从未写清。
2. **只会生成，不会交付**：助手给出了看起来合理的文字或代码，但没有来源、没有证据、没有可接手格式，结果无法进入下一步。
3. **只把 Codex 当编程工具**：调研、整理、计划、数据处理、浏览器操作等日常任务从未进入 Codex 工作流；一旦不涉及代码，就回到手动模式。
4. **个人偶尔成功，无法复用**：缺少项目说明、Skill、Automation 和评测机制，成功经验不能稳定复制，更谈不上团队推广。

本专栏不按 Codex 功能菜单讲解，也不把调研、写作、计划和编程当成彼此无关的能力。课程围绕一条普通人可以理解的完整创意交付链组织训练：

> 想法 → 调研验证 → PRD 定义 → 计划拆解 → AI Coding → 真实使用验证 → Skill / Automation / Eval → Playbook

课程要回答的核心问题不是「Codex 能不能写代码」，而是：

> **我有一个想法，但不会做，怎样让 Codex 帮我把它做成第一个真正可用的版本？**

委托、验收、入口、工作区、调研、写作和计划，不再是并列专题，而是做出第一版过程中自然出现的方法。AI Coding 也不是课程突然切换到编程，而是前面产品决策开始被执行。

---

## 三、专栏与图书的关系

### 1. 图书：建立系统认知

图书围绕 AI 编程智能体的认知迁移、上下文工程、能力边界和团队治理展开，回答「为什么 Codex 不只是代码生成工具」。

### 2. 专栏：练成工作方式

专栏不沿用图书章节顺序，而是让读者在 20 讲里完整走过一次 **想法—第一版—真实验证—稳定复用**。图书讲判断，专栏练交付。

| 对比维度 | 图书 | 专栏 |
|---|---|---|
| 核心定位 | 方法论与边界判断 | 借助 Codex 把想法做成可用第一版 |
| 组织方式 | 按知识体系展开 | 按产品交付流程递进 |
| 主要载体 | 论述与案例框架 | 调研 Brief、PRD、计划、可用版本、Eval |
| 代码角色 | 重要场景之一 | 执行产品方案的手段，不要求读者先会编程 |

**一句话**：图书帮你理解 Codex 能做什么、不能做什么；专栏带你和 Codex 一起做出一个真正可用的东西。

---

## 四、目标读者

### 主受众

- 已使用 ChatGPT、豆包、Kimi、Copilot、Cursor 或 Codex，但主要停留在问答、生成和偶尔成功阶段的人；
- 希望把一个工作想法交给 AI 推进，并能判断结果是否真的可用的知识工作者、个体创作者与学生；
- 希望用 Codex 处理调研、写作、计划、数据整理、浏览器操作，甚至做出自己的小工具与自动化流程；
- 不要求先成为程序员，但愿意学习怎样定义任务、检查证据、控制风险并承担最终决定。

### 进阶受众

- 希望 Codex 进入代码库、Bug 修复、PR、Review、CI 与团队协作流程的开发者和 Tech Lead；
- 想把个人助手经验沉淀为 Skill、Automation、Eval 和团队 Playbook 的负责人。

### 前置基础

- 能使用电脑完成日常办公与简单文件操作；
- 不要求编程基础；涉及代码时，读者重点学习如何指导、检查和验收 Codex；
- 不要求有 Agent、MCP 或自动化经验。

### 三类读者的学习收获

| 读者 | 学习重点 | 结业标准 |
|---|---|---|---|
| **普通用户与学生** | 把一个模糊想法调研清楚、定义清楚并做出第一版 | 独立完成从想法到真实使用验证 |
| **创作者与个体经营者** | 低成本验证产品想法，控制数据、权限与投入风险 | 做出可继续迭代或及时停止的可用成果 |
| **开发者与负责人** | 用产品交付主线重新组织 AI Coding、Review、CI 与团队方法 | 把个人成功沉淀为可评测、可推广的工作流 |

### 学完后的能力

1. 把一个模糊想法整理成可调研、可判断的问题；
2. 用证据决定继续、修改还是停止，而不是让 Codex 替自己拍板；
3. 把调研结论写成明确第一版范围的 PRD；
4. 把 PRD 拆成按用户结果验收的实施计划；
5. 即使不会编程，也能指导 Codex 做出、运行、修改和交付第一版；
6. 通过真实用户任务判断产品是否解决问题；
7. 将稳定步骤沉淀为 Skill、Automation，并用 Eval 持续改进；
8. 写出别人能够复用的个人或团队 Playbook。

---

## 五、课程设计原则

### 1. 一条产品交付主线贯穿全课

读者从自己的一个模糊想法出发，依次完成调研、PRD、计划、AI Coding、真实使用验证、稳定复用与 Playbook。每讲的交付物必须成为下一讲的输入。

### 2. 按交付阶段组织，不按产品功能组织

App、CLI、Cloud、MCP、Skills、Automations、PR 和 CI 等能力，只在交付流程需要时出现。

### 3. 每讲一个可验收交付物

每讲结束时，读者应留下 **可被第三方检查** 的产物：Brief、报告、计划、数据表、Handoff 文档、Diff、PR 或 Eval 记录——而不是一段聊天记录。

### 4. 解释决策，不是命令流水账

正文说明：为什么这样委托、给了什么上下文、验收标准是什么、哪些判断不能交给 Agent。

### 5. 配套资产可运行、可检查

- 助手类 Lab：结构校验、来源检查、Rubric 评分；
- 工程类 Lab：`make lab-xx` 确定性验收；
- 两类 Lab 共用同一套 Brief 模板与 Handoff 格式。

### 6. 一个真实主案例贯穿，多个小案例解释方法

主案例使用 **A 股投资研究与模拟策略验证台**：从“我想让 AI 帮我研究一只 A 股”这句模糊想法开始，经过调研、PRD、计划和 AI Coding，做出一个读取固定历史行情、财报与公告样本，生成可追溯研究摘要，运行简单策略回测并展示风险的第一版，再通过真实使用、Skill、Automation 与 Eval 逐步稳定。

案例参考作者真实交易研究项目中的行情、回测、风险和评测经验，但课程使用独立、轻量、脱敏的 A 股起始项目与固定样本数据，不依赖私有仓库、内部服务或证券账户。腾讯文档迁移、每周简报和代码库任务继续作为局部方法示例，不抢走主叙事。

### 7. 默认只读、模拟和人工审批

课程案例默认只读取固定历史行情、财报和公告样本，只运行离线分析与策略回测，不接证券账户、不自动下单、不提供具体买卖建议、不承诺收益。任何涉及实时行情、真实账户、交易执行或公开发布的动作，都属于课程范围外的高风险扩展，必须经过合规、风控和人工审批。

### 8. 对齐 Codex 官方工作循环

课程实操对齐 OpenAI 推荐的 **Inspect → Plan → Edit → Verify → Report** 循环（见 [Working with Codex](https://openai.com/academy/working-with-codex/)）：Brief 对应 Plan，验收对应 Verify，Handoff / PR 描述对应 Report。

---

## 六、课程结构

课程围绕一个问题展开：

> **我有一个想法，但不会做，怎样让 Codex 帮我做出第一个真正可用的版本？**

完整主线如下：

```text
想法
→ 调研验证
→ PRD 定义
→ 计划拆解
→ AI Coding
→ 真实使用验证
→ Skill / Automation / Eval
→ Playbook
```

**贯穿主案例**：[A 股投资研究与模拟策略验证台](docs/A股项目贯穿章节稿.md)  
**可运行项目**：[labs/10-a-share-research](labs/10-a-share-research/README.md)  
**正文目录**：[docs/v2/README.md](docs/v2/README.md)

主案例从「我想让 AI 帮我研究一只 A 股」出发，使用虚构教学标的「示例科技（600001）」与固定历史样本，交付研究摘要、双均线回测、浏览器界面与自动验收。不接证券账户、不荐股、不自动下单。

腾讯文档迁移、每周简报、代码库勘察等继续作为**方法侧例**，解释委托、验收、Skill 与工程护栏，但不替代主叙事。

---

### 开篇词｜我有一个想法，但不会做

**正文**：[docs/v2/00-我有一个想法但不会做.md](docs/v2/00-我有一个想法但不会做.md)

用「高中生借助 Codex 做出中转服务部分功能」开场：创造门槛在下降，但「做出来」不等于「值得用、能验证、可接手」。引出 A 股课程主案例与 20 讲交付链。

---

### 第一篇｜调研验证：这个想法值得做吗

本篇不急着实现。读者先学会把愿望改写成可调查的问题，并用证据决定继续、修改还是停止。

| 讲次 | 正文 | 主案例交付物 | 方法侧例 / 验收 |
|---|---|---|---|
| 第 1 讲 | [01-把一个模糊想法交给Codex.md](docs/v2/01-把一个模糊想法交给Codex.md) | [product-brief.md](labs/10-a-share-research/product-brief.md) | [labs/00-assistant-brief](labs/00-assistant-brief/README.md) · `py scripts/course.py lab-00` |
| 第 2 讲 | [02-开始之前先定义什么叫调研完成.md](docs/v2/02-开始之前先定义什么叫调研完成.md) | 调研验收规则（来源卡、F/I/R/U 分层） | [labs/04-research](labs/04-research/README.md) · `lab-04` |
| 第 3 讲 | [03-给Codex准备正确的资料和工作区.md](docs/v2/03-给Codex准备正确的资料和工作区.md) | 工作区边界（固定样本、无账户密钥） | [labs/03-entry-workspace](labs/03-entry-workspace/README.md) · `lab-03` · [AGENTS.md](AGENTS.md) |
| 第 4 讲 | [04-用调研证据决定继续、修改还是停止.md](docs/v2/04-用调研证据决定继续、修改还是停止.md) | [research-report.md](labs/10-a-share-research/research-report.md)（Go 决策） | [labs/04-research](labs/04-research/README.md) · `lab-04` |

**第 1 讲**｜把一个模糊想法交给 Codex  
区分产品想法、投资期待与真实用户问题；把「研究 A 股」改写为可委托 Brief。

**第 2 讲**｜开始之前，先定义什么叫调研完成  
建立验收思维：事实须映射来源、推断须可追踪、未知不得写「无」。

**第 3 讲**｜给 Codex 准备正确的资料和工作区  
选择 App / CLI / Cloud 入口，准备最小上下文；明确禁止进入工作区的资料（账户、密钥、未审查实时数据）。

**第 4 讲**｜用调研证据决定：继续、修改还是停止  
整理竞品与用户问题，输出 Go / Revise / No-Go；第一版方向定为「研究 + 模拟验证」，不做自动交易。

**本篇交付结果**：Brief、验收标准、上下文包、[research-report.md](labs/10-a-share-research/research-report.md) 与产品方向决策。

---

### 第二篇｜PRD 定义：第一版究竟要做什么

调研证明问题值得继续后，本篇把证据固化为第一版产品合同。

| 讲次 | 正文 | 主案例交付物 | 方法侧例 / 验收 |
|---|---|---|---|
| 第 5 讲 | [05-从调研结论中找到真正的用户问题.md](docs/v2/05-从调研结论中找到真正的用户问题.md) | 用户问题定义（可追溯研究，非荐股） | [labs/04-research](labs/04-research/README.md) 汇报体裁 |
| 第 6 讲 | [06-第一版做什么、又明确不做什么.md](docs/v2/06-第一版做什么、又明确不做什么.md) | [prd.md](labs/10-a-share-research/prd.md) | [labs/06-planning-handoff](labs/06-planning-handoff/README.md) · `lab-06` |
| 第 7 讲 | [07-让Codex审查PRD、而不是替你做产品决定.md](docs/v2/07-让Codex审查PRD、而不是替你做产品决定.md) | PRD 审查记录与决策汇报 | — |

**第 5 讲**｜从调研结论中找到真正的用户问题  
核心用户是「希望用一致证据整理公司信息并验证简单策略的人」，不是「希望 AI 荐股或保证盈利的人」。

**第 6 讲**｜第一版做什么，又明确不做什么  
[prd.md](labs/10-a-share-research/prd.md) 限定：虚构标的、固定样本、研究摘要、双均线回测、风险说明；非目标含证券账户、实时行情、荐股与收益承诺。

**第 7 讲**｜让 Codex 审查 PRD，而不是替你做产品决定  
Codex 查找矛盾、遗漏与不可验收表述；范围、承诺与取舍由人负责。

**本篇交付结果**：问题定义、[prd.md](labs/10-a-share-research/prd.md)、PRD 审查记录与决策汇报。

---

### 第三篇｜计划拆解：把 PRD 变成可执行任务

PRD 回答做什么，本篇回答怎样分阶段做，以及每一步如何证明完成。

| 讲次 | 正文 | 主案例交付物 | 方法侧例 / 验收 |
|---|---|---|---|
| 第 8 讲 | [08-从完整产品中切出第一条用户闭环.md](docs/v2/08-从完整产品中切出第一条用户闭环.md) | 用户闭环定义 + 浏览器证据链 | 本地页面 / 公开页面验证 |
| 第 9 讲 | [09-把用户闭环拆成可以逐步验收的计划.md](docs/v2/09-把用户闭环拆成可以逐步验收的计划.md) | [plan.md](labs/10-a-share-research/plan.md) | [skills/weekly-brief](skills/weekly-brief/SKILL.md) · `lab-09` |

**第 8 讲**｜从完整产品中切出第一条用户闭环  
切出路径：打开页面 → 阅读带来源摘要 → 运行默认回测 → 查看收益/回撤/交易/限制 → 解释为何不能据此交易。

**第 9 讲**｜把用户闭环拆成可以逐步验收的计划  
[plan.md](labs/10-a-share-research/plan.md) 拆成三 milestone：固定研究包 → 回测引擎 → 可用网页；每步带证据门与停止线。

**本篇交付结果**：最小用户闭环、[plan.md](labs/10-a-share-research/plan.md)、风险清单与 Handoff 草稿。

---

### 第四篇｜AI Coding：让 Codex 做出第一个版本

AI Coding 在此自然出现：读者学习指导 Codex、检查证据、处理失败与接手成果，而非先学逐行写代码。

| 讲次 | 正文 | 主案例交付物 | 方法侧例 / 验收 |
|---|---|---|---|
| 第 10 讲 | [10-不会编程、怎样选择第一版实现方式.md](docs/v2/10-不会编程、怎样选择第一版实现方式.md) | 技术选型（标准库 + 固定样本） | 对照 [web3-trading](https://github.com/congde/web3-trading) 分层形状 |
| 第 11 讲 | [11-让Codex完成第一条可运行的用户路径.md](docs/v2/11-让Codex完成第一条可运行的用户路径.md) | `a_share/` · `app.py` · `report_cli.py` · `static/` | 数据处理留痕纪律 |
| 第 12 讲 | [12-Codex说完成了、怎样证明真的完成了.md](docs/v2/12-Codex说完成了、怎样证明真的完成了.md) | `verify.py` · `tests/` | [AGENTS.md](AGENTS.md) · `lab-10` · `lab-16` |
| 第 13 讲 | [13-修复问题、交付可以使用的第一版.md](docs/v2/13-修复问题、交付可以使用的第一版.md) | [README.md](labs/10-a-share-research/README.md) · Handoff | [skills/repo-readiness](skills/repo-readiness/SKILL.md) · `lab-16` |

**第 10 讲**｜不会编程，怎样选择第一版实现方式  
在「标准库 + 固定文件」「全栈量化参考」「表格/Notebook」间选型；保留 web3-trading 的「数据 → 引擎 → 报告 → 界面」分层，去掉 API Key 与数据库依赖。

**第 11 讲**｜让 Codex 完成第一条可运行的用户路径  
完成竖切：`data/` → `a_share/research.py` / `backtest.py` → `report.py` → 浏览器与 CLI 双入口。

**第 12 讲**｜Codex 说完成了，怎样证明真的完成了  
运行 `py scripts/course.py lab-10`：检查项目资产、来源卡、回测指标、异常参数与安全边界；盈利样本不能替代验收证据。

**第 13 讲**｜修复问题，交付可以使用的第一版  
交付可运行版本、使用说明、已知限制、恢复方案与 Handoff；另一位读者只读 README 即可启动并复现。

**本篇交付结果**：技术路线、可运行用户路径、验收证据与可用第一版。

**主案例代码地图**：

```text
labs/10-a-share-research/
├── product-brief.md · research-report.md · prd.md · plan.md
├── data/company.json · data/prices.csv
├── a_share/research.py · backtest.py · report.py
├── app.py · report_cli.py · static/
├── user-test.md · eval-rubric.md · playbook.md
├── verify.py · tests/
└── README.md
```

---

### 第五篇｜真实使用验证：它真的解决问题了吗

作者自己跑通一次，只能证明产品能演示。本篇让真实用户完成真实任务，并据此决定下一步。

| 讲次 | 正文 | 主案例交付物 | 方法侧例 / 验收 |
|---|---|---|---|
| 第 14 讲 | [14-让真实用户完成一次真实任务.md](docs/v2/14-让真实用户完成一次真实任务.md) | [user-test.md](labs/10-a-share-research/user-test.md) | [labs/01-first-ticket](labs/01-first-ticket/README.md) · `lab-01` |
| 第 15 讲 | [15-根据使用结果决定继续、修改还是停止.md](docs/v2/15-根据使用结果决定继续、修改还是停止.md) | 版本决策与下一步计划 | — |

**第 14 讲**｜让真实用户完成一次真实任务  
任务：比较默认双均线与买入持有，并解释至少两个不可外推的原因；观察用户是否形成可追溯判断，而非策略是否碰巧盈利。

**第 15 讲**｜根据使用结果决定继续、修改还是停止  
综合任务完成率、理解成本、错误风险与维护成本；历史收益率只是样本结果，不能替代产品价值判断。

**本篇交付结果**：真实使用记录、反馈分析、版本决策与下一步计划。

---

### 第六篇｜稳定重复：从一次成功到个人工作系统

产品或工作流被证明有价值后，才值得自动化与评测。

| 讲次 | 正文 | 主案例交付物 | 方法侧例 / 验收 |
|---|---|---|---|
| 第 16 讲 | [16-哪些步骤值得交给Codex重复执行.md](docs/v2/16-哪些步骤值得交给Codex重复执行.md) | 流程盘点（研究/回测可重复，下单不可） | — |
| 第 17 讲 | [17-用Skill和Automation固化成功流程.md](docs/v2/17-用Skill和Automation固化成功流程.md) | Skill / Automation 候选 | [skills/weekly-brief](skills/weekly-brief/SKILL.md) · `lab-09` |
| 第 18 讲 | [18-用Eval证明下次仍然能够做好.md](docs/v2/18-用Eval证明下次仍然能够做好.md) | [eval-rubric.md](labs/10-a-share-research/eval-rubric.md) | `lab-04` · `lab-16` 迷你评测链 |

**第 16 讲**｜哪些步骤值得交给 Codex 重复执行  
区分适合做 Skill、适合自动执行、必须人工审批与不应自动化的步骤（含证券登录、荐股、下单）。

**第 17 讲**｜用 Skill 和 Automation 固化成功流程  
把稳定步骤沉淀为 Skill；Automation 只推进到可审查草稿，高影响动作保留审批门。

**第 18 讲**｜用 Eval 证明下次仍然能够做好  
[eval-rubric.md](labs/10-a-share-research/eval-rubric.md) 五维评分：来源、复现、风险表达、安全边界、交接；全 2 分才允许扩大自动化。

**本篇交付结果**：流程盘点、Skill 候选、受控 Automation 设计与 Eval 规程。

---

### 第七篇｜Playbook：把个人成功变成可复制方法

| 讲次 | 正文 | 主案例交付物 | 方法侧例 / 验收 |
|---|---|---|---|
| 第 19 讲 | [19-毕业交付、从自己的想法重新走完全过程.md](docs/v2/19-毕业交付、从自己的想法重新走完全过程.md) | 读者自选想法的完整交付包 | A 股项目作参考，不作扩展题 |
| 第 20 讲 | [20-写出别人也能使用的Codex-Playbook.md](docs/v2/20-写出别人也能使用的Codex-Playbook.md) | [playbook.md](labs/10-a-share-research/playbook.md) | 接手测试 |

**第 19 讲**｜毕业交付：从自己的想法重新走完全过程  
读者选择真实想法，重新完成调研 → PRD → 计划 → 第一版 → 用户验证 → Eval；代码非必选项。

**第 20 讲**｜写出别人也能使用的 Codex Playbook  
[playbook.md](labs/10-a-share-research/playbook.md) 写清运行、验证、停止线与永不自动化动作；另一位读者无需原聊天记录即可接续。

**本篇交付结果**：毕业交付包、接手测试与个人或团队 Playbook。

---

### 章节交付链

每一阶段的产物必须成为下一阶段的输入：

```text
模糊想法
→ product-brief.md + research-report.md（调研决策）
→ prd.md（第一版合同）
→ plan.md（证据门计划）
→ labs/10-a-share-research 可运行第一版
→ user-test.md 使用记录 + 版本决策
→ Skill / Automation / eval-rubric.md
→ playbook.md
```

### 配套验收入口

Windows PowerShell：

```powershell
py scripts/course.py setup          # 首次
py scripts/course.py lab-10         # A 股主案例
py scripts/course.py check          # 全课仓库检查
```

macOS / Linux：`make lab-10`、`make check`。

现有正文与 Lab 的章节—文件映射，见 [docs/v2/README.md](docs/v2/README.md) 与 [docs/A股项目贯穿章节稿.md](docs/A股项目贯穿章节稿.md)；写作细则见 [docs/20讲详细写作大纲.md](docs/20讲详细写作大纲.md)。

---

## 七、单讲内容形态

| 模块 | 作用 |
|---|---|
| 上游输入 | 明确本讲从上一阶段继承了什么，不允许凭空开始 |
| 主案例锚点 | 指向 `labs/10-a-share-research/` 中当讲应对齐的交付物 |
| 真实冲突 | 展示当前交付阶段最容易犯的错误 |
| 委托示范 | 完整 Brief、上下文选择与人工判断点 |
| Codex 机制 | 只讲本讲任务真正用到的能力 |
| 验收演示 | 展示如何通过 / 如何拒绝助手结果 |
| 人工判断点 | 明确不能交给 Agent 的责任 |
| 翻车与恢复 | 常见失败（幻觉、越界、凑格式、测试凑绿）及恢复 |
| 过关任务 | 产出将被下一讲继续使用的可检查交付物 |

---

## 八、配套仓库设计

`ashare-research-sandbox` 是一条 **从想法到工作手册的交付训练场**。正文在 [docs/v2/](docs/v2/)，可执行 Lab 在 [labs/](labs/)，可复用 Skill 在 [skills/](skills/)。

| 类型 | 目录 | 验收命令 | 与主案例关系 |
|---|---|---|---|
| **贯穿主案例** | [labs/10-a-share-research/](labs/10-a-share-research/README.md) | `lab-10` | Brief → 调研 → PRD → 计划 → 代码 → 用户测试 → Eval → Playbook 的完整实物 |
| 调研与 Brief | [labs/00-assistant-brief/](labs/00-assistant-brief/README.md) | `lab-00` | 第 1 讲 Brief 结构侧例 |
| 入口与工作区 | [labs/03-entry-workspace/](labs/03-entry-workspace/README.md) | `lab-03` | 第 3 讲上下文包侧例 |
| 调研报告 | [labs/04-research/](labs/04-research/README.md) | `lab-04` | 第 2–5 讲 F/I/R/U 与来源卡侧例 |
| 计划与交接 | [labs/06-planning-handoff/](labs/06-planning-handoff/README.md) | `lab-06` | 第 6、9 讲证据门计划侧例 |
| 热修复 | [labs/01-first-ticket/](labs/01-first-ticket/README.md) | `lab-01` | 第 14 讲工程修复侧例 |
| 周报 Skill | [labs/09-weekly-brief-skill/](labs/09-weekly-brief-skill/sample-report.md) + [skills/weekly-brief/](skills/weekly-brief/SKILL.md) | `lab-09` | 第 9、17 讲 Skill 侧例 |
| 仓库勘察 | [labs/16-repo-readiness-skill/](labs/16-repo-readiness-skill/sample-report.md) + [skills/repo-readiness/](skills/repo-readiness/SKILL.md) | `lab-16` | 第 12–13 讲工程护栏侧例 |
| 课程ware | [scripts/course.py](scripts/course.py) · [scripts/verify_courseware.py](scripts/verify_courseware.py) | `check` · `courseware-check` | 正文链接、章节结构与 Lab 一致性 |

**主案例 ten 件套**（`lab-10` 强制检查）：

```text
product-brief.md · research-report.md · prd.md · plan.md
user-test.md · eval-rubric.md · playbook.md
data/company.json · data/prices.csv · static/index.html
+ a_share/*.py · app.py · verify.py · tests/
```

原则：

- 正文提到的文件、命令与验收必须与仓库一致（[AGENTS.md](AGENTS.md) 强制）；
- 非程序员可借助主案例完成 AI Coding 与使用验证，无需证券账户或外部 API；
- 正文同时展示「用户看到的结果」与「可复查的交付证据」；
- 方法侧例 Lab 自包含，不依赖其他 Lab 的可变文件。

---

## 九、差异化价值

与常见 AI 编程课 / 提示词课相比：

1. **定位差异**：面向「有想法但不会做」的普通人，而不是只面向已经拿到工单的程序员。
2. **结构差异**：调研、PRD、计划、AI Coding 和验证组成一条连续产品交付链，不是若干 AI 功能的拼盘。
3. **实现差异**：不教读者逐行模仿代码，而是教他指导 Codex、检查证据、处理失败和接手成果。
4. **产品差异**：第一版能运行不是结业标准，真实用户完成真实任务才算进入下一阶段。
5. **复用差异**：Skill、Automation 和 Eval 只用于已经验证有价值的流程，避免自动化无效工作。
6. **证据差异**：每一讲都有上游输入、可见产物、验收闸门和停止条件；主案例有确定性 `lab-10` 验收。

### 业界参考（立项调研摘要）

| 参考对象 | 可借鉴点 | 本课如何差异化 |
|---|---|---|
| [web3-trading](https://github.com/congde/web3-trading) | 研究 → 回测 → 报告 → API 分层 | 保留分层形状，用固定样本 + 标准库压缩为教学 MVP |
| [Claude Code 工程化实战](https://news.qq.com/rain/a/20260131A02R6I00) | 记忆系统、Sub-Agents、Skills、Hooks、CI 集成 | 将工程方法放进普通人也能理解的完整产品交付链 |
| [GitHubSentinel Agent 实战](https://time.geekbang.org/course/intro/101061913) | 单项目从立项到生产的里程碑递进 | 从产品想法和用户验证开始，而不是从已有工程目标开始 |
| [OpenAI Working with Codex](https://openai.com/academy/working-with-codex/) | Thread / Project、Steer、可执行委托 | 课程化 Inspect → Plan → Verify → Report |
| [DataCamp Codex 教程](https://www.datacamp.com/tutorial/openai-codex) | AGENTS.md、沙箱、PR 验收 | 把工具能力放进 AI Coding、验证和交接阶段按需讲解 |

---

## 十、预期成果

读者结业时应拥有：

- 一套跨场景复用的 **Brief 模板** 与 **验收清单**；
- 一份有证据支持的调研结论（参考 [research-report.md](labs/10-a-share-research/research-report.md)）；
- 一份第一版 PRD（[prd.md](labs/10-a-share-research/prd.md)）和证据门计划（[plan.md](labs/10-a-share-research/plan.md)）；
- 一个经过真实使用验证和风险检查的可用第一版（或等价的自选项目交付包）；
- 一份 [eval-rubric.md](labs/10-a-share-research/eval-rubric.md) 评分规程与 **Eval** 记录；
- 一份 [playbook.md](labs/10-a-share-research/playbook.md) 级别的 **个人 Playbook**（可选团队版）。

最终希望读者形成的习惯：

> **有一个想法时，不是立即让 AI 开始做，而是先验证问题、定义第一版、拆出可验收计划，再让 Codex 执行。**

---

## 附录：与上一版大纲的主要变化

| 维度 | 上一版（个人助手能力进阶） | 当前版（创意交付主线） |
|---|---|---|
| 核心问题 | 怎样把不同任务可靠交给 Codex | 我有想法但不会做，怎样做出可用第一版 |
| 课程组织 | 交出去、管得住、做出来、能重复 | 调研、PRD、计划、AI Coding、验证、复用 |
| 正文位置 | 分散草稿 | 统一在 [docs/v2/](docs/v2/)，目录见 [docs/v2/README.md](docs/v2/README.md) |
| 主案例 | 多案例接力 | [labs/10-a-share-research](labs/10-a-share-research/README.md) 十件套贯穿 |
| 调研、写作、计划 | 并列助手能力 | 连续产品交付阶段；侧例 Lab 保留 |
| AI Coding | 高风险压力测试的一部分 | 执行 PRD 和计划的核心阶段 |
| Skill / Automation / Eval | 独立能力模块 | 产品验证成功后的稳定复用链 |
| 毕业标准 | 完成一份综合任务 | 从自己的想法重新走完全过程 |
| 验收入口 | 工程 Lab 为主 | `lab-10`（主案例）+ `check`（全课） |

现有工程 Lab、`docs/v2/` 正文与 [docs/A股项目贯穿章节稿.md](docs/A股项目贯穿章节稿.md) 共同构成可发布课程ware；新增内容以主案例交付链为准对齐更新。
