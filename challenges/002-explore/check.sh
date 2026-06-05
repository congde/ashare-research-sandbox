#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMPACT="$ROOT/challenges/002-explore/IMPACT.md"

required=("模块地图" "调用链" "测试覆盖" "改动影响")

for section in "${required[@]}"; do
  if ! grep -q "$section" "$IMPACT"; then
    echo "✗ IMPACT.md 缺少章节: $section"
    exit 1
  fi
done

if grep -q "（填写）" "$IMPACT"; then
  echo "✗ IMPACT.md 仍有未填写的「（填写）」占位"
  exit 1
fi

echo "✓ 工单 #002 通过"
