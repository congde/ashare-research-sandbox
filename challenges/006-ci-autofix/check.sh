#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

test -f .github/workflows/codex-autofix.yml
test -x scripts/codex-exec-fix.sh
bash scripts/codex-exec-fix.sh --dry-run

echo "✓ 工单 #006 通过"
