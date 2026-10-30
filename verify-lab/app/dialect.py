"""SQL 方言 —— 把两种数据库的差异集中到两个类里

同一套业务逻辑要跑在 SQLite 和 MySQL 上，差异只有几处：

| 差异点            | SQLite                    | MySQL                     |
|-------------------|---------------------------|---------------------------|
| 参数占位符        | `?`                       | `%s`                      |
| 当前时间          | `datetime('now')`         | `NOW()`                   |
| 今天              | `date('now')`             | `CURDATE()`               |
| 取日期部分        | `date(col)`               | `DATE(col)`               |
| 插入并忽略冲突    | `INSERT OR IGNORE`        | `INSERT IGNORE`           |
| 开写事务 / 行锁   | `BEGIN IMMEDIATE`         | `START TRANSACTION` + `FOR UPDATE` |
| 唯一键冲突异常    | `sqlite3.IntegrityError`  | `pymysql.err.IntegrityError` |

把这些封装成"方言对象"，上层代码就只写一份 SQL 模板。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime


class Dialect:
    name = "base"
    placeholder = "?"
    lock_suffix = ""          # SELECT ... FOR UPDATE 的后缀，SQLite 用不到

    # ---- SQL 片段 ----
    def now_expr(self) -> str:
        raise NotImplementedError

    def today_expr(self) -> str:
        raise NotImplementedError

    def date_expr(self, column: str) -> str:
        raise NotImplementedError

    def insert_verb(self) -> str:
        """INSERT 的变体：冲突时忽略。"""
        raise NotImplementedError

    # ---- 事务 ----
    def begin_write(self, conn) -> None:
        raise NotImplementedError

    def commit(self, conn) -> None:
        conn.commit()

    def rollback(self, conn) -> None:
        conn.rollback()

    # ---- 结果与异常 ----
    def is_integrity_error(self, exc: BaseException) -> bool:
        return False

    def row_to_dict(self, row) -> dict:
        return dict(row) if not isinstance(row, dict) else dict(row)

    @staticmethod
    def parse_dt(value) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))


class SQLiteDialect(Dialect):
    name = "sqlite"
    placeholder = "?"
    lock_suffix = ""

    def now_expr(self) -> str:
        return "datetime('now')"

    def today_expr(self) -> str:
        return "date('now')"

    def date_expr(self, column: str) -> str:
        return f"date({column})"

    def insert_verb(self) -> str:
        return "INSERT OR IGNORE"

    def begin_write(self, conn) -> None:
        # 连上时设了 isolation_level=None，这里显式拿写锁
        conn.execute("BEGIN IMMEDIATE")

    def is_integrity_error(self, exc: BaseException) -> bool:
        return isinstance(exc, sqlite3.IntegrityError)


class MySQLDialect(Dialect):
    name = "mysql"
    placeholder = "%s"
    lock_suffix = " FOR UPDATE"      # 事务内锁住这一行，防并发超发

    def now_expr(self) -> str:
        return "NOW()"

    def today_expr(self) -> str:
        return "CURDATE()"

    def date_expr(self, column: str) -> str:
        return f"DATE({column})"

    def insert_verb(self) -> str:
        return "INSERT IGNORE"

    def begin_write(self, conn) -> None:
        # pymysql 连接是 autocommit=False 的，begin() 会发 START TRANSACTION
        conn.begin()

    def is_integrity_error(self, exc: BaseException) -> bool:
        try:
            import pymysql
        except ImportError:                  # 没装驱动也能判定：靠类名兜底
            return exc.__class__.__name__ == "IntegrityError"
        return isinstance(exc, pymysql.err.IntegrityError)
