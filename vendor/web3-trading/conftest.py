# conftest.py — 根目录 pytest 配置
import sys
from pathlib import Path

# 把 src/ 加入模块搜索路径，无论从哪里运行 pytest 都生效
sys.path.insert(0, str(Path(__file__).parent / "src"))
