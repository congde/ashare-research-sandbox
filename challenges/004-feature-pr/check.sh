#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv/bin"
CLI="$ROOT/app/src/todo_app/cli.py"

echo "==> 工单 #004 跨端功能 PR 验收"

# 检查 list 支持 --tag
"$VENV/python" "$CLI" list --help | grep -q -- '--tag'

"$VENV/pytest" app/tests/test_cli.py -q
echo "✓ 工单 #004 通过"
