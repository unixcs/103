"""verify-lab Bot 启动入口

    cp .env.example .env      # 填 BOT_TOKEN / ADMIN_USER_ID
    python bot.py             # 真实 Telegram 轮询
    python bot.py --check     # 启动自检（数据库 / 渲染 / 审核状态机 / Token）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.bot_service import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
