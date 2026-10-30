"""MySQL 后端 —— 与 SQLite 版共用 base.py 的全部业务逻辑

已对真实 MySQL 8.0（Docker）验证：
  1. sql/schema_mysql.sql 建表；
  2. tests/test_mysql_integration.py 的全链路、事务、行锁、DATETIME 归一化；
  3. 20 线程并发扣分与卡密防超发；
  4. tests/test_bot_mysql_e2e.py 的 Bot + MySQL 全栈；
  5. Docker 容器内 bot.py --check。

连接信息从环境变量读取（见 .env.example）；没装 pymysql 或没起库时会给出明确报错。
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from .base import BaseDatabase
from .dialect import MySQLDialect

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "schema_mysql.sql"


def _split_statements(sql: str) -> list[str]:
    """把 .sql 文件拆成一条条语句（去掉 -- 注释行）。"""
    body = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    return [stmt.strip() for stmt in body.split(";") if stmt.strip()]


class MySQLDatabase(BaseDatabase):
    dialect = MySQLDialect()

    def __init__(self, config: dict | None = None, connect_factory=None):
        self.config = config or {
            "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
            "port": int(os.getenv("MYSQL_PORT", "3306")),
            "user": os.getenv("MYSQL_USER", "lab"),
            "password": os.getenv("MYSQL_PASSWORD", "labpass"),
            "database": os.getenv("MYSQL_DATABASE", "verify_lab"),
            "charset": "utf8mb4",
            "autocommit": False,
        }
        # connect_factory 用于测试注入假连接；生产不传
        self._connect_factory = connect_factory
        super().__init__()

    def _pymysql(self):
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError(
                "MySQL 后端需要 pymysql：pip install pymysql"
            ) from exc
        return pymysql

    @contextmanager
    def _connect(self):
        if self._connect_factory is not None:
            conn = self._connect_factory()
        else:
            pymysql = self._pymysql()
            conn = pymysql.connect(
                **self.config,
                cursorclass=pymysql.cursors.DictCursor,
            )
        try:
            yield conn
        finally:
            conn.close()

    def init_database(self) -> None:
        statements = _split_statements(SCHEMA_PATH.read_text(encoding="utf-8"))
        with self._connect() as conn:
            cur = conn.cursor()
            for stmt in statements:
                cur.execute(stmt)
            conn.commit()
