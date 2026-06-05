# 工单 #006：CI 自修复

## 实战 Brief

**背景**  
GitHub Actions 中 pytest 失败时，用 `codex exec` 自动尝试修复并重新跑 CI（本仓库提供 workflow 模板）。

**验收标准**

```bash
make challenge-006
```

**禁止项**

- 不得在 workflow 中硬编码 API Key
- 不得关闭 required check 绕过 CI

---

## 决策卡

| 何时用 | 重复性失败、修复模式固定（如 lint / 单测） |
| 何时不用 |  flaky 测试、需产品决策的语义变更 |
| 常见误用 | 无限循环 exec；无人工审批 gate |

---

## 实操演示

见 `.github/workflows/codex-autofix.yml` 与 `scripts/codex-exec-fix.sh`。

---

## 翻车复盘

**现象**：CI 自动提交到 main。  
**恢复**：改为 PR 分支 + required review。

---

## 过关任务

本地 `make challenge-006` 通过；可选：Fork 后观察 Action 运行。
