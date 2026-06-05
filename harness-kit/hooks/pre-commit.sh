#!/usr/bin/env bash
# pre-commit hook 示例：阻止误提交敏感文件
set -euo pipefail

BLOCKED='\.env$|credentials\.json|\.pem$'
if git diff --cached --name-only | grep -E "$BLOCKED"; then
  echo "✗ 检测到敏感文件，拒绝提交"
  exit 1
fi

echo "✓ pre-commit 检查通过"
