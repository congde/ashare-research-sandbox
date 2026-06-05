#!/usr/bin/env python3
"""命令行入口 —— 讲 4 跨端功能 PR 会扩展此模块。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许从仓库根目录直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from todo_app.models import Priority  # noqa: E402
from todo_app.service import TodoService  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Todo CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    add_p = sub.add_parser("add", help="添加 Todo")
    add_p.add_argument("title")
    add_p.add_argument("--priority", choices=["low", "medium", "high"], default="medium")

    sub.add_parser("list", help="列出全部 Todo")

    args = parser.parse_args(argv)
    svc = TodoService()

    if args.cmd == "add":
        pri_map = {"low": Priority.LOW, "medium": Priority.MEDIUM, "high": Priority.HIGH}
        todo = svc.add(args.title, priority=pri_map[args.priority])
        print(json.dumps({"id": todo.id, "title": todo.title, "priority": todo.priority.name}))
        return 0

    if args.cmd == "list":
        todos = svc.list()
        print(json.dumps([{"id": t.id, "title": t.title, "done": t.done} for t in todos]))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
