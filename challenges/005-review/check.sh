#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FINDINGS="$ROOT/challenges/005-review/FINDINGS.md"

for level in "Blocker" "Major" "改评记录"; do
  grep -q "$level" "$FINDINGS" || { echo "✗ FINDINGS.md 缺少: $level"; exit 1; }
done

if grep -q "（示例：" "$FINDINGS"; then
  echo "✗ FINDINGS.md 仍为模板占位，请填写真实 findings"
  exit 1
fi

echo "✓ 工单 #005 通过"
