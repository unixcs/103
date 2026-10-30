"""管理员业务逻辑 —— 纯函数，**不 import telegram**

对照原项目 handlers/admin_commands.py：那里每条命令都长这样：

    async def genkey_command(update, context, db):
        if await reject_group_command(update): return          # ① 适配层
        if update.effective_user.id != ADMIN_USER_ID: ...      # ② 鉴权
        if not context.args or len(context.args) < 2: ...      # ③ 参数校验
        try: key_code = context.args[0]; balance = int(...)     # ④ 解析
        ...                                                     # ⑤ 业务
        await update.message.reply_text(...)                    # ⑥ 回复

①③④⑥ 是 Telegram 的事，②⑤ 是业务的事，它们被焊死在一个函数里，
所以想测"卡密余额非正数会不会被拒绝"，必须伪造一个 Update 对象。

这里把业务函数抽出来：入参是普通值，返回值是要回复的文本。
Telegram 适配层（bot_skeleton.py）只做三件事：取参数 → 调函数 → 发消息。
"""
from __future__ import annotations

from datetime import datetime

from .db import Database

ADMIN_ONLY = "您没有权限使用此命令。"
NO_USER = "请先使用 /start 注册。"
BLOCKED = "您已被拉黑，无法使用此功能。"


# ---------------- 公共校验 ----------------

def _deny(operator_id: int, admin_id: int) -> str | None:
    return None if operator_id == admin_id else ADMIN_ONLY


def _parse_int(text: str, field: str) -> int:
    try:
        return int(text)
    except (TypeError, ValueError):
        raise ValueError(f"{field} 必须是整数：{text!r}") from None


def _require_user(db: Database, user_id: int) -> str | None:
    return None if db.user_exists(user_id) else f"用户 {user_id} 不存在。"


# ---------------- 积分 ----------------

def add_balance(db: Database, operator_id: int, admin_id: int, args: list[str]) -> str:
    if err := _deny(operator_id, admin_id):
        return err
    if len(args) < 2:
        return "用法：/addbalance <用户ID> <积分>"
    try:
        target, amount = _parse_int(args[0], "用户ID"), _parse_int(args[1], "积分")
    except ValueError as exc:
        return str(exc)
    if err := _require_user(db, target):
        return err
    if amount == 0:
        return "积分不能为 0。"
    if abs(amount) > 1_000_000:
        return "单次调整积分不能超过 1,000,000。"
    db.add_balance(target, amount)
    return f"已为用户 {target} 增加 {amount} 分，当前 {db.get_user(target)['balance']} 分"


# ---------------- 黑名单 ----------------

def block(db: Database, operator_id: int, admin_id: int, args: list[str]) -> str:
    if err := _deny(operator_id, admin_id):
        return err
    if not args:
        return "用法：/block <用户ID>"
    try:
        target = _parse_int(args[0], "用户ID")
    except ValueError as exc:
        return str(exc)
    if err := _require_user(db, target):
        return err
    db.block_user(target)
    return f"已拉黑用户 {target}"


def unblock(db: Database, operator_id: int, admin_id: int, args: list[str]) -> str:
    if err := _deny(operator_id, admin_id):
        return err
    if not args:
        return "用法：/white <用户ID>"
    try:
        target = _parse_int(args[0], "用户ID")
    except ValueError as exc:
        return str(exc)
    if err := _require_user(db, target):
        return err
    db.unblock_user(target)
    return f"已将用户 {target} 移出黑名单"


def blacklist(db: Database, operator_id: int, admin_id: int, args: list[str]) -> str:
    if err := _deny(operator_id, admin_id):
        return err
    rows = db.get_blacklist()
    if not rows:
        return "黑名单为空。"
    lines = [f"用户 {r['user_id']}  @{r['username'] or '-'}  {r['full_name']}" for r in rows]
    return "黑名单：\n" + "\n".join(lines)


# ---------------- 卡密 ----------------

def genkey(db: Database, operator_id: int, admin_id: int, args: list[str]) -> str:
    if err := _deny(operator_id, admin_id):
        return err
    if len(args) < 2:
        return "用法：/genkey <卡密> <积分> [次数] [有效天数]"
    key = args[0].strip()
    try:
        balance = _parse_int(args[1], "积分")
        max_uses = _parse_int(args[2], "次数") if len(args) > 2 else 1
        days = _parse_int(args[3], "有效天数") if len(args) > 3 else None
    except ValueError as exc:
        return str(exc)
    if balance <= 0:
        return "积分必须大于 0。"
    if balance > 1_000_000:
        return "积分不能超过 1,000,000。"
    if max_uses <= 0:
        return "使用次数必须大于 0。"
    if max_uses > 1_000_000:
        return "使用次数不能超过 1,000,000。"
    if days is not None and not 1 <= days <= 3650:
        return "有效天数必须在 1-3650 之间。"
    if not key or len(key) > 100:
        return "卡密长度必须在 1-100 个字符之间。"
    if not db.create_card_key(key, balance, operator_id, max_uses, days):
        return f"卡密 {key} 已存在。"
    expiry = f"{days} 天后过期" if days else "永久有效"
    return f"已生成卡密 {key}：{balance} 分 / {max_uses} 次 / {expiry}"


def listkeys(db: Database, operator_id: int, admin_id: int, args: list[str]) -> str:
    if err := _deny(operator_id, admin_id):
        return err
    cards = db.get_all_card_keys()
    if not cards:
        return "暂无卡密。"
    lines = []
    for c in cards:
        status = f"{c['current_uses']}/{c['max_uses']}"
        expire_at = c["expire_at"]
        if expire_at:
            # 数据层已把 MySQL datetime 归一成 ISO 字符串；这里再兜一层，
            # 防止有人绕过 BaseDatabase 直接拿到原始 datetime。
            if isinstance(expire_at, datetime):
                expire_at = expire_at.isoformat()
            expired = datetime.now() > datetime.fromisoformat(expire_at)
            status += "（已过期）" if expired else f"（{expire_at[:10]} 到期）"
        lines.append(f"{c['key_code']:<16} {c['balance']:>4} 分  {status}")
    return "卡密列表：\n" + "\n".join(lines)


# ---------------- 统计 ----------------

def stats(db: Database, operator_id: int, admin_id: int, args: list[str]) -> str:
    if err := _deny(operator_id, admin_id):
        return err
    return (
        "运行统计：\n"
        f"用户总数：{db.count_users()}\n"
        f"黑名单：{len(db.get_blacklist())}\n"
        f"卡密数量：{len(db.get_all_card_keys())}\n"
        f"认证记录：{db.count_verifications()}"
    )


# ---------------- 广播 ----------------

def broadcast_targets(db: Database, operator_id: int, admin_id: int,
                      text: str) -> tuple[list[int], str]:
    """只负责"该发给谁"，真正的发送（需要 bot 对象和限速）留在适配层。

    这样的拆分让"广播给谁"这件事可以单测，而"怎么发"才需要 Telegram。
    """
    if err := _deny(operator_id, admin_id):
        return [], err
    if not text.strip():
        return [], "用法：/broadcast <文本>"
    if len(text) > 4000:
        return [], "广播内容太长（Telegram 单条上限 4096 字，请拆成多条）。"
    targets = db.get_all_user_ids()
    return targets, f"开始广播，共 {len(targets)} 人"
