#!/usr/bin/env bash
# Export draw.io → PDF sized for LaTeX (\includefig in main.tex).
# macOS: brew install --cask drawio
#   DRAWIO="/Applications/draw.io.app/Contents/MacOS/draw.io" ./export_pdfs.sh
set -euo pipefail
cd "$(dirname "$0")"

if [[ -z "${DRAWIO:-}" ]]; then
  if [[ -x "/Applications/draw.io.app/Contents/MacOS/draw.io" ]]; then
    DRAWIO="/Applications/draw.io.app/Contents/MacOS/draw.io"
  else
    DRAWIO="drawio"
  fi
fi

if ! command -v "$DRAWIO" &>/dev/null && [[ ! -x "$DRAWIO" ]]; then
  echo "draw.io CLI not found. Install draw.io desktop or set DRAWIO= path." >&2
  echo "Edit .drawio at https://app.diagrams.net/ and export PDF manually." >&2
  exit 1
fi

# Match main.tex: fig1 = figure* 0.92\textwidth; fig2–6 = \columnwidth (~3.33in printable).
# --width fits diagram to target px width; --crop trims canvas margins.
export_one() {
  local base="$1"
  local width_px="$2"
  echo "Exporting ${base}.drawio -> ${base}.pdf (width=${width_px}px, crop)"
  "$DRAWIO" --export --format pdf \
    --border 6 \
    --crop \
    --width "$width_px" \
    -o "${base}.pdf" "${base}.drawio"
}

export_one fig1_classify_control_flow 1680
export_one fig2_retrieval_pipeline 880
export_one fig3_positioning_matrix 880
export_one fig4_system_architecture 880
export_one fig5_workflow_pipeline 880
export_one fig6_performance_funnel 880

echo "Done. PDFs sized for LaTeX. Recompile Paper/main.tex or run ../export_overleaf_zip.sh"
