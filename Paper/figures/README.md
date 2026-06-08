# Figures Directory

论文插图以 **draw.io**（`.drawio`）为推荐编辑格式；编译时优先嵌入导出的 **PDF**，若无导出则回退到 TikZ 源码（`.tex`）。

## 文件一览

| 源文件（编辑） | 导出（编译） | 回退（TikZ） | 论文中的图 |
|----------------|--------------|--------------|------------|
| `fig1_classify_control_flow.drawio` | `fig1_classify_control_flow.pdf` | `fig1_classify_control_flow.tex` | Figure 1（通栏）classify 控制流 |
| `fig2_retrieval_pipeline.drawio` | `fig2_retrieval_pipeline.pdf` | `fig2_retrieval_pipeline.tex` | Figure 2 |
| `fig3_positioning_matrix.drawio` | `fig3_positioning_matrix.pdf` | `fig3_positioning_matrix.tex` | Figure 3（能力矩阵） |
| `fig4_system_architecture.drawio` | `fig4_system_architecture.pdf` | `fig4_system_architecture.tex` | Figure 4 三层系统架构（Client / CS Agent / AI Infra） |
| `fig5_workflow_pipeline.drawio` | `fig5_workflow_pipeline.pdf` | `fig5_workflow_pipeline.tex` | Figure 5 LangGraph workflow pipeline（analyze → END） |
| `fig6_performance_funnel.drawio` | `fig6_performance_funnel.pdf` | `fig6_performance_funnel.tex` | Figure 6 Run 1 Hit@1 性能柱状图 |

`main.tex` 通过 `\includefig` 自动选择：存在 PDF → `\includegraphics`；否则 `\input{...}` TikZ/表格。

**fig1–fig6** 均已写入 `main.tex`：fig4（§3 架构）、fig5/fig1（Workflow）、fig2（Hybrid recall）、fig3（Related work 定位）、fig6（Runs~1--2 漏斗）。LaTeX 中的 Figure 编号按正文出现顺序自动编号，与文件名前缀不必一致。

## 用 draw.io 编辑

1. 安装 [draw.io Desktop](https://github.com/jgraph/drawio-desktop) 或打开 [diagrams.net](https://app.diagrams.net/)。
2. 打开本目录下对应的 `.drawio` 文件调整布局、配色、文字。
3. 导出 PDF（见下文）后重新编译 `main.tex`。

## 导出 PDF

**方式 A — 图形界面**

- File → Export as → PDF（建议勾选透明背景关闭、边框 8–10px）
- 保存为与源文件同名的 `.pdf`（例如 `fig1_classify_control_flow.pdf`）

**方式 B — 命令行**（需安装 draw.io 桌面版）

```bash
cd Paper/figures
chmod +x export_pdfs.sh
./export_pdfs.sh   # auto-detects draw.io on macOS; fig1=1680px wide, fig2–6=880px + --crop
```

一键导出 PDF 并打 Overleaf 包（在 `Paper/` 目录）：

```bash
cd Paper
./export_overleaf_zip.sh ~/Desktop/paper-overleaf.zip
```

## Overleaf

1. 上传 `main.tex`、`refs.bib`、整个 `figures/` 目录（含 `.drawio` 与可选 `.pdf`）。
2. 若在本地已导出 PDF，一并上传三个 `.pdf`，Overleaf 将直接使用矢量图，无需 TikZ。
3. 若仅上传 `.drawio` 未导出 PDF，将自动使用 `.tex` TikZ 回退（需 pdfLaTeX + TikZ）。

## 仅使用 TikZ（不编辑 draw.io）

保留现有 `fig*_*.tex` 即可；不放置 PDF 时编译行为与之前一致。

## 提示

- 图 1 宽度在 `main.tex` 中为 `0.92\textwidth`；图 2/3 为 `\columnwidth`。
- 导出 PDF 后若需提交到 Git，可将 `Paper/figures/*.pdf` 加入版本库（已在 `Paper/.gitignore` 中对 `figures/*.pdf` 放行）。
- 文件名保持小写加下划线，与 `\includefig` 路径一致。
