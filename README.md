# codexDemo

**Codex 个人助手实战课 · 配套交付仓库**

> 从日常委托到可验收交付

这个仓库不是代码示例合集，而是专栏的交付训练场。每个任务都应留下可检查的 Brief、产物与验收证据。

## 快速开始

macOS / Linux：

```bash
git clone https://github.com/congde/codexDemo.git
cd codexDemo
make setup    # 创建虚拟环境并安装依赖
make check    # 运行全量课程资产验收
```

Windows PowerShell（不要求安装 Make）：

```powershell
git clone https://github.com/congde/codexDemo.git
cd codexDemo
py scripts/course.py setup
py scripts/course.py check
```

如果 `py` 不可用，将命令中的 `py` 换成 `python`。运行前可用
`py --version` 或 `python --version` 确认 Python 已正确安装。

## 仓库结构

```
codexDemo/
├── AGENTS.md          # Codex 自动读取的项目级工作说明
├── docs/              # 20 讲正文、写作大纲与立项文档
├── labs/              # 与章节配套的可运行实验
├── skills/            # 助手向与工程向 Codex Skills
├── scripts/course.py  # Windows、macOS、Linux 共用的任务运行器
└── Makefile           # macOS / Linux 的简短命令入口
```

## 课程设计

- [20 讲正文](docs/v2/README.md)
- [20 讲详细写作大纲](docs/20讲详细写作大纲.md)
- [极客时间立项大纲](极客时间立项大纲-Codex智能编程实战课.md)
- [立项卖点一页纸](docs/极客时间课程卖点一页纸.md)

## 配套实验

macOS / Linux：

```bash
make lab-00   # 讲 1：Brief 结构验收
make lab-03   # 讲 3：入口决策与工作区合同验收
make lab-04   # 讲 4：调研报告来源验收
make lab-09   # 讲 9：weekly-brief Skill 验收
make lab-01   # 讲 14：热修复 fixture 验收
make lab-16   # 讲 13：repo-readiness Skill 验收
make check    # 运行全部课程资产验收
```

Windows PowerShell 使用对应任务名，例如：

```powershell
py scripts/course.py lab-00
py scripts/course.py lab-03
py scripts/course.py check
```

## 延伸阅读

《Codex：AI 驱动的智能编程时代》（邮电出版社）
