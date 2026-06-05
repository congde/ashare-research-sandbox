# codexDemo

**Codex 智能编程实战课 · 配套代码仓库**

> 动手篇——在真实工作流里把 Codex 用到过关

## 快速开始

```bash
git clone https://github.com/congde/codexDemo.git
cd codexDemo
make setup    # 创建虚拟环境并安装依赖
make check    # 运行全量验收（第一篇过关标志）
```

## 仓库结构

```
codexDemo/
├── docs/              # 各讲 Markdown（Brief / 决策卡 / 实操 / 翻车 / 过关任务）
├── app/               # 实战载体：Todo 示例应用
├── harness-kit/       # 第二篇：护栏装配 Lab（config / AGENTS / Rules / Hooks）
├── challenges/        # 工单 #001–#006 + 毕业综合 Challenge
├── scripts/           # 验收脚本
├── playbook/          # 第六篇：Playbook 导出模板
└── Makefile           # 统一入口：setup / check / challenge-XXX
```

## 课程目录

| 篇章 | 讲次 | 文档 | 过关标志 |
|------|------|------|----------|
| 开篇 | 开篇词 | [docs/00-开篇词.md](docs/00-开篇词.md) | Fork 本仓库 |
| 第一篇 | 讲 1–3 | [docs/01](docs/) | `make check` + 工单 #001 |
| 第二篇 | 讲 4–5 | [docs/04](docs/) | `config.toml` + harness-kit 联调 |
| 第三篇 | 讲 6–10 | [docs/06](docs/) | 完成 5 张工单中至少 4 张 |
| 第四篇 | 讲 11–12 | [docs/11](docs/) | Cloud Handoff + Automation |
| 第五篇 | 讲 13–14 | [docs/13](docs/) | 1 次非编码任务产出 |
| 第六篇 | 讲 15–17 | [docs/15](docs/) | 导出个人 Playbook |
| 结束 | 结束语 | [docs/99-结束语.md](docs/99-结束语.md) | — |

## 工单速查

```bash
make challenge-001   # 热修复
make challenge-002   # 陌生模块勘察
make challenge-003   # Bug 定位与回归
make challenge-004   # 跨端功能 PR
make challenge-005   # Review 双向闭环
make challenge-006   # CI 自修复
make challenge-graduation  # 毕业综合 Challenge
```

## 延伸阅读

《Codex：AI 驱动的智能编程时代》（邮电出版社）
