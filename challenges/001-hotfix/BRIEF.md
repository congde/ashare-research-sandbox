# 工单 #001：热修复

## 实战 Brief

**背景**  
线上反馈：Todo 列表「按优先级排序」结果反了——HIGH 排在 LOW 后面。值班同学已在 `app/src/todo_app/service.py` 定位到 `sort_by_priority`，需最小改动修复并跑通验收。

**验收标准**

```bash
make challenge-001
# 或
make check
```

**禁止项**

- 不得修改 `app/tests/` 中的断言
- 不得重构 `TodoService` 其他方法
- 不得删除 `# BUG(#001)` 注释（修复后改为说明性注释即可）

---

## 决策卡

| 何时用 | 小范围、有明确验收命令的紧急修复 |
| 何时不用 | 需改架构 / 多模块 —— 应开 Plans 或新工单 |
| 常见误用 | 委托里没写验收命令；顺手「优化」周边代码 |

---

## 实操演示

### 1. 写 Brief（委托）

```
修复 sort_by_priority 排序方向。
验收：make challenge-001
范围：仅 app/src/todo_app/service.py
禁止：改 tests
```

### 2. 审 Diff

确认只改了 `sorted(..., reverse=True)` 一行。

### 3. 跑验收

```bash
make setup
make challenge-001
```

---

## 翻车复盘

**现象**：Agent 改了 `service.py` 但把 `test_service.py` 断言也改了。  
**恢复**：`git checkout app/tests/` → 重新委托并强调「禁止改 tests」。

---

## 过关任务

1. 独立完成一次 Brief → 委托 → 审 Diff → `make challenge-001`
2. 截图验收输出 `✓ 工单 #001 通过`
