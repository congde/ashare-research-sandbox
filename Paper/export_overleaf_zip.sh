#!/usr/bin/env bash
# Export draw.io PDFs (LaTeX-friendly width) and pack for Overleaf Upload project.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "==> Exporting figure PDFs..."
bash figures/export_pdfs.sh

ZIP="${1:-$ROOT/paper-overleaf.zip}"
rm -f "$ZIP"
zip -r "$ZIP" main.tex refs.bib \
  figures/fig1_classify_control_flow.pdf \
  figures/fig2_retrieval_pipeline.pdf \
  figures/fig3_positioning_matrix.pdf \
  figures/fig4_system_architecture.pdf \
  figures/fig5_workflow_pipeline.pdf \
  figures/fig6_performance_funnel.pdf \
  figures/fig1_classify_control_flow.tex \
  figures/fig2_retrieval_pipeline.tex \
  figures/fig3_positioning_matrix.tex \
  figures/fig4_system_architecture.tex \
  figures/fig5_workflow_pipeline.tex \
  figures/fig6_performance_funnel.tex

echo "==> Created: $ZIP"
echo "Overleaf: Upload project → $ZIP"
echo "Menu → Main document → main.tex → Recompile (pdfLaTeX)"
