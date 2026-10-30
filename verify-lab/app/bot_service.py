"""Telegram Bot 完整接线层 —— 业务逻辑仍在 app/ 里，这里只做适配

设计边界和 app/admin.py 一样：
- 业务规则（积分、卡密、权限、记账）不写在这里；
- 这里只负责：取 Telegram 参数 → 调同步业务函数（走线程池）→ 回复；
- 所有网络/数据库/渲染都是真实调用，唯一"假"的是审核网关
  （app/mock_verifier.py，本地状态机，不联网、不提交任何身份材料）。

运行：
    cp .env.example .env      # 填 BOT_TOKEN 和 ADMIN_USER_ID
    python bot.py
自检（不发消息、不轮询）：
    python bot.py --check
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP_DIR = Path(__file__).resolve().parent
BASE = APP_DIR.parent
sys.path.insert(0, str(BASE))

from app import admin                                    # noqa: E402
from app.concurrency import registry                     # noqa: E402
from app.env import load_env                             # noqa: E402
from app.factory import make_database                    # noqa: E402
from app.mock_verifier import GatewayError, MockReviewGateway  # noqa: E402
from app.render import render_certificate                # noqa: E402
from app.settings import REGISTER_REWARD, VERIFY_COST    # noqa: E402

logger = logging.getLogger("verify-lab.bot")


class _RedactingFormatter(logging.Formatter):
    """httpx 会把 Bot Token 拼进 URL 打日志，任何日志输出前统一抹掉。"""

    def __init__(self, fmt: str, secret: str):
        super().__init__(fmt)
        self.secret = secret

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        return text.replace(self.secret, "***") if self.secret else text


def _configure_logging(secret: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_RedactingFormatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", secret
    ))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    # httpx 的 INFO 日志会打印完整请求 URL（含 Token），压到 WARNING。
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

try:
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
except ImportError:                       # 没装 PTB 时给出明确提示，而不是 ImportError 堆栈
    Update = object                         # type: ignore
    ContextTypes = object                   # type: ignore
    Application = None                      # type: ignore
    CommandHandler = MessageHandler = filters = None  # type: ignore


# ---------------- 配置 ----------------

@dataclass
class BotConfig:
    token: str
    admin_id: int
    database: object
    gateway: MockReviewGateway
    outputs_dir: Path
    render_backend: str = "auto"
    concurrent_updates: int = 32
    base_url: Optional[str] = None
    poll_interval: float = 0.0
    drop_pending: bool = True


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def build_config() -> BotConfig:
    outputs_dir = Path(os.getenv("OUTPUTS_DIR", str(BASE / "outputs")))
    return BotConfig(
        token=os.getenv("BOT_TOKEN", "").strip(),
        admin_id=_env_int("ADMIN_USER_ID", 0),
        database=make_database(),
        gateway=MockReviewGateway(outputs_dir / "evidence"),
        outputs_dir=outputs_dir,
        render_backend=os.getenv("RENDER_BACKEND", "auto").strip().lower(),
        concurrent_updates=_env_int("BOT_CONCURRENT", 32),
        base_url=os.getenv("TELEGRAM_BASE_URL", "").strip() or None,
        poll_interval=_env_float("BOT_POLL_INTERVAL", 0.0),
        drop_pending=os.getenv("BOT_DROP_PENDING", "1").strip() not in ("0", "false", "False"),
    )


# ---------------- 公共适配小工具 ----------------

def _uid(update) -> int:
    return update.effective_user.id


def _display_name(update) -> str:
    u = update.effective_user
    return (u.full_name or u.first_name or str(u.id)).strip()


TELEGRAM_TEXT_LIMIT = 4000


def _split_message(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Telegram 单条消息上限 4096；列表类命令（卡密/黑名单）可能超长。

    优先按换行切，避免把一行从中间劈开；单行超长时硬切。
    """
    if not text:
        return []
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


async def _reply(update, text: str) -> None:
    if update is not None and update.effective_message is not None:
        for chunk in _split_message(text):
            await update.effective_message.reply_text(chunk)


async def _guard(update, cfg: BotConfig, need_registered: bool = True) -> bool:
    """私聊 / 未拉黑 / 已注册 三道闸；不通过时已经回复用户。"""
    if update is None or update.effective_user is None or update.effective_message is None:
        return False
    if update.effective_chat is None or update.effective_chat.type != "private":
        await _reply(update, "请在私聊中使用本机器人。")
        return False

    uid = _uid(update)
    if await asyncio.to_thread(cfg.database.is_blocked, uid):
        await _reply(update, admin.BLOCKED)
        return False
    if need_registered and not await asyncio.to_thread(cfg.database.user_exists, uid):
        await _reply(update, admin.NO_USER)
        return False
    return True


# ---------------- 用户命令 ----------------

async def start_command(update, context: ContextTypes.DEFAULT_TYPE, cfg: BotConfig) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    if update.effective_chat is None or update.effective_chat.type != "private":
        await _reply(update, "请在私聊中使用本机器人。")
        return

    uid = _uid(update)
    if await asyncio.to_thread(cfg.database.is_blocked, uid):
        await _reply(update, admin.BLOCKED)
        return

    user = await asyncio.to_thread(cfg.database.get_user, uid)
    if user:
        await _reply(update, f"欢迎回来，{_display_name(update)}。\n当前积分：{user['balance']}")
        return

    invited_by = None
    if context.args:
        try:
            invited_by = int(context.args[0])
        except ValueError:
            invited_by = None
        if invited_by == uid:
            invited_by = None

    created = await asyncio.to_thread(
        cfg.database.create_user, uid, update.effective_user.username or "",
        _display_name(update), invited_by,
    )
    if not created:                       # 并发下另一个请求先注册成功
        user = await asyncio.to_thread(cfg.database.get_user, uid)
        balance = user["balance"] if user else REGISTER_REWARD
        await _reply(update, f"欢迎回来，{_display_name(update)}。\n当前积分：{balance}")
        return

    await _reply(
        update,
        f"注册成功，赠送 {REGISTER_REWARD} 积分。\n\n"
        f"用 /verify <课程名> 生成一张教学示例证书；\n"
        f"用 /qd 每日签到；用 /redeem <卡密> 兑换积分。\n"
        f"邀请好友：把你的 ID {uid} 发给对方，让对方发 /start {uid}。",
    )


async def help_command(update, context: ContextTypes.DEFAULT_TYPE, cfg: BotConfig) -> None:
    if not await _guard(update, cfg, need_registered=False):
        return
    text = (
        "可用命令：\n"
        "/start [邀请人ID]  注册（可带邀请人）\n"
        "/help             查看本帮助\n"
        "/balance          查询积分\n"
        "/qd               每日签到\n"
        "/redeem <卡密>     兑换积分\n"
        "/verify <课程名>   消耗 1 积分生成教学证书\n"
    )
    if _uid(update) == cfg.admin_id:
        text += (
            "\n管理员命令：\n"
            "/addbalance <用户ID> <积分>\n"
            "/block <用户ID>  /white <用户ID>\n"
            "/blacklist\n"
            "/genkey <卡密> <积分> [次数] [有效天数]\n"
            "/listkeys\n"
            "/stats\n"
            "/broadcast <文本>"
        )
    await _reply(update, text)


async def balance_command(update, context: ContextTypes.DEFAULT_TYPE, cfg: BotConfig) -> None:
    if not await _guard(update, cfg):
        return
    user = await asyncio.to_thread(cfg.database.get_user, _uid(update))
    await _reply(update, f"当前积分：{user['balance']}")


async def checkin_command(update, context: ContextTypes.DEFAULT_TYPE, cfg: BotConfig) -> None:
    if not await _guard(update, cfg):
        return
    uid = _uid(update)
    ok = await asyncio.to_thread(cfg.database.checkin, uid)
    user = await asyncio.to_thread(cfg.database.get_user, uid)
    message = "签到成功" if ok else "今天已经签过了"
    await _reply(update, f"{message}\n当前积分：{user['balance']}")


async def redeem_command(update, context: ContextTypes.DEFAULT_TYPE, cfg: BotConfig) -> None:
    if not await _guard(update, cfg):
        return
    if not context.args:
        await _reply(update, "用法：/redeem <卡密>")
        return

    uid = _uid(update)
    code = context.args[0].strip()
    result = await asyncio.to_thread(cfg.database.use_card_key, code, uid)
    if result > 0:
        user = await asyncio.to_thread(cfg.database.get_user, uid)
        await _reply(update, f"兑换成功，到账 {result} 积分。\n当前积分：{user['balance']}")
        return

    reason = {
        -1: "该卡密使用次数已满。",
        -2: "该卡密已过期。",
        -3: "你已经使用过这张卡密。",
        -4: "卡密不存在，请检查是否输入正确。",
        -5: "请先 /start 注册。",
    }.get(result, "兑换失败，请稍后重试。")
    await _reply(update, reason)


async def verify_command(update, context: ContextTypes.DEFAULT_TYPE, cfg: BotConfig) -> None:
    """扣分 → 渲染 → 本地模拟审核 → 记账 → 发送证书图。全程不联网。"""
    if not await _guard(update, cfg):
        return
    if not context.args:
        await _reply(update, "用法：/verify <课程名>\n例如：/verify Python 异步编程")
        return

    uid = _uid(update)
    name = _display_name(update)[:32]
    course = " ".join(context.args).strip()[:80]

    charged = await asyncio.to_thread(cfg.database.deduct_balance, uid, VERIFY_COST)
    if not charged:
        await _reply(update, "积分不足，请先 /qd 签到或 /redeem 兑换卡密。")
        return

    status = await _reply_and_return(
        update, f"已扣 {VERIFY_COST} 积分，正在生成证书并提交本地审核..."
    )

    def refund_and_record(detail: str) -> None:
        cfg.database.add_balance(uid, VERIFY_COST)
        try:
            cfg.database.add_verification(uid, "certificate", "failed", detail[:1000])
        except Exception:
            logger.exception("记录失败认证时出错")

    try:
        async with registry.get("certificate"):
            vid = await asyncio.to_thread(cfg.gateway.create, uid)
            await asyncio.to_thread(
                cfg.gateway.collect_applicant_info, vid, full_name=name, course=course
            )
            png = await asyncio.to_thread(
                render_certificate, name, course, 12, 95,
                f"VL-{uid}-{vid}-{uuid.uuid4().hex[:6]}",
                cfg.outputs_dir, cfg.render_backend,
            )
            upload = await asyncio.to_thread(
                cfg.gateway.request_upload, vid, png.name, png.stat().st_size
            )
            await asyncio.to_thread(cfg.gateway.put_object, upload["uploadUrl"], png.read_bytes())
            await asyncio.to_thread(cfg.gateway.complete_upload, vid)
            result = await asyncio.to_thread(cfg.gateway.poll, vid, 5.0)
    except GatewayError as exc:
        await asyncio.to_thread(refund_and_record, f"GatewayError: {exc}")
        await _edit(status, update, f"提交失败：{exc}\n已退回 {VERIFY_COST} 积分。")
        return
    except Exception:
        logger.exception("verify failed")
        await asyncio.to_thread(refund_and_record, "internal error")
        await _edit(status, update, f"处理出错，已退回 {VERIFY_COST} 积分。")
        return

    review_status = result.get("status", "unknown")
    if review_status != "success":
        await asyncio.to_thread(
            refund_and_record, f"review status={review_status} result={result}"
        )
        await _edit(status, update, f"审核未通过：{review_status}\n已退回 {VERIFY_COST} 积分。")
        return

    try:
        await asyncio.to_thread(
            cfg.database.add_verification, uid, "certificate", "success", str(result)
        )
    except Exception:
        logger.exception("记录成功认证时出错（证书仍会发送）")

    reward = result.get("rewardCode")
    await _edit(status, update, f"审核通过 ✅\n课程：{course}\n优惠码：{reward}")

    caption = f"教学示例证书 · 不具备任何效力\n课程：{course}\n编号：{png.stem}"
    try:
        with png.open("rb") as fh:
            await update.effective_message.reply_document(
                document=fh, filename=png.name, caption=caption[:1024]
            )
    except Exception:
        logger.exception("发送证书失败")
        await _reply(update, "证书已生成，但图片发送失败；请稍后用 /balance 确认积分。")


async def _reply_and_return(update, text: str):
    if update.effective_message is None:
        return None
    return await update.effective_message.reply_text(text)


async def _edit(status_message, update, text: str) -> None:
    if status_message is None or len(text) > TELEGRAM_TEXT_LIMIT:
        await _reply(update, text)
        return
    try:
        await status_message.edit_text(text)
    except Exception:
        logger.exception("编辑消息失败，改为新发一条")
        await _reply(update, text)


# ---------------- 管理员命令 ----------------

async def _run_admin(update, context: ContextTypes.DEFAULT_TYPE,
                     cfg: BotConfig, fn) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    text = await asyncio.to_thread(
        fn, cfg.database, _uid(update), cfg.admin_id, context.args
    )
    await _reply(update, text)


async def broadcast_command(update, context: ContextTypes.DEFAULT_TYPE, cfg: BotConfig) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    text = " ".join(context.args).strip()
    targets, message = await asyncio.to_thread(
        admin.broadcast_targets, cfg.database, _uid(update), cfg.admin_id, text
    )
    await _reply(update, message)
    if not targets:
        return

    sent = 0
    for target in targets:
        try:
            await context.bot.send_message(chat_id=target, text=text)
            sent += 1
        except Exception as exc:                      # 单个用户失败不影响整体
            logger.warning("广播到 %s 失败: %s", target, exc)
        await asyncio.sleep(0.05)                     # 限速，避免触发 Telegram 频控
    await _reply(update, f"广播完成：成功 {sent}/{len(targets)}")


async def unknown_command(update, context: ContextTypes.DEFAULT_TYPE, cfg: BotConfig) -> None:
    if update.effective_message is None:
        return
    command = (update.effective_message.text or "").split()[0]
    await _reply(update, f"未知命令：{command}\n发送 /help 查看可用命令。")


async def plain_text(update, context: ContextTypes.DEFAULT_TYPE, cfg: BotConfig) -> None:
    await _reply(update, "发送 /help 查看可用命令。")


async def on_error(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("未捕获异常", exc_info=context.error)
    try:
        await _reply(update, "处理出错，请稍后重试。")
    except Exception:
        pass


# ---------------- 装配 ----------------

def build_application(cfg: BotConfig):
    if Application is None:
        raise RuntimeError("需要先安装：pip install 'python-telegram-bot>=21'")

    builder = Application.builder().token(cfg.token)
    if cfg.concurrent_updates:
        builder = builder.concurrent_updates(cfg.concurrent_updates)
    if cfg.base_url:                       # 本地 Bot API 仿真 / 自建反代
        builder = builder.base_url(cfg.base_url.rstrip("/"))
        builder = builder.base_file_url(cfg.base_url.rstrip("/"))
    app = builder.build()

    user_commands = [
        ("start", start_command),
        ("help", help_command),
        ("balance", balance_command),
        ("qd", checkin_command),
        ("redeem", redeem_command),
        ("verify", verify_command),
    ]
    for name, handler in user_commands:
        app.add_handler(CommandHandler(name, partial(handler, cfg=cfg)))

    admin_commands = [
        ("addbalance", admin.add_balance),
        ("block", admin.block),
        ("white", admin.unblock),
        ("blacklist", admin.blacklist),
        ("genkey", admin.genkey),
        ("listkeys", admin.listkeys),
        ("stats", admin.stats),
    ]
    for name, fn in admin_commands:
        app.add_handler(CommandHandler(name, partial(_run_admin, cfg=cfg, fn=fn)))
    app.add_handler(CommandHandler("broadcast", partial(broadcast_command, cfg=cfg)))

    app.add_handler(MessageHandler(filters.COMMAND, partial(unknown_command, cfg=cfg)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, partial(plain_text, cfg=cfg)))
    app.add_error_handler(on_error)
    return app


# ---------------- 自检 ----------------

def _check_telegram_token(token: str) -> tuple[bool, str]:
    if not token:
        return False, "未设置 BOT_TOKEN（真实联网测试需要它）"
    url = f"https://api.telegram.org/bot{token}/getMe"
    last_error = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("ok"):
                me = payload["result"]
                return True, f"@{me.get('username')} (id={me.get('id')})"
            return False, f"Telegram 返回：{payload.get('description', payload)}"
        except urllib.error.HTTPError as exc:
            return False, f"HTTP {exc.code}（通常是 Token 无效）"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))     # 网络抖动重试，401 不重试
    return False, last_error


def run_check(cfg: BotConfig) -> int:
    problems: list[str] = []
    print("== verify-lab 启动自检 ==")
    print(f"数据库后端：{os.getenv('DB_BACKEND', 'sqlite')}")
    try:
        users = cfg.database.count_users()
        cards = len(cfg.database.get_all_card_keys())
        records = cfg.database.count_verifications()
        print(f"[✓] 数据库连通：用户 {users} / 卡密 {cards} / 认证记录 {records}")
    except Exception as exc:
        problems.append(f"数据库连接失败：{type(exc).__name__}: {exc}")
        print(f"[✗] 数据库连接失败：{type(exc).__name__}: {exc}")

    try:
        out = render_certificate(
            "自检 张三", "启动自检（教学示例）", 1, 100, "VL-SELFCHECK",
            cfg.outputs_dir / "_selfcheck", "pillow",
        )
        from PIL import Image
        with Image.open(out) as img:
            width, height = img.size
            img.verify()
        if width < 100 or height < 100:
            raise ValueError(f"图片尺寸异常：{width}x{height}")
        print(f"[✓] 证书渲染：{out} ({width}x{height}, {out.stat().st_size} bytes)")
    except Exception as exc:
        problems.append(f"证书渲染失败：{type(exc).__name__}: {exc}")
        print(f"[✗] 证书渲染失败：{type(exc).__name__}: {exc}")

    try:
        vid = cfg.gateway.create(0)
        cfg.gateway.collect_applicant_info(vid, full_name="自检", course="启动自检")
        upload = cfg.gateway.request_upload(vid, "selfcheck.png", 16)
        cfg.gateway.put_object(upload["uploadUrl"], b"\x89PNG\r\n\x1a\n" + b"0" * 8)
        cfg.gateway.complete_upload(vid)
        result = cfg.gateway.poll(vid, timeout=2.0)
        if result.get("status") != "success":
            raise RuntimeError(f"审核状态机返回 {result}")
        print(f"[✓] 本地审核状态机：{result.get('rewardCode')}")
    except Exception as exc:
        problems.append(f"审核状态机失败：{type(exc).__name__}: {exc}")
        print(f"[✗] 审核状态机失败：{type(exc).__name__}: {exc}")

    token_ok, token_msg = _check_telegram_token(cfg.token)
    if token_ok:
        print(f"[✓] Telegram Token：{token_msg}")
    elif cfg.token:
        print(f"[✗] Telegram Token：{token_msg}")
        problems.append(f"Telegram Token 不可用：{token_msg}")
    else:
        print(f"[!] Telegram Token：{token_msg}")

    if cfg.admin_id:
        print(f"[i] 管理员 ID：{cfg.admin_id}")
    else:
        print("[!] 未设置 ADMIN_USER_ID：管理命令将对所有人拒绝")

    print()
    if problems:
        print(f"自检失败：{len(problems)} 项")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("自检通过 ✅" + ("（未做真实联网消息测试）" if not cfg.token else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="verify-lab Telegram Bot")
    parser.add_argument("--check", action="store_true", help="只做本地/Token 自检，不启动轮询")
    args = parser.parse_args(argv)

    load_env()
    _configure_logging(os.getenv("BOT_TOKEN", "").strip())
    cfg = build_config()

    if args.check:
        return run_check(cfg)

    if not cfg.token:
        print("请先设置 BOT_TOKEN（从 @BotFather 获取），可写进 .env：")
        print("  cp .env.example .env")
        print('  BOT_TOKEN="123456:ABC..."')
        print("Token 只在环境变量/本机 .env 中使用，不会写进日志或数据库。")
        return 2
    if not cfg.admin_id:
        logger.warning("ADMIN_USER_ID 未设置，所有管理员命令都会被拒绝")

    return _run_polling_with_retry(cfg)


def _run_polling_with_retry(cfg: BotConfig) -> int:
    """启动时网络抖动（DNS/连接超时）不该让整个 Bot 直接退出。"""
    from telegram.error import NetworkError, TimedOut

    delay = 5
    while True:
        try:
            app = build_application(cfg)
            logger.info(
                "bot started (db=%s, admin=%s)", os.getenv("DB_BACKEND", "sqlite"), cfg.admin_id
            )
            app.run_polling(
                drop_pending_updates=cfg.drop_pending,
                poll_interval=cfg.poll_interval,
                allowed_updates=Update.ALL_TYPES,
            )
            return 0
        except (NetworkError, TimedOut) as exc:
            logger.warning("Telegram 连接失败，%s 秒后重试：%s", delay, exc)
            time.sleep(delay)
            delay = min(delay * 2, 60)


if __name__ == "__main__":
    raise SystemExit(main())
