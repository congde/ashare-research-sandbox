from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
WEB_STATIC_DIR = SRC_ROOT / "web" / "static"
