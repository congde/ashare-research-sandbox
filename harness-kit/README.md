# Codex Harness Kit

本目录为**第二篇 · 讲 4「护栏装配 Lab」**配套资产。  
目标：一次装齐 Sandbox / 审批 / AGENTS.md + Rules + Hook。

## 目录

```
harness-kit/
├── config.toml.example   # 项目级 Codex 配置模板
├── AGENTS.md             # Agent 行为说明
├── rules/                # 委托与禁区规则
├── hooks/                # 提交前 / 验收 Hook
└── scripts/verify.sh     # harness-kit 联调验收
```

## 快速联调

```bash
# 复制配置到项目根（或 ~/.codex/config.toml）
cp harness-kit/config.toml.example .codex/config.toml

make harness-check
```

## 与专栏文档

详见 [docs/04-护栏装配Lab.md](../docs/04-护栏装配Lab.md)
