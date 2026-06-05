#!/usr/bin/env bash
# codex exec 自修复脚本模板 —— 工单 #006
set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
fi

PROMPT="${CODEX_FIX_PROMPT:-修复 app/tests 失败，最小改动，验收: make test}"

if $DRY_RUN; then
  echo "[dry-run] codex exec -a never \"$PROMPT\""
  exit 0
fi

if [[ -z "${CODEX_API_KEY:-}" ]]; then
  echo "✗ 请设置 CODEX_API_KEY"
  exit 1
fi

# 实际环境取消注释：
# codex exec -a never "$PROMPT"
echo "→ 接入 codex CLI 后在此执行 exec"
exit 0
