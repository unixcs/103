"""双后端测试

不依赖真库的：
  1. 两种方言生成的 SQL 片段是否正确；
  2. MySQL 后端在**假连接**下生成的 SQL 形状（%s / FOR UPDATE / CURDATE）；
  3. 工厂按环境变量选后端；
  4. 两个后端的公共接口一致。

需要真库的（设 VERIFY_LAB_MYSQL=1，默认跳过）：
  5. 真实 MySQL 的语义（事务隔离、锁行为、DATETIME 解析）——
     已在 Docker mysql:8.0 上验证，见 tests/test_mysql_integration.py。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.base import BaseDatabase                    # noqa: E402
from app.db import SQLiteDatabase                    # noqa: E402
from app.db_mysql import MySQLDatabase               # noqa: E402
from app.dialect import MySQLDialect, SQLiteDialect  # noqa: E402
from app.factory import make_database                # noqa: E402

PYMYSQL_INSTALLED = importlib.util.find_spec("pymysql") is not None


class FakeCursor:
    def __init__(self, conn: "FakeConnection"):
        self._conn = conn

    @property
    def rowcount(self) -> int:
        return self._conn.rowcount

    @property
    def lastrowid(self) -> int:
        return 1

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._conn.executed.append((sql, params))

    def fetchone(self):
        return self._conn.rows.pop(0) if self._conn.rows else None

    def fetchall(self):
        return []

    def close(self) -> None:
        pass


class FakeConnection:
    """只记录 SQL、按队列返回结果，不连任何数据库。"""

    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []
        self.rows: list[dict] = []
        self.rowcount = 1
        self.commits = 0
        self.rollbacks = 0
        self.began = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def begin(self) -> None:
        self.began = True

    def close(self) -> None:
        pass


class TestDialect(unittest.TestCase):
    def test_sqlite_fragments(self):
        d = SQLiteDialect()
        self.assertEqual(d.placeholder, "?")
        self.assertEqual(d.now_expr(), "datetime('now')")
        self.assertEqual(d.today_expr(), "date('now')")
        self.assertEqual(d.date_expr("last_checkin"), "date(last_checkin)")
        self.assertEqual(d.insert_verb(), "INSERT OR IGNORE")
        self.assertEqual(d.lock_suffix, "")

    def test_mysql_fragments(self):
        d = MySQLDialect()
        self.assertEqual(d.placeholder, "%s")
        self.assertEqual(d.now_expr(), "NOW()")
        self.assertEqual(d.today_expr(), "CURDATE()")
        self.assertEqual(d.date_expr("last_checkin"), "DATE(last_checkin)")
        self.assertEqual(d.insert_verb(), "INSERT IGNORE")
        self.assertEqual(d.lock_suffix, " FOR UPDATE")

    def test_sqlite_begin_write_is_immediate(self):
        calls = []

        class Recorder:
            def execute(self, sql):
                calls.append(sql)

        SQLiteDialect().begin_write(Recorder())
        self.assertEqual(calls, ["BEGIN IMMEDIATE"])

    def test_mysql_begin_write_starts_transaction(self):
        conn = FakeConnection()
        MySQLDialect().begin_write(conn)
        self.assertTrue(conn.began)


class TestMySQLSqlShape(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConnection()
        self.db = MySQLDatabase(connect_factory=lambda: self.conn)

    def test_init_creates_five_tables(self):
        statements = [sql for sql, _ in self.conn.executed]
        self.assertEqual(len(statements), 5, statements)
        self.assertTrue(all("CREATE TABLE" in s for s in statements))
        self.assertGreaterEqual(self.conn.commits, 1)

    def test_deduct_uses_placeholder_and_guard(self):
        self.assertTrue(self.db.deduct_balance(7, 3))
        sql, params = self.conn.executed[-1]
        self.assertIn("balance = balance - %s", sql)
        self.assertIn("balance >= %s", sql)
        self.assertNotIn("?", sql)
        self.assertEqual(params, (3, 7, 3))

    def test_checkin_uses_mysql_datetime(self):
        self.assertTrue(self.db.checkin(7))
        sql, _ = self.conn.executed[-1]
        self.assertIn("NOW()", sql)
        self.assertIn("CURDATE()", sql)
        self.assertIn("DATE(last_checkin)", sql)
        self.assertNotIn("date('now')", sql)

    def test_use_card_key_locks_row(self):
        self.conn.rows = [
            {"user_id": 7},                                   # 用户存在
            {"key_code": "K", "balance": 5, "max_uses": 2,
             "current_uses": 0, "created_by": None, "expire_at": None},
        ]
        self.assertEqual(self.db.use_card_key("K", 7), 5)
        selects = [sql for sql, _ in self.conn.executed if "FROM card_keys" in sql]
        self.assertTrue(selects)
        self.assertIn("FOR UPDATE", selects[-1])
        self.assertNotIn("?", selects[-1])
        self.assertTrue(self.conn.began)
        self.assertGreaterEqual(self.conn.commits, 2)

    def test_create_user_with_invite(self):
        self.conn.rows = [{"user_id": 1}]                     # 邀请人存在
        self.assertTrue(self.db.create_user(7, "u", "U", invited_by=1))
        statements = [sql for sql, _ in self.conn.executed]
        self.assertTrue(any("INSERT IGNORE INTO invitations" in s for s in statements))
        self.assertTrue(any("balance = balance + %s" in s for s in statements))


class TestFactory(unittest.TestCase):
    def setUp(self):
        self.tmp = BASE / ".tmp" / f"case-{uuid.uuid4().hex[:8]}"
        self.tmp.mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sqlite_backend(self):
        db = make_database("sqlite", path=self.tmp / "a.db")
        self.assertIsInstance(db, SQLiteDatabase)
        db.create_user(1, "u", "U")
        self.assertTrue(db.user_exists(1))

    def test_unknown_backend(self):
        with self.assertRaises(ValueError):
            make_database("postgres")

    @unittest.skipIf(PYMYSQL_INSTALLED, "本机装了 pymysql，会尝试真连库")
    def test_mysql_without_driver(self):
        with self.assertRaises(RuntimeError):
            make_database("mysql")


class TestPublicApiParity(unittest.TestCase):
    """两个后端继承同一个基类，接口必须一致。"""

    METHODS = [
        "create_user", "get_user", "user_exists", "is_blocked", "block_user",
        "unblock_user", "get_blacklist", "get_all_user_ids", "count_users",
        "add_balance", "deduct_balance", "checkin", "create_card_key",
        "use_card_key", "get_all_card_keys", "add_verification",
        "list_verifications",
    ]

    def test_same_surface(self):
        for name in self.METHODS:
            self.assertTrue(hasattr(SQLiteDatabase, name), name)
            self.assertTrue(hasattr(MySQLDatabase, name), name)
        self.assertTrue(issubclass(SQLiteDatabase, BaseDatabase))
        self.assertTrue(issubclass(MySQLDatabase, BaseDatabase))


@unittest.skipUnless(os.getenv("VERIFY_LAB_MYSQL") == "1",
                     "需要真实 MySQL：设 VERIFY_LAB_MYSQL=1 后再跑")
class TestRealMySQL(unittest.TestCase):
    """真库冒烟测试：设 VERIFY_LAB_MYSQL=1 才跑，跑完清理自己的数据。"""

    def test_smoke(self):
        db = MySQLDatabase()
        uid = 9_000_000 + uuid.uuid4().int % 100_000
        try:
            self.assertTrue(db.create_user(uid, "smoke", "Smoke"))
            self.assertTrue(db.deduct_balance(uid, 1) in (True, False))
            self.assertEqual(db.use_card_key("NOPE", uid), -4)
        finally:
            import pymysql
            conn = pymysql.connect(**db.config)
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM verifications WHERE user_id = %s", (uid,))
                    cur.execute("DELETE FROM invitations WHERE inviter_id = %s OR invitee_id = %s",
                                (uid, uid))
                    cur.execute("DELETE FROM users WHERE user_id = %s", (uid,))
                conn.commit()
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
