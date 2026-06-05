#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv/bin"
if [[ ! -x "$VENV/pytest" ]]; then
  echo "请先运行: make setup"
  exit 1
fi

echo "==> 工单 #001 热修复验收"

"$VENV/pytest" app/tests/test_service.py::test_sort_by_priority_desc -q

echo "✓ 工单 #001 通过"
