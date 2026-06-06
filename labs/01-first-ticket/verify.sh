#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTEST="$ROOT/.venv/bin/pytest"

if [[ ! -x "$PYTEST" ]]; then
  echo "Run 'make setup' first."
  exit 1
fi

echo "==> Confirm the starter fails for the intended reason"
if PYTHONPATH="$ROOT/labs/01-first-ticket/starter" \
  "$PYTEST" "$ROOT/labs/01-first-ticket/starter/test_todo.py" -q >/tmp/codex-demo-lab01-starter.log 2>&1; then
  echo "Starter unexpectedly passed."
  exit 1
fi
grep -q "restore checkout" /tmp/codex-demo-lab01-starter.log

echo "==> Confirm the minimal solution passes"
PYTHONPATH="$ROOT/labs/01-first-ticket/solution" \
  "$PYTEST" "$ROOT/labs/01-first-ticket/solution/test_todo.py" -q

echo "Lab 01 fixture is valid."

