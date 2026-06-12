# Research package: Tencent Docs to Feishu Docs

## Research question map

| ID | Question | Why it matters | Preferred source | Stop condition |
|---|---|---|---|---|
| Q1 | 两个平台覆盖哪些团队协作能力？ | 判断试点是否值得开始 | 官方产品页 | 能力边界已记录 |
| Q2 | 目标版本与团队规模对应什么成本？ | 影响迁移收益 | 官方定价页 | 当前公开版本边界已记录 |
| Q3 | 代表性迁移能否保留格式、评论、权限和历史记录？ | 可能使迁移成本不可接受 | 真实迁移测试 | 已复核一个项目空间 |
| Q4 | 团队当前流程真正卡在哪里？ | 决定迁移是否解决真实问题 | 团队访谈 | 阻塞项已排序 |

## Source cards

### S1

- URL: https://docs.qq.com/
- Source role: official Tencent Docs product page
- Retrieved: 2026-06-12
- Supports: 腾讯文档提供在线文档、表格、幻灯片和收集表等产品入口。
- Does not support: 迁移到飞书文档后格式与权限能够完整保留。
- Freshness or access concern: 产品能力可能更新，正式决策前应重新核对。

### S2

- URL: https://www.feishu.cn/product/docs
- Source role: official Feishu Docs product page
- Retrieved: 2026-06-12
- Supports: 飞书文档将文档、表格、多维表格、知识库等能力放在同一协作平台中。
- Does not support: 这些能力一定能解决特定团队的协作问题。
- Freshness or access concern: 产品介绍不能替代团队试点。

### S3

- URL: https://www.feishu.cn/pricing
- Source role: official pricing
- Retrieved: 2026-06-12
- Supports: 飞书提供按版本区分的公开定价页。
- Does not support: 特定团队的总迁移成本。
- Freshness or access concern: 定价可能变化，采购前应重新核对。

### S4

- URL: https://docs.qq.com/
- Source role: official source boundary
- Retrieved: 2026-06-12
- Supports: 腾讯文档是当前迁移来源平台。
- Does not support: 导入飞书文档后的格式、评论、权限与历史记录保真度。
- Freshness or access concern: 迁移保真度必须通过真实样本验证。

## Claim ledger

| ID | Claim | Type | Supports | Status |
|---|---|---|---|---|
| F1 | 腾讯文档提供多类在线协作文档产品入口 | Fact | S1 | accepted |
| F2 | 飞书文档在同一平台提供文档、表格、多维表格与知识库等能力 | Fact | S2 | accepted |
| F3 | 飞书提供按版本区分的公开定价页 | Fact | S3 | accepted |
| F4 | 官网产品介绍不能证明迁移保真度 | Fact | S1, S2, S4 | accepted |
| I1 | 一体化协作诉求足够强时，飞书文档值得小范围试点 | Inference | F2, F4 | accepted |
| I2 | 决策需同时比较版本成本与真实迁移保真度 | Inference | F3, F4 | accepted |
| R1 | 先迁移一个项目空间试点两周 | Recommendation | I1 | accepted |
| R2 | 记录迁移缺陷与团队使用摩擦后再决定 | Recommendation | I2 | accepted |
| U1 | 团队真实协作阻塞尚未确认 | Unknown | Q4 | open |
| U2 | 格式、评论、权限和历史记录保真度尚未验证 | Unknown | Q3 | open |
| F5 | 飞书文档一定比腾讯文档更适合团队 | Fact | S2 | rejected: source does not support team-specific fit |

## Source review log

| Fact ID | Review result | What the source supports | Required rewrite |
|---|---|---|---|
| F2 | fully supported | 飞书文档产品能力范围 | None |
| F3 | fully supported | 存在按版本区分的公开定价页 | None |

## Handoff

- Questions covered: Q1 and Q2 have official-source candidates.
- Questions still open: Q3 requires a representative migration test; Q4 requires team interviews.
- Sources that could not be accessed: None recorded in this fixture.
- Claims rejected or downgraded: F5 was rejected because a product page cannot prove team-specific fit.
- Next action: Migrate one representative project space and record defects before making a decision.
