#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> codexDemo 全量验收"
echo "    1/2  单元测试"
make test

echo "    2/2  工单 #001 热修复验收"
bash challenges/001-hotfix/check.sh

echo ""
echo "✓ make check 全部通过 —— 第一篇过关标志达成"
