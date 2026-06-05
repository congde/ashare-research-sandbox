# 工单 #005：Review 双向闭环

## 实战 Brief

**背景**  
你收到一份 Agent 提交的 Diff（见 `sample_diff.patch`），需输出结构化 Review findings，并驱动 Agent 改评直至 `make challenge-005` 通过。

**验收标准**

```bash
make challenge-005
```

产出：`challenges/005-review/FINDINGS.md`（至少 2 条 finding，含严重级别）

**禁止项**

- 不得直接手改代码代替 Review 流程
- findings 必须可验证（对应测试或 lint）

---

## 决策卡

| 何时用 | Agent 首版 Diff 需人工或第二 Agent 审 |
| 何时不用 | 热修复且 Diff 仅 1 行 |
| 常见误用 | 泛泛而谈「代码风格不好」；无改评闭环 |

---

## 实操演示

1. 阅读 `sample_diff.patch`
2. 写 `FINDINGS.md`（Blocker / Major / Nit）
3. 委托 Agent 逐条修复
4. `make challenge-005`

---

## 翻车复盘

**现象**：Agent 声称已修复但未跑测试。  
**恢复**：每条 finding 绑定验收命令，改评后必须贴 pytest 输出。

---

## 过关任务

完成 findings + 改评，`make challenge-005` 通过。
