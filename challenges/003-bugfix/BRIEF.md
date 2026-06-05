# 工单 #003：Bug 定位与回归

## 实战 Brief

**背景**  
`TodoService.list()` 在同时指定 `done=False` 与 `min_priority` 时结果不正确（低优先级未完成项仍会出现）。

**验收标准**

```bash
make challenge-003
```

新增回归测试 `app/tests/test_regression_003.py` 并通过。

**禁止项**

- 不得删除现有测试
- 不得修改 `challenges/*/check.sh`

---

## 决策卡

| 何时用 | 有复现步骤、需补回归测试 |
| 何时不用 | 无稳定复现 —— 先勘察 |
| 常见误用 | 只改实现不写测试；测试过于耦合实现细节 |

---

## 实操演示

```bash
# 先看失败测试
make setup
.venv/bin/pytest app/tests/test_regression_003.py -v
```

委托：修复 `list()` 过滤逻辑 + 保持测试绿色。

---

## 翻车复盘

**现象**：修复后 `test_filter_by_tag` 失败 —— 过滤条件组合顺序错了。  
**恢复**：跑全量 `make test`，用 Plans 分步修。

---

## 过关任务

`make challenge-003` 通过并提交 PR（或本地 commit 记录）。
