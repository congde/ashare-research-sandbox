# 工单 #002：陌生模块勘察

## 实战 Brief

**背景**  
你刚接手 codexDemo，需要在不改代码的前提下产出「模块地图 + 影响分析」，供后续工单 #003 使用。

**验收标准**

```bash
make challenge-002
```

产出文件：`challenges/002-explore/IMPACT.md`（模板已提供，需填完整）

**禁止项**

- 不得修改 `app/` 业务代码
- 不得跳过影响分析直接改 Bug

---

## 决策卡

| 何时用 | 进陌生仓库、大模块、Legacy 代码 |
| 何时不用 | 单行热修复且路径明确 |
| 常见误用 | 只要口头总结、不落文档；地图与后续改动脱节 |

---

## 实操演示

委托示例：

```
阅读 app/src/todo_app/，输出：
1. 模块职责（models / service / cli）
2. sort_by_priority 调用链
3. 若改 filter 逻辑会影响哪些测试
写入 challenges/002-explore/IMPACT.md
禁止改 app/ 代码
```

---

## 翻车复盘

**现象**：地图只列文件名，没有数据流。  
**恢复**：要求补充「谁调用谁、测试覆盖哪条路径」。

---

## 过关任务

填完 `IMPACT.md` 并通过 `make challenge-002`。
