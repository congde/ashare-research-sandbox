#!/usr/bin/env bash
# 任务结束后提醒跑验收（由 Codex Hook 或手动调用）
set -euo pipefail

echo "→ 记得运行 Brief 中的验收命令，例如："
echo "    make check"
echo "    make challenge-001"
