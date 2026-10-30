"""后端工厂 —— 用环境变量切换 SQLite / MySQL

    DB_BACKEND=sqlite   python bot_skeleton.py     # 默认
    DB_BACKEND=mysql    python bot_skeleton.py     # 需要先起 MySQL

业务代码只认 BaseDatabase 的接口，不关心底下是哪个库。
"""
from __future__ import annotations

import os


def make_database(backend: str | None = None, **kwargs):
    backend = (backend or os.getenv("DB_BACKEND", "sqlite")).strip().lower()

    if backend == "sqlite":
        from .db import SQLiteDatabase
        return SQLiteDatabase(kwargs.get("path") or os.getenv("SQLITE_PATH", "verify_lab.db"))

    if backend == "mysql":
        from .db_mysql import MySQLDatabase
        return MySQLDatabase(kwargs.get("config"))

    raise ValueError(f"不支持的数据库后端：{backend!r}（可选 sqlite / mysql）")
