"""SQLite 后端 —— 零配置，demo 和单测用它

只负责三件事：怎么连、怎么建表、以及把方言告诉上层。
业务逻辑全部在 base.py。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from .base import BaseDatabase
from .dialect import SQLiteDialect

# 兼容旧引用：app.db.VERIFY_COST 等仍然可用
from .settings import (  # noqa: F401
    CHECKIN_REWARD,
    INVITE_REWARD,
    REGISTER_REWARD,
    VERIFY_COST,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT,
    full_name    TEXT,
    balance      INTEGER NOT NULL DEFAULT {register_reward},
    is_blocked   INTEGER NOT NULL DEFAULT 0,
    invited_by   INTEGER,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    last_checkin TEXT
);

CREATE TABLE IF NOT EXISTS invitations (
    inviter_id INTEGER NOT NULL,
    invitee_id INTEGER NOT NULL UNIQUE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS verifications (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    kind      TEXT NOT NULL,
    status    TEXT NOT NULL,
    detail    TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS card_keys (
    key_code     TEXT PRIMARY KEY,
    balance      INTEGER NOT NULL,
    max_uses     INTEGER NOT NULL DEFAULT 1,
    current_uses INTEGER NOT NULL DEFAULT 0,
    created_by   INTEGER,
    expire_at    TEXT
);

CREATE TABLE IF NOT EXISTS card_key_usage (
    key_code TEXT NOT NULL,
    user_id  INTEGER NOT NULL,
    used_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (key_code, user_id)
);
""".format(register_reward=REGISTER_REWARD)


class SQLiteDatabase(BaseDatabase):
    dialect = SQLiteDialect()

    def __init__(self, path: str = "verify_lab.db"):
        self.path = str(path)
        super().__init__()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_database(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)


# 旧名字保留，demo / bot / 测试都不用改
Database = SQLiteDatabase
