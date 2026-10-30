"""数据层公共实现 —— 业务逻辑只写一遍，数据库差异交给 Dialect

对照原来的 database_mysql.py：SQL 和 pymysql 调用混在一起，
想换数据库就得复制整个文件、再把每个 `?` 改成 `%s`、把 datetime('now')
改成 NOW()、把 BEGIN IMMEDIATE 改成 START TRANSACTION + FOR UPDATE。

现在：SQL 模板里只有 `{p}` 占位符和几个方言片段，子类只负责"怎么连库"。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from .dialect import Dialect
from .settings import CHECKIN_REWARD, INVITE_REWARD, REGISTER_REWARD

logger = logging.getLogger(__name__)


class BaseDatabase:
    dialect: Dialect

    def __init__(self) -> None:
        self.init_database()

    # ---------------- 子类必须实现 ----------------
    def init_database(self) -> None:
        raise NotImplementedError

    def _connect(self):
        """返回上下文管理器，yield 一个 DB-API 连接。"""
        raise NotImplementedError

    # ---------------- 内部小工具 ----------------
    @property
    def p(self) -> str:
        return self.dialect.placeholder

    def _rollback_quietly(self, conn) -> None:
        try:
            self.dialect.rollback(conn)
        except Exception:                      # 事务可能已经回滚过
            pass

    @staticmethod
    def _normalize_row(row: Optional[dict]) -> Optional[dict]:
        """把 MySQL 的 datetime 统一成 ISO 字符串。

        SQLite 存的是文本，pymysql 返回的是 datetime 对象；不归一化的话，
        `row["expire_at"][:10]`、`fromisoformat(row["created_at"])` 这类按文本
        写的代码在 SQLite 上能跑、换 MySQL 就炸。
        """
        if row is None:
            return None
        for field, value in row.items():
            if isinstance(value, datetime):
                row[field] = value.isoformat()
        return row

    def _one(self, conn, sql: str, params: tuple = ()) -> Optional[dict]:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        return self._normalize_row(self.dialect.row_to_dict(row)) if row is not None else None

    def _all(self, conn, sql: str, params: tuple = ()) -> list[dict]:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [self._normalize_row(self.dialect.row_to_dict(r)) for r in cur.fetchall()]

    # ---------------- 用户 ----------------
    def create_user(self, user_id: int, username: str, full_name: str,
                    invited_by: Optional[int] = None) -> bool:
        p = self.p
        with self._connect() as conn:
            cur = conn.cursor()
            self.dialect.begin_write(conn)
            try:
                cur.execute(
                    f"INSERT INTO users (user_id, username, full_name, invited_by)"
                    f" VALUES ({p},{p},{p},{p})",
                    (user_id, username, full_name, invited_by),
                )
                if invited_by and self._one(
                    conn, f"SELECT user_id FROM users WHERE user_id = {p}", (invited_by,)
                ):
                    cur.execute(
                        f"UPDATE users SET balance = balance + {p} WHERE user_id = {p}",
                        (INVITE_REWARD, invited_by),
                    )
                    cur.execute(
                        f"{self.dialect.insert_verb()} INTO invitations"
                        f" (inviter_id, invitee_id) VALUES ({p},{p})",
                        (invited_by, user_id),
                    )
                self.dialect.commit(conn)
                return True
            except Exception as exc:
                self._rollback_quietly(conn)
                if self.dialect.is_integrity_error(exc):
                    return False
                logger.exception("create_user failed")
                raise

    def get_user(self, user_id: int) -> Optional[dict]:
        with self._connect() as conn:
            return self._one(conn, f"SELECT * FROM users WHERE user_id = {self.p}", (user_id,))

    def user_exists(self, user_id: int) -> bool:
        with self._connect() as conn:
            return self._one(
                conn, f"SELECT user_id FROM users WHERE user_id = {self.p}", (user_id,)
            ) is not None

    def is_blocked(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        return bool(user and user["is_blocked"])

    def block_user(self, user_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE users SET is_blocked = 1 WHERE user_id = {self.p}", (user_id,)
            )
            self.dialect.commit(conn)
            return cur.rowcount > 0

    def unblock_user(self, user_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE users SET is_blocked = 0 WHERE user_id = {self.p}", (user_id,)
            )
            self.dialect.commit(conn)
            return cur.rowcount > 0

    def get_blacklist(self) -> list[dict]:
        with self._connect() as conn:
            return self._all(conn, "SELECT * FROM users WHERE is_blocked = 1 ORDER BY user_id")

    def get_all_user_ids(self) -> list[int]:
        with self._connect() as conn:
            rows = self._all(conn, "SELECT user_id FROM users ORDER BY user_id")
        return [r["user_id"] for r in rows]

    def count_users(self) -> int:
        with self._connect() as conn:
            return int(self._one(conn, "SELECT COUNT(*) AS n FROM users")["n"])

    def count_verifications(self) -> int:
        with self._connect() as conn:
            return int(self._one(conn, "SELECT COUNT(*) AS n FROM verifications")["n"])

    # ---------------- 积分 ----------------
    def add_balance(self, user_id: int, amount: int) -> bool:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE users SET balance = balance + {self.p} WHERE user_id = {self.p}",
                (amount, user_id),
            )
            self.dialect.commit(conn)
            return cur.rowcount > 0

    def deduct_balance(self, user_id: int, amount: int) -> bool:
        """原子扣分：余额判断写进 WHERE，靠 rowcount 判断成败。"""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE users SET balance = balance - {self.p}"
                f" WHERE user_id = {self.p} AND balance >= {self.p}",
                (amount, user_id, amount),
            )
            self.dialect.commit(conn)
            return cur.rowcount > 0

    def checkin(self, user_id: int) -> bool:
        """原子签到：今天没签过才 +1。"""
        d = self.dialect
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                UPDATE users
                   SET balance = balance + {self.p}, last_checkin = {d.now_expr()}
                 WHERE user_id = {self.p}
                   AND (last_checkin IS NULL
                        OR {d.date_expr('last_checkin')} < {d.today_expr()})
                """,
                (CHECKIN_REWARD, user_id),
            )
            self.dialect.commit(conn)
            return cur.rowcount > 0

    # ---------------- 卡密 ----------------
    def create_card_key(self, key_code: str, balance: int, created_by: Optional[int] = None,
                        max_uses: int = 1, expire_days: Optional[int] = None) -> bool:
        expire_at = None
        if expire_days:
            expire_at = (datetime.now() + timedelta(days=expire_days)).strftime("%Y-%m-%d %H:%M:%S")
        p = self.p
        with self._connect() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"INSERT INTO card_keys (key_code, balance, max_uses, created_by, expire_at)"
                    f" VALUES ({p},{p},{p},{p},{p})",
                    (key_code, balance, max_uses, created_by, expire_at),
                )
                self.dialect.commit(conn)
                return True
            except Exception as exc:
                self._rollback_quietly(conn)
                if self.dialect.is_integrity_error(exc):
                    return False
                raise

    def use_card_key(self, key_code: str, user_id: int) -> int:
        """返回积分；-1 次数满 / -2 过期 / -3 本人已用 / -4 卡密不存在 / -5 用户不存在。"""
        p = self.p
        with self._connect() as conn:
            cur = conn.cursor()
            self.dialect.begin_write(conn)          # 拿写锁 / 开事务
            try:
                if self._one(
                    conn, f"SELECT user_id FROM users WHERE user_id = {p}", (user_id,)
                ) is None:
                    self._rollback_quietly(conn)
                    return -5

                card = self._one(
                    conn,
                    f"SELECT * FROM card_keys WHERE key_code = {p}{self.dialect.lock_suffix}",
                    (key_code,),
                )
                if card is None:
                    self._rollback_quietly(conn)
                    return -4
                if card["expire_at"] and datetime.now() > self.dialect.parse_dt(card["expire_at"]):
                    self._rollback_quietly(conn)
                    return -2
                if card["current_uses"] >= card["max_uses"]:
                    self._rollback_quietly(conn)
                    return -1

                # 联合主键冲突 = 该用户已用过这张卡
                try:
                    cur.execute(
                        f"INSERT INTO card_key_usage (key_code, user_id) VALUES ({p},{p})",
                        (key_code, user_id),
                    )
                except Exception as exc:
                    if self.dialect.is_integrity_error(exc):
                        self._rollback_quietly(conn)
                        return -3
                    raise

                cur.execute(
                    f"UPDATE card_keys SET current_uses = current_uses + 1 WHERE key_code = {p}",
                    (key_code,),
                )
                cur.execute(
                    f"UPDATE users SET balance = balance + {p} WHERE user_id = {p}",
                    (card["balance"], user_id),
                )
                self.dialect.commit(conn)
                return int(card["balance"])
            except Exception:
                self._rollback_quietly(conn)
                raise

    def get_all_card_keys(self) -> list[dict]:
        with self._connect() as conn:
            return self._all(conn, "SELECT * FROM card_keys ORDER BY key_code")

    # ---------------- 认证记录 ----------------
    def add_verification(self, user_id: int, kind: str, status: str, detail: str = "") -> int:
        p = self.p
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO verifications (user_id, kind, status, detail)"
                f" VALUES ({p},{p},{p},{p})",
                (user_id, kind, status, detail),
            )
            self.dialect.commit(conn)
            return int(cur.lastrowid)

    def list_verifications(self, user_id: int) -> list[dict]:
        with self._connect() as conn:
            return self._all(
                conn,
                f"SELECT * FROM verifications WHERE user_id = {self.p} ORDER BY id DESC",
                (user_id,),
            )
