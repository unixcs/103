"""全栈真实性测试：真实 PTB 调度 + 真实 MySQL + 真实 PNG 渲染

链路：
    /start /qd /genkey /redeem /verify
      → python-telegram-bot 发 HTTP 请求
      → 本地 Bot API 仿真（不打真实 Telegram）
      → MySQL 8.0（真实事务、真实 DATETIME）
      → Pillow 渲染 PNG
      → sendDocument 把证书传回"用户"

审核网关仍是 app/mock_verifier.py 的本地状态机：不联网、不提交身份材料。
"""
from __future__ import annotations

import asyncio
import os
import random
import shutil
import sys
import unittest
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.bot_service import BotConfig, build_application          # noqa: E402
from app.db_mysql import MySQLDatabase                            # noqa: E402
from app.mock_verifier import MockReviewGateway                   # noqa: E402
from tests.fake_telegram_api import FakeTelegramAPI               # noqa: E402

ADMIN_ID = 9000
TOKEN = "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

try:
    import telegram  # noqa: F401
    PTB_INSTALLED = True
except ImportError:
    PTB_INSTALLED = False


@unittest.skipUnless(os.getenv("VERIFY_LAB_MYSQL") == "1",
                     "需要真实 MySQL：设 VERIFY_LAB_MYSQL=1 后再跑")
@unittest.skipUnless(PTB_INSTALLED, "需要 python-telegram-bot：pip install 'python-telegram-bot>=21'")
class BotMySQLFullStackTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = BASE / ".tmp" / f"bot-mysql-{uuid.uuid4().hex[:8]}"
        self.tmp.mkdir(parents=True)
        self.db = MySQLDatabase()
        self.uid = 1_000_000_000 + random.randint(1, 900_000_000)
        self.key = f"E2E-{uuid.uuid4().hex[:12].upper()}"
        self.api = FakeTelegramAPI().start()
        cfg = BotConfig(
            token=TOKEN,
            admin_id=ADMIN_ID,
            database=self.db,
            gateway=MockReviewGateway(self.tmp / "evidence"),
            outputs_dir=self.tmp / "outputs",
            render_backend="pillow",
            concurrent_updates=8,
            base_url=self.api.base_url,
            poll_interval=0.05,
        )
        self.app = build_application(cfg)
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(poll_interval=0.05)
        for _ in range(100):
            if any(r["method"] == "getUpdates" for r in self.api.requests):
                break
            await asyncio.sleep(0.05)

    async def asyncTearDown(self) -> None:
        try:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
        finally:
            self.api.stop()
            import pymysql
            conn = pymysql.connect(**self.db.config)
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM card_key_usage WHERE key_code = %s", (self.key,))
                    cur.execute("DELETE FROM card_keys WHERE key_code = %s", (self.key,))
                    cur.execute("DELETE FROM verifications WHERE user_id = %s", (self.uid,))
                    cur.execute("DELETE FROM users WHERE user_id = %s", (self.uid,))
                conn.commit()
            finally:
                conn.close()
            shutil.rmtree(self.tmp, ignore_errors=True)

    async def wait_message(self, contains: str, timeout: float = 10.0) -> dict:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            for message in self.api.messages:
                if message["chat_id"] == self.uid and contains in message["text"]:
                    return message
            await asyncio.sleep(0.05)
        self.fail(f"等不到包含 {contains!r} 的消息：{self.api.messages!r}")

    async def send(self, user_id: int, text: str, expect: str) -> None:
        self.api.clear()
        self.api.inject_message(user_id, text)
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            for message in self.api.messages:
                if message["chat_id"] == user_id and expect in message["text"]:
                    return
            await asyncio.sleep(0.05)
        self.fail(f"{text!r} 没有得到 {expect!r}：{self.api.messages!r}")

    async def wait_document(self, timeout: float = 15.0) -> dict:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            for document in self.api.documents:
                if document["chat_id"] == self.uid:
                    return document
            await asyncio.sleep(0.05)
        self.fail(f"等不到证书：{self.api.messages!r}")

    async def test_full_chain_on_real_mysql(self):
        await self.send(self.uid, "/start", "注册成功")
        await self.send(self.uid, "/qd", "签到成功")
        await self.send(ADMIN_ID, f"/genkey {self.key} 5 2 7", "已生成卡密")
        await self.send(self.uid, f"/redeem {self.key}", "兑换成功，到账 5")
        await self.send(ADMIN_ID, "/listkeys", self.key)

        self.api.clear()
        self.api.inject_message(self.uid, "/verify 真实 MySQL 全栈测试")
        document = await self.wait_document()
        self.assertIn("教学示例", document["caption"])
        self.assertGreater(document["size"], 10_000)
        self.assertTrue(document["data"].startswith(b"\x89PNG\r\n\x1a\n"))

        user = self.db.get_user(self.uid)
        self.assertEqual(user["balance"], 6)          # 1 + 1 + 5 - 1
        self.assertIsInstance(user["created_at"], str)
        self.assertIsInstance(user["last_checkin"], str)
        record = self.db.list_verifications(self.uid)[0]
        self.assertEqual(record["status"], "success")

        pngs = list((self.tmp / "outputs").glob("*.png"))
        self.assertEqual(len(pngs), 1)
        self.assertEqual(pngs[0].stat().st_size, document["size"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
