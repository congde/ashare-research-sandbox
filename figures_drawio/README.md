# 第 9-12 章配图（.drawio 可编辑格式）

本目录包含本书第 9-12 章的全部 19 张原创配图，每张图都是原生 draw.io
（mxGraph）XML 格式——每个方框、箭头、文字都是独立可编辑的图形元素，
而非 PNG/SVG 这种不可拆分的栅格/矢量整体。

## 怎么打开

1. **在线版（推荐）**：访问 https://app.diagrams.net/，菜单 File → Open
   From → Device，选择任意 `.drawio` 文件即可在浏览器里直接编辑。打开后
   选择"Save"会下载更新后的 `.drawio` 文件。
2. **桌面版**：下载 draw.io Desktop（https://www.drawio.com/），双击
   `.drawio` 文件即可打开。
3. **VS Code 插件**：装"Draw.io Integration"扩展（hediet.vscode-drawio）
   后，VS Code 里双击 `.drawio` 文件就能编辑。
4. **导出为 PNG / SVG / PDF**：在 draw.io 里 File → Export As 选择
   目标格式，可直接生成出版用的位图或矢量图。

## 文件清单

### 第 9 章 接手陌生代码库
- `fig9_1_parallel_recon.drawio`　并行勘察：主智能体 fan-out 与子代理汇总
- `fig9_2_agents_md_layers.drawio`　AGENTS.md 三层级架构与优先级
- `fig9_3_understanding_layers.drawio`　代码理解的四层金字塔
- `fig9_4_strangler_fig.drawio`　Strangler Fig 渐进式迁移模式
- `fig9_5_codex_worktrees.drawio`　Codex CLI 原生 worktree 三路并行

### 第 10 章 修 Bug、补测试、做回归
- `fig10_1_fix_loop.drawio`　Bug 修复验证闭环
- `fig10_2_test_pyramid.drawio`　AI 时代的测试金字塔
- `fig10_3_mutation_score.drawio`　行覆盖率 vs 变异得分对比
- `fig10_4_tia.drawio`　测试影响分析 TIA
- `fig10_5_git_bisect_codex.drawio`　git bisect + Codex 自动二分定位

### 第 11 章 跨前后端功能开发
- `fig11_1_api_contract.drawio`　API 契约自动化链路
- `fig11_2_migration_phases.drawio`　数据库迁移五阶段
- `fig11_3_consistency_check.drawio`　跨层一致性检查
- `fig11_4_release_coordination.drawio`　跨前后端发布的安全时序

### 第 12 章 PR、Review、CI/CD 自动化
- `fig12_1_ci_autofix.drawio`　CI 自修复闭环
- `fig12_2_pr_accept_v2.drawio`　任务分层的 PR 接受率（MSR '26）
- `fig12_3_risk_levels.drawio`　四级自动化风险分级框架
- `fig12_4_rollout.drawio`　Codex 自动化能力的渐进式落地路径
- `fig12_5_codex_review_triggers.drawio`　Codex CLI 三处审查触发点

## 样式约定

为保持视觉一致，所有图采用统一的色板：
- `#2C3E50` 主线色 / `#3B82F6` 强调色 / `#10B981` 成功色 / `#EF4444` 警告色
- 浅色填充：`#DBEAFE` 蓝 / `#D1FAE5` 绿 / `#FEF3C7` 黄 / `#FEE2E2` 红 / `#EDE9FE` 紫

如果需要重新染色，draw.io 的"Edit Style"对话框（Ctrl/Cmd+E）能直接改
`fillColor` 和 `strokeColor` 值，所有图的样式约定保持一致。

## 编辑建议

- 标题：默认 16px、加粗、`#2C3E50`，如需替换图号请改正文 docx 中的
  "图 X-Y" 引用一并同步
- 箭头：建议保持 `endArrow=classic;strokeWidth=1.8` 以与其他章节风格一致
- 添加新框：可复用现有框的样式（右键 → Edit Style → 复制粘贴）
