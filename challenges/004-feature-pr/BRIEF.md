# 工单 #004：跨端功能 PR

## 实战 Brief

**背景**  
产品要求 CLI 支持 `--tag` 过滤，与 `TodoService.list(TodoFilter(tag=...))` 对齐。

**验收标准**

```bash
make challenge-004
```

**禁止项**

- 不得破坏现有 `add` / `list` 子命令行为
- 单次 PR 仅包含 CLI + 对应测试

---

## 决策卡

| 何时用 | 多文件但边界清晰的竖切功能 |
| 何时不用 | 需改数据模型 / 数据库迁移 |
| 常见误用 | 一个 PR 混入格式化、无关重构 |

---

## 实操演示

委托：

```
为 cli.py 的 list 子命令增加 --tag 参数，调用 TodoFilter。
新增 app/tests/test_cli.py。
验收：make challenge-004
```

---

## 翻车复盘

**现象**：CLI 能过滤但 JSON 输出字段不一致。  
**恢复**：Brief 里写清输出 schema，补集成测试。

---

## 过关任务

完成 PR 描述（背景 / 验收 / 风险）并通过 `make challenge-004`。
