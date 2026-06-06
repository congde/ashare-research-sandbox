# codexDemo

**Codex 智能交付实战课 · 配套交付仓库**

> 从第一张工单到团队级 Agent 工作流

这个仓库不是代码示例合集，而是专栏的交付训练场。每个任务都应留下可检查的输入、改动、交付物和验收证据。

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
├── AGENTS.md          # Codex 自动读取的项目级工作说明
├── docs/              # 20 讲正文、写作大纲与配套样本
├── labs/              # 与章节配套的可运行实验
├── skills/            # 课程中构建和验证的真实 Codex Skills
└── Makefile           # 统一入口：setup / check / lab-XX
```

## 课程设计

- [20 讲正文初稿](docs/v2/README.md)
- [20 讲交付版章节内容设计](docs/20讲交付版章节内容设计.md)
- [20 讲详细写作大纲](docs/20讲详细写作大纲.md)
- [极客时间立项大纲](极客时间立项大纲-Codex智能编程实战课.md)

## 配套实验

```bash
make lab-01   # 第一张工单：确认 starter 失败、solution 通过
make lab-16   # 验证 repo-readiness Skill 的报告契约
make courseware-check  # 检查已完成正文的本地链接
make check    # 运行全部课程资产验收
```

## 延伸阅读

《Codex：AI 驱动的智能编程时代》（邮电出版社）
