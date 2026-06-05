# 委托规则

## 必须

- 每次委托附带**验收命令**（如 `make challenge-003`）
- Diff 审阅通过后再 stage
- 改动保持单一职责，一张工单一个 PR

## 禁止

- 修改 `challenges/*/check.sh` 验收脚本
- 删除或弱化测试断言
- 在无 Brief 授权时修改 `harness-kit/` 配置

## 推荐

- 陌生模块先 `@` 引用 `docs/` 与 `AGENTS.md`
- 大任务拆 Plans，每步可独立验收
