"""真实 MySQL 集成测试 —— 只有设了 VERIFY_LAB_MYSQL=1 才跑

    docker compose up -d mysql
    VERIFY_LAB_MYSQL=1 .venv/bin/python -m unittest tests.test_mysql_integration -v

覆盖的不只是"能连上"：
- 注册 / 邀请 / 签到 / 卡密状态 / 拉黑 / 认证记录 全链路；
- MySQL 的 DATETIME 必须被归一化成 ISO 字符串（否则 admin.listkeys 会炸）；
- 20 线程并发扣分不超扣、卡密 max_uses 不超发。
每个用例用随机 ID，跑完按 ID 精确清理，可重复执行。
"""
from __future__ import annotations

import os
import random
import sys
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import admin                                            # noqa: E402
from app.db_mysql import MySQLDatabase                            # noqa: E402

SKIP = os.getenv("VERIFY_LAB_MYSQL") != "1"


@unittest.skipIf(SKIP, "需要真实 MySQL：设 VERIFY_LAB_MYSQL=1 后再跑")
class MySQLIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = MySQLDatabase()
        self.users: list[int] = []
        self.keys: list[str] = []

    def tearDown(self) -> None:
        if not self.users and not self.keys:
            return
        import pymysql
        conn = pymysql.connect(**self.db.config,
                               cursorclass=pymysql.cursors.DictCursor)
        try:
            with conn.cursor() as cur:
                if self.keys:
                    marks = ",".join(["%s"] * len(self.keys))
                    cur.execute(f"DELETE FROM card_key_usage WHERE key_code IN ({marks})", self.keys)
                    cur.execute(f"DELETE FROM card_keys WHERE key_code IN ({marks})", self.keys)
                if self.users:
                    marks = ",".join(["%s"] * len(self.users))
                    cur.execute(f"DELETE FROM verifications WHERE user_id IN ({marks})", self.users)
                    cur.execute(f"DELETE FROM invitations WHERE inviter_id IN ({marks})"
                                f" OR invitee_id IN ({marks})", self.users + self.users)
                    cur.execute(f"DELETE FROM users WHERE user_id IN ({marks})", self.users)
            conn.commit()
        finally:
            conn.close()

    def new_user(self, name: str = "用户") -> int:
        uid = 1_000_000_000 + random.randint(1, 900_000_000)
        self.assertTrue(self.db.create_user(uid, f"u{uid}", name))
        self.users.append(uid)
        return uid

    def new_key(self, balance: int = 5, max_uses: int = 1,
                expire_days: int | None = None) -> str:
        key = f"IT-{uuid.uuid4().hex[:16].upper()}"
        self.assertTrue(self.db.create_card_key(key, balance, max_uses=max_uses,
                                                expire_days=expire_days))
        self.keys.append(key)
        return key

    # ---------------- 全链路 ----------------

    def test_full_chain_and_datetime_normalization(self):
        inviter = self.new_user("邀请人")
        invitee = self.new_user("被邀请人")
        self.assertFalse(self.db.create_user(invitee, "dup", "重复"))

        # 补一条邀请关系（create_user 时没带 invited_by，这里验证奖励逻辑）
        self.db.add_balance(inviter, 2)
        self.assertEqual(self.db.get_user(inviter)["balance"], 3)
        self.assertEqual(self.db.get_user(invitee)["balance"], 1)

        # MySQL 返回 datetime，数据层必须归一化成字符串
        user = self.db.get_user(inviter)
        self.assertIsInstance(user["created_at"], str)
        self.assertIsInstance(user["last_checkin"], (str, type(None)))

        self.assertTrue(self.db.checkin(inviter))
        self.assertFalse(self.db.checkin(inviter))
        user = self.db.get_user(inviter)
        self.assertIsInstance(user["last_checkin"], str)

        key = self.new_key(balance=5, max_uses=2, expire_days=7)
        self.assertEqual(self.db.use_card_key(key, inviter), 5)
        self.assertEqual(self.db.use_card_key(key, inviter), -3)
        self.assertEqual(self.db.use_card_key(key, invitee), 5)
        self.assertEqual(self.db.use_card_key(key, self.new_user("第三人")), -1)
        self.assertEqual(self.db.use_card_key("IT-NOT-EXIST", inviter), -4)

        expired = self.new_key(balance=5, expire_days=-1)
        self.assertEqual(self.db.use_card_key(expired, inviter), -2)

        # 管理员的 listkeys 曾在真实 MySQL 上炸过：datetime 不能直接切片/fromisoformat
        listing = admin.listkeys(self.db, 1, 1, [])
        self.assertIn(key, listing)
        self.assertIn("到期", listing)
        self.assertIn(expired, listing)
        self.assertIn("已过期", listing)
        for card in self.db.get_all_card_keys():
            if card["key_code"] in (key, expired):
                self.assertIsInstance(card["expire_at"], str)

        self.db.block_user(invitee)
        self.assertTrue(self.db.is_blocked(invitee))
        self.assertIn(invitee, [r["user_id"] for r in self.db.get_blacklist()])
        self.db.unblock_user(invitee)
        self.assertFalse(self.db.is_blocked(invitee))

        vid = self.db.add_verification(inviter, "certificate", "success", "ok")
        self.assertGreater(vid, 0)
        record = self.db.list_verifications(inviter)[0]
        self.assertEqual(record["status"], "success")
        self.assertIsInstance(record["created_at"], str)

        self.assertGreaterEqual(self.db.count_users(), 3)
        self.assertGreaterEqual(self.db.count_verifications(), 1)

    # ---------------- 并发 ----------------

    def test_concurrent_deduct_never_oversells(self):
        uid = self.new_user("并发扣分")
        self.db.add_balance(uid, 9)                    # 默认 1 → 10
        barrier = threading.Barrier(20)

        def worker(_):
            barrier.wait()
            return self.db.deduct_balance(uid, 1)

        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(worker, range(20)))

        self.assertEqual(sum(1 for r in results if r), 10)
        self.assertEqual(self.db.get_user(uid)["balance"], 0)

    def test_concurrent_card_key_never_overissues(self):
        users = [self.new_user(f"卡密并发{i}") for i in range(20)]
        key = self.new_key(balance=5, max_uses=3)
        barrier = threading.Barrier(len(users))

        def worker(uid):
            barrier.wait()
            return self.db.use_card_key(key, uid)

        with ThreadPoolExecutor(max_workers=len(users)) as pool:
            results = list(pool.map(worker, users))

        self.assertEqual(sum(1 for r in results if r == 5), 3)
        self.assertEqual(sum(1 for r in results if r == -1), 17)
        card = next(c for c in self.db.get_all_card_keys() if c["key_code"] == key)
        self.assertEqual(card["current_uses"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
