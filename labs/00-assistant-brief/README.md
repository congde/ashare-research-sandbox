# Lab 00：任务说明（Brief）

本实验教你写出一份可委托的最小任务说明。起始样例故意不完整；完整样例展示团队文档迁移场景下的一份合格 Brief——请在你自己的草稿通过检查**之后**再对照阅读。

## 任务

1. 阅读 [brief-template.md](brief-template.md) 与 [starter/brief.md](starter/brief.md)。
   在打开 `solution/brief.md` 之前，先写下 starter 缺了哪些结构、哪些内容不足。
2. 将 `brief-template.md` 复制为本目录下的 `my-brief.md`。
3. 为一个**非代码**任务（调研、写作或计划）填完五栏。
4. 对 `my-brief.md` 运行 `verify.py`，直到通过。
5. 此时再打开 [solution/brief.md](solution/brief.md)，对照差异。

## 验证教具

```bash
python scripts/course.py lab-00
```

也可使用 `make lab-00`（若本机已安装 Make）。

脚本证明检查器本身有效：

1. 起始 Brief 未通过结构检查。
2. 完整 Brief 通过同一套检查。

仅运行 `lab-00` 不算完成实验——你自己的 Brief 仍需单独通过 `verify.py`。

## 验证你自己的 Brief

```bash
python labs/00-assistant-brief/verify.py labs/00-assistant-brief/my-brief.md
```

`my-brief.md` 已加入 `.gitignore`，练习草稿保留在本地即可。
