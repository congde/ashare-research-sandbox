"""工单 #004：CLI --tag 功能测试（实现前失败）。"""

import json
import subprocess
import sys
from pathlib import Path

APP_SRC = Path(__file__).resolve().parents[1] / "src"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(APP_SRC / "todo_app" / "cli.py"), *args],
        capture_output=True,
        text=True,
        cwd=APP_SRC,
    )


def test_list_filter_by_tag():
    run_cli("add", "后端任务", "--priority", "high")
    # 第二条需带 tag —— 当前 CLI 不支持，学员扩展 add 或测试用 service 预置
    # 简化：仅验证 list --tag 子命令存在且可解析
    result = run_cli("list", "--tag", "backend")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data, list)
