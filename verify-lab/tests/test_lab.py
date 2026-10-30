"""verify-lab 测试套件（标准库 unittest，无需 pytest）

    python -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import admin, db as db_module                       # noqa: E402
from app.db import Database                                  # noqa: E402
from app.mock_verifier import GatewayError, MockReviewGateway  # noqa: E402
from app.render import render_certificate                    # noqa: E402

ADMIN_ID = 9000


class LabTestCase(unittest.TestCase):
    """每个测试一个独立的临时数据库，互不污染。"""

    def setUp(self) -> None:
        # 注意：这里刻意不用 tempfile.TemporaryDirectory —— 在 Windows 沙箱下
        # 它创建的目录连本进程都写不进去（mkdtemp 的权限位问题），
        # 所以改成自己在工作区里建唯一目录。
        self.tmp = BASE / ".tmp" / f"case-{uuid.uuid4().hex[:8]}"
        self.tmp.mkdir(parents=True)
        self.db = Database(self.tmp / "test.db")
        self.gateway = MockReviewGateway(self.tmp / "evidence")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- 用户 / 积分 ----------

    def test_register_and_invite_reward(self):
        self.assertTrue(self.db.create_user(1, "alice", "Alice"))
        self.assertTrue(self.db.create_user(2, "bob", "Bob", invited_by=1))
        self.assertEqual(self.db.get_user(1)["balance"], 1 + db_module.INVITE_REWARD)
        self.assertEqual(self.db.get_user(2)["balance"], db_module.REGISTER_REWARD)
        self.assertFalse(self.db.create_user(1, "alice", "Alice"))   # 重复注册

    def test_checkin_only_once_per_day(self):
        self.db.create_user(1, "a", "A")
        before = self.db.get_user(1)["balance"]
        self.assertTrue(self.db.checkin(1))
        self.assertFalse(self.db.checkin(1))
        self.assertEqual(self.db.get_user(1)["balance"], before + db_module.CHECKIN_REWARD)

    def test_deduct_insufficient_balance(self):
        self.db.create_user(1, "a", "A")
        self.assertFalse(self.db.deduct_balance(1, 999))
        self.assertEqual(self.db.get_user(1)["balance"], db_module.REGISTER_REWARD)

    # ---------- 卡密状态机 ----------

    def test_card_key_states(self):
        self.db.create_user(1, "a", "A")
        self.db.create_user(2, "b", "B")
        self.db.create_user(3, "c", "C")
        self.db.create_card_key("K1", balance=5, max_uses=2)

        self.assertEqual(self.db.use_card_key("K1", 1), 5)      # 正常
        self.assertEqual(self.db.use_card_key("K1", 1), -3)     # 同一人重复
        self.assertEqual(self.db.use_card_key("K1", 2), 5)      # 第二人，次数用满
        self.assertEqual(self.db.use_card_key("K1", 3), -1)     # 次数已满
        self.assertEqual(self.db.use_card_key("NOPE", 1), -4)   # 卡密不存在
        self.assertEqual(self.db.use_card_key("K1", 999), -5)   # 用户不存在

    def test_expired_card_key(self):
        self.db.create_user(1, "a", "A")
        self.db.create_card_key("OLD", balance=5, expire_days=-1)
        self.assertEqual(self.db.use_card_key("OLD", 1), -2)

    # ---------- 管理员：鉴权与业务分离 ----------

    def test_admin_permission_denied(self):
        self.db.create_user(1, "a", "A")
        self.assertEqual(admin.genkey(self.db, 1, ADMIN_ID, ["K", "10"]), admin.ADMIN_ONLY)
        self.assertEqual(admin.add_balance(self.db, 1, ADMIN_ID, ["1", "10"]), admin.ADMIN_ONLY)

    def test_admin_add_balance(self):
        self.db.create_user(1, "a", "A")
        msg = admin.add_balance(self.db, ADMIN_ID, ADMIN_ID, ["1", "10"])
        self.assertIn("10", msg)
        self.assertEqual(self.db.get_user(1)["balance"], 11)

    def test_admin_add_balance_bounds(self):
        self.db.create_user(1, "a", "A")
        self.assertIn("不能为 0", admin.add_balance(self.db, ADMIN_ID, ADMIN_ID, ["1", "0"]))
        self.assertIn("不能超过", admin.add_balance(self.db, ADMIN_ID, ADMIN_ID, ["1", "1000001"]))
        self.assertIn("不能超过", admin.add_balance(self.db, ADMIN_ID, ADMIN_ID, ["1", "-1000001"]))
        self.assertEqual(self.db.get_user(1)["balance"], 1)

    def test_admin_genkey_validation(self):
        self.assertIn("大于 0", admin.genkey(self.db, ADMIN_ID, ADMIN_ID, ["K", "0"]))
        self.assertIn("整数", admin.genkey(self.db, ADMIN_ID, ADMIN_ID, ["K", "abc"]))
        self.assertIn("已生成", admin.genkey(self.db, ADMIN_ID, ADMIN_ID, ["K", "10", "3", "7"]))
        self.assertIn("已存在", admin.genkey(self.db, ADMIN_ID, ADMIN_ID, ["K", "10"]))

    def test_admin_genkey_bounds(self):
        self.assertIn("不能超过", admin.genkey(self.db, ADMIN_ID, ADMIN_ID, ["K", "1000001"]))
        self.assertIn("不能超过", admin.genkey(self.db, ADMIN_ID, ADMIN_ID, ["K", "10", "1000001"]))
        self.assertIn("1-3650", admin.genkey(self.db, ADMIN_ID, ADMIN_ID, ["K", "10", "1", "0"]))
        self.assertIn("1-3650", admin.genkey(self.db, ADMIN_ID, ADMIN_ID, ["K", "10", "1", "3651"]))
        self.assertIn("1-100", admin.genkey(self.db, ADMIN_ID, ADMIN_ID, ["X" * 101, "10"]))
        self.assertIn("1-100", admin.genkey(self.db, ADMIN_ID, ADMIN_ID, ["", "10"]))
        self.assertEqual(
            [c for c in self.db.get_all_card_keys() if c["key_code"] == "K"], []
        )

    def test_admin_genkey_permanent(self):
        self.assertIn("永久有效", admin.genkey(self.db, ADMIN_ID, ADMIN_ID, ["FOREVER", "10"]))
        cards = [c for c in self.db.get_all_card_keys() if c["key_code"] == "FOREVER"]
        self.assertEqual(len(cards), 1)
        self.assertIsNone(cards[0]["expire_at"])

    def test_admin_block_blacklist_unblock(self):
        self.db.create_user(1, "a", "A")
        self.assertIn("已拉黑", admin.block(self.db, ADMIN_ID, ADMIN_ID, ["1"]))
        self.assertIn("用户 1", admin.blacklist(self.db, ADMIN_ID, ADMIN_ID, []))
        self.assertIn("移出", admin.unblock(self.db, ADMIN_ID, ADMIN_ID, ["1"]))
        self.assertEqual(admin.blacklist(self.db, ADMIN_ID, ADMIN_ID, []), "黑名单为空。")

    def test_admin_unknown_user(self):
        self.assertIn("不存在", admin.block(self.db, ADMIN_ID, ADMIN_ID, ["42"]))
        self.assertIn("用法", admin.block(self.db, ADMIN_ID, ADMIN_ID, []))

    def test_broadcast_targets(self):
        for uid in (1, 2, 3):
            self.db.create_user(uid, f"u{uid}", f"U{uid}")
        ids, msg = admin.broadcast_targets(self.db, ADMIN_ID, ADMIN_ID, "hi")
        self.assertEqual(ids, [1, 2, 3])
        self.assertIn("3", msg)
        ids, msg = admin.broadcast_targets(self.db, 1, ADMIN_ID, "hi")
        self.assertEqual(ids, [])
        self.assertEqual(msg, admin.ADMIN_ONLY)
        ids, msg = admin.broadcast_targets(self.db, ADMIN_ID, ADMIN_ID, "  ")
        self.assertEqual(ids, [])
        ids, msg = admin.broadcast_targets(self.db, ADMIN_ID, ADMIN_ID, "x" * 4001)
        self.assertEqual(ids, [])
        self.assertIn("太长", msg)
        ids, msg = admin.broadcast_targets(self.db, ADMIN_ID, ADMIN_ID, "x" * 4000)
        self.assertEqual(ids, [1, 2, 3])

    # ---------- 模拟审核状态机 ----------

    def test_gateway_happy_path(self):
        self.db.create_user(1, "a", "A")
        vid = self.gateway.create(1)
        self.assertEqual(
            self.gateway.collect_applicant_info(vid, full_name="A", course="C"),
            "uploadDocument",
        )
        up = self.gateway.request_upload(vid, "cert.png", 1024)
        self.gateway.put_object(up["uploadUrl"], b"fake-png-bytes")
        self.assertEqual(self.gateway.complete_upload(vid), "review")
        result = self.gateway.poll(vid, timeout=3, interval=0.05)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["rewardCode"].startswith("REWARD-"))

    def test_gateway_validation_and_size_limit(self):
        vid = self.gateway.create(1)
        with self.assertRaises(GatewayError):
            self.gateway.collect_applicant_info(vid, full_name="", course="")
        vid2 = self.gateway.create(1)
        self.gateway.collect_applicant_info(vid2, full_name="A", course="C")
        with self.assertRaises(GatewayError):
            self.gateway.request_upload(vid2, "big.png", 3 * 1024 * 1024)
        with self.assertRaises(GatewayError):
            self.gateway.complete_upload(vid2)          # 还没上传就提交

    def test_failure_refunds_balance(self):
        """失败路径的完整约定：扣分 → 出错 → 退分 → 记账。"""
        self.db.create_user(1, "a", "A")
        self.assertTrue(self.db.deduct_balance(1, db_module.VERIFY_COST))
        try:
            vid = self.gateway.create(1)
            self.gateway.collect_applicant_info(vid, full_name="", course="")
        except GatewayError as exc:
            self.db.add_balance(1, db_module.VERIFY_COST)
            self.db.add_verification(1, "certificate", "failed", str(exc))
        self.assertEqual(self.db.get_user(1)["balance"], db_module.REGISTER_REWARD)
        self.assertEqual(self.db.list_verifications(1)[0]["status"], "failed")

    # ---------- 渲染 ----------

    def test_render_certificate(self):
        png = render_certificate("Test User", "Python 课", 10, 90, "T-001",
                                 out_dir=self.tmp / "out", backend="pillow")
        self.assertTrue(png.exists())
        self.assertEqual(png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertTrue((self.tmp / "out" / "T-001.html").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
