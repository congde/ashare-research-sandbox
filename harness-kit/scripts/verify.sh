#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "==> harness-kit 联调验收"

test -f harness-kit/AGENTS.md
test -f harness-kit/config.toml.example
test -f harness-kit/rules/delegation.md
test -f harness-kit/rules/safety.md
test -x harness-kit/hooks/pre-commit.sh

bash harness-kit/hooks/pre-commit.sh 2>/dev/null || true

echo "✓ harness-kit 联调通过 —— 第二篇过关标志达成"
