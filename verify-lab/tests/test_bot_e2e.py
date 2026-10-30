"""Bot 端到端测试：真实 python-telegram-bot 调度栈 + 本地 Bot API 仿真

不联网、不需要 BOT_TOKEN，但走的是真实的：
    HTTP 请求 → Update 反序列化 → CommandHandler → handler → sendMessage/sendDocument

覆盖：注册/邀请、签到、卡密全部状态、扣分、失败退款、黑名单、
管理员权限、广播、未知命令、证书图片发送。
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import unittest
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.bot_service import BotConfig, build_application          # noqa: E402
from app.db import SQLiteDatabase                                 # noqa: E402
from app.mock_verifier import GatewayError, MockReviewGateway     # noqa: E402
from tests.fake_telegram_api import FakeTelegramAPI               # noqa: E402

ADMIN_ID = 9000
TOKEN = "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

try:
    import telegram  # noqa: F401
    PTB_INSTALLED = True
except ImportError:
    PTB_INSTALLED = False


@unittest.skipUnless(PTB_INSTALLED, "需要 python-telegram-bot：pip install 'python-telegram-bot>=21'")
class BotE2ETest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = BASE / ".tmp" / f"bot-{uuid.uuid4().hex[:8]}"
        self.tmp.mkdir(parents=True)
        self.db = SQLiteDatabase(self.tmp / "bot.db")
        self.api = FakeTelegramAPI().start()
        self.cfg = BotConfig(
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
        self.app = build_application(self.cfg)
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(poll_interval=0.05)
        # 等 updater 真正开始 getUpdates，避免第一条消息在启动竞态里丢掉
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
            shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------------- 测试小工具 ----------------

    async def wait_message(self, chat_id: int, contains: str, timeout: float = 10.0) -> dict:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            for message in self.api.messages:
                if message["chat_id"] == chat_id and contains in message["text"]:
                    return message
            await asyncio.sleep(0.05)
        self.fail(
            f"等不到发给 {chat_id} 且包含 {contains!r} 的消息；"
            f"已发送={self.api.messages!r}"
        )

    async def send(self, user_id: int, text: str, expect: str | None = None,
                   timeout: float = 10.0) -> dict:
        self.api.clear()
        self.api.inject_message(user_id, text)
        if expect is None:
            await asyncio.sleep(0.4)
            return {}
        return await self.wait_message(user_id, expect, timeout)

    async def wait_document(self, chat_id: int, timeout: float = 15.0) -> dict:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            for document in self.api.documents:
                if document["chat_id"] == chat_id:
                    return document
            await asyncio.sleep(0.05)
        self.fail(f"等不到发给 {chat_id} 的证书文件；消息={self.api.messages!r}")

    # ---------------- 主链路 ----------------

    async def test_user_flow_end_to_end(self):
        uid = 10001
        await self.send(uid, "/start", "注册成功")
        await self.send(uid, "/balance", "当前积分：1")
        await self.send(uid, "/qd", "签到成功")
        await self.send(uid, "/qd", "今天已经签过了")

        await self.send(ADMIN_ID, "/genkey VIP-100 5 2 7", "已生成卡密")
        await self.send(ADMIN_ID, "/listkeys", "VIP-100")
        await self.send(uid, "/redeem VIP-100", "兑换成功，到账 5")
        await self.send(uid, "/redeem VIP-100", "已经使用过这张卡密")

        self.api.clear()
        self.api.inject_message(uid, "/verify Python 异步编程")
        document = await self.wait_document(uid)

        self.assertTrue(document["filename"].endswith(".png"))
        self.assertGreater(document["size"], 10_000)
        self.assertTrue(document["data"].startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn("教学示例", document["caption"])
        self.assertIn("不具备任何效力", document["caption"])
        await self.wait_message(uid, "审核通过")

        user = self.db.get_user(uid)
        self.assertEqual(user["balance"], 6)          # 1 注册 + 1 签到 + 5 卡密 - 1 认证
        records = self.db.list_verifications(uid)
        self.assertEqual(records[0]["status"], "success")

        pngs = list((self.tmp / "outputs").glob("*.png"))
        self.assertEqual(len(pngs), 1, pngs)
        self.assertEqual(pngs[0].stat().st_size, document["size"])

        await self.send(uid, "/help", "/verify")

    async def test_invite_reward(self):
        inviter, invitee = 11001, 11002
        await self.send(inviter, "/start", "注册成功")
        await self.send(invitee, f"/start {inviter}", "注册成功")
        self.assertEqual(self.db.get_user(inviter)["balance"], 3)   # 1 + 2 邀请奖励
        self.assertEqual(self.db.get_user(invitee)["balance"], 1)

    async def test_gateway_failure_refunds_and_records(self):
        uid = 12001
        await self.send(uid, "/start", "注册成功")

        def boom(vid, **kwargs):
            raise GatewayError("模拟审核失败")

        self.cfg.gateway.collect_applicant_info = boom
        await self.send(uid, "/verify 失败课程", "提交失败")
        await self.wait_message(uid, "已退回 1 积分")

        self.assertEqual(self.db.get_user(uid)["balance"], 1)
        records = self.db.list_verifications(uid)
        self.assertEqual(records[0]["status"], "failed")
        self.assertIn("模拟审核失败", records[0]["detail"])

    async def test_blocked_admin_permissions_and_stats(self):
        uid = 13001
        await self.send(uid, "/start", "注册成功")
        await self.send(uid, "/genkey HACK 5", "没有权限")

        await self.send(ADMIN_ID, f"/block {uid}", "已拉黑")
        await self.send(uid, "/balance", "已被拉黑")
        await self.send(ADMIN_ID, "/blacklist", str(uid))
        await self.send(ADMIN_ID, f"/white {uid}", "移出黑名单")
        await self.send(uid, "/balance", "当前积分：1")

        await self.send(ADMIN_ID, "/stats", "用户总数")
        await self.send(ADMIN_ID, "/addbalance 999999 5", "不存在")

    async def test_card_key_errors_and_insufficient_balance(self):
        uid, other = 14001, 14002
        await self.send(uid, "/start", "注册成功")
        await self.send(other, "/start", "注册成功")
        await self.send(uid, "/redeem NOPE", "卡密不存在")

        # 管理员命令现在拒绝 <=0 的天数，过期卡直接写库构造
        self.db.create_card_key("EXPIRED", 5, ADMIN_ID, 1, -1)
        await self.send(uid, "/redeem EXPIRED", "已过期")

        await self.send(ADMIN_ID, "/genkey FULL 5 1", "已生成卡密")
        await self.send(uid, "/redeem FULL", "兑换成功，到账 5")
        await self.send(other, "/redeem FULL", "使用次数已满")

        self.db.deduct_balance(uid, self.db.get_user(uid)["balance"])
        await self.send(uid, "/verify 余额不足课程", "积分不足")

        await self.send(uid, "/no_such_command", "未知命令")
        await self.send(uid, "你好", "/help")

    async def test_broadcast(self):
        first, second = 15001, 15002
        await self.send(first, "/start", "注册成功")
        await self.send(second, "/start", "注册成功")

        self.api.clear()
        self.api.inject_message(ADMIN_ID, "/broadcast 系统维护通知")
        await self.wait_message(ADMIN_ID, "广播完成：成功 2/2")
        texts = {(m["chat_id"], m["text"]) for m in self.api.messages}
        self.assertIn((first, "系统维护通知"), texts)
        self.assertIn((second, "系统维护通知"), texts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
