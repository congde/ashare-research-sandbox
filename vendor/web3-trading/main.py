# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/18 16:54:02
'''

import os
import subprocess
import sys
import warnings

if sys.version_info < (3, 11):
    import enum

    if not hasattr(enum, "StrEnum"):
        class StrEnum(str, enum.Enum):
            pass

        enum.StrEnum = StrEnum

import uvicorn

warnings.filterwarnings("ignore")
base_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(base_path, "src"))

from web.application import create_app


app = create_app()


def free_port(port: int) -> None:
    current_pid = os.getpid()
    if os.name == "nt":
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        for line in result.stdout.splitlines():
            if f":{port}" not in line or "LISTENING" not in line:
                continue
            parts = line.split()
            if len(parts) < 5 or not parts[-1].isdigit():
                continue
            pid = int(parts[-1])
            if pid != current_pid:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False)
    else:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            check=False,
        )
        for pid in result.stdout.split():
            if pid.isdigit() and int(pid) != current_pid:
                subprocess.run(["kill", "-9", pid], check=False)


if __name__ == "__main__":
    port = int(os.getenv("SERVER_PORT", 10240))
    free_port(port)
    uvicorn.run(
        app,
        host=os.getenv("SERVER_HOST", "0.0.0.0"),
        port=port,
    )
