"""兼容旧入口 —— 真正的实现已经搬到 app/bot_service.py

保留这个文件只是为了让以前的命令还能跑：

    python bot_skeleton.py

新代码请用 `python bot.py`；参数完全一致（支持 --check）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.bot_service import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
