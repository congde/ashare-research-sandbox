# Brief：评估是否值得从 Notion 迁移到 Obsidian

## Goal

产出一份面向个人用户的决策报告，判断从 Notion 迁移到 Obsidian 是否值得，并明确推荐“迁移”“暂不迁移”或“先小范围试迁移”的条件与理由。报告应帮助用户作出决定，但不得执行真实迁移。

## Context

- 当前主要笔记工具是 Notion，候选工具是 Obsidian。
- 评估对象是个人笔记与知识管理，不讨论团队级知识库选型。
- 重点比较：数据所有权与可迁移性、离线可用性、跨设备同步、写作与检索体验、数据库与协作能力、维护成本、插件依赖风险，以及未来一年的费用。
- 事实信息以执行调研时可访问的 Obsidian 与 Notion 官方定价、帮助中心和产品文档为准。
- 用户的笔记规模、常用 Notion 数据库、协作需求和设备组合尚未确认；报告应说明这些未知如何影响结论，并按不同场景给出条件式建议，不得自行补全用户情况。

## Constraints

- 只评估并提出建议，不登录账户、不安装软件、不导出、删除或迁移任何真实笔记。
- 产品功能、限制和价格只引用官方来源；用户体验判断可以标为推断，但不得伪装成事实。
- 不把插件能够实现的能力表述为 Obsidian 核心功能；涉及插件时说明维护与兼容风险。
- 不只比较功能清单，必须结合迁移成本与用户现有工作流判断。
- 不默认 Obsidian 或 Notion 必然更优，也不因本 Brief 的标题预设应当迁移。
- 最终报告不超过 1,500 字，并清楚区分 Facts、Inferences、Recommendations 和 Unknowns。

## Done when

- 报告保存为 `reports/notion-to-obsidian-migration-assessment.md`。
- 报告包含 `Facts`、`Inferences`、`Recommendations`、`Unknowns` 和 `Sources` 五个部分。
- `Facts` 中每条事实均附有可打开的官方来源 URL，并注明核对日期。
- 报告覆盖 Context 中列出的八个比较维度，并提供一张简洁的对比表。
- 报告估算至少三类迁移成本：内容导出与整理、Notion 数据库能力替代、跨设备同步配置。
- `Recommendations` 至少分别说明“适合迁移”“适合暂不迁移”和“信息不足时先试迁移”的条件，并包含一个风险较低、可回退的 14 天试迁移方案。
- `Unknowns` 列出仍需用户回答的问题，并说明每个问题可能怎样改变建议。
- 执行者逐条打开并人工核对至少一条 Obsidian 价格事实和一条 Notion 价格事实。
- 运行 `python labs/04-research/verify.py reports/notion-to-obsidian-migration-assessment.md`；若脚本不适用于该报告结构，则记录未通过原因，不得声称验证通过。

## Open questions

- 当前 Notion 中大约有多少页面、附件和数据库？
- 是否依赖关系型数据库、看板、公式、自动化或公开分享页面？
- 是否需要与他人实时协作？
- 日常使用哪些设备，是否接受为同步服务付费？
- 本地 Markdown 文件是否属于硬性要求？
- 可接受的试迁移时间和手工整理成本是多少？
