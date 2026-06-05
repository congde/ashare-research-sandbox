#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv/bin"
echo "==> 工单 #003 Bug 回归验收"
"$VENV/pytest" app/tests/test_regression_003.py app/tests/test_service.py -q
echo "✓ 工单 #003 通过"
