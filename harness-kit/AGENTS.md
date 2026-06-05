# codexDemo Agent 说明

你是 codexDemo 专栏的结对编程助手。遵循 Brief → 委托 → 审 Diff → 验收 闭环。

## 项目结构

- `app/src/todo_app/` — Todo 示例应用（Python）
- `challenges/` — 工单 #001–#006
- `harness-kit/` — 护栏配置 Lab
- `docs/` — 各讲 Markdown

## 硬性约束

1. **最小改动**：只改 Brief 指定文件，不顺手重构
2. **必须跑验收**：改完后执行 Brief 中的 `make` / `pytest` 命令
3. **禁止**：提交 `.env`、密钥、大范围格式化

## 委托模板

```
背景：<工单背景>
验收：make challenge-XXX
禁止：改 tests 断言、删现有测试
范围：仅 app/src/todo_app/service.py
```

## 常用命令

```bash
make setup
make check
make challenge-001
make harness-check
```
