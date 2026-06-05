#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PLAYBOOK="$ROOT/playbook/my-playbook.md"

echo "==> 毕业综合 Challenge"

for id in 001-hotfix 002-explore 003-bugfix 004-feature-pr; do
  bash "challenges/$id/check.sh"
done

if [[ ! -f "$PLAYBOOK" ]]; then
  echo "✗ 缺少 playbook/my-playbook.md"
  exit 1
fi

count=$(grep -c "^## 模板" "$PLAYBOOK" || true)
if [[ "$count" -lt 3 ]]; then
  echo "✗ Playbook 至少需要 3 条委托模板"
  exit 1
fi

echo "✓ 毕业综合 Challenge 通过"
