"""真实 MySQL 冒烟测试 —— 只有在你起了 MySQL 之后才有意义

前置：
    docker compose up -d mysql          # 首次启动会自动执行 sql/schema_mysql.sql
    pip install pymysql
    set MYSQL_HOST=127.0.0.1 ...        # 或用默认值（127.0.0.1 / lab / labpass / verify_lab）

运行：
    python scripts/smoke_mysql.py

它会用随机 user_id 建数据，跑完自己删掉，可重复执行。
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.db_mysql import MySQLDatabase  # noqa: E402


def main() -> int:
    db = MySQLDatabase()                       # 读 MYSQL_* 环境变量
    uid = random.randint(10**9, 10**10)
    key = f"SMOKE-{uid}"
    ok = True

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal ok
        ok = ok and cond
        print(f"  [{'✓' if cond else '✗'}] {label:<28} {extra}")

    try:
        db.create_user(uid, "smoke", "Smoke User")
        check("建表 + 注册", db.user_exists(uid))

        check("签到", db.checkin(uid))
        check("重复签到被拒", not db.checkin(uid))

        before = db.get_user(uid)["balance"]
        check("原子扣分", db.deduct_balance(uid, 1),
              f"{before} → {db.get_user(uid)['balance']}")

        check("生成卡密", db.create_card_key(key, balance=5, max_uses=2))
        check("使用卡密", db.use_card_key(key, uid) == 5)
        check("同一人重复使用被拒", db.use_card_key(key, uid) == -3)
        check("卡密不存在", db.use_card_key("NOPE", uid) == -4)
        check("用户不存在", db.use_card_key(key, 10**10 + 1) == -5)

        db.add_verification(uid, "smoke", "success", "ok")
        check("认证记录", len(db.list_verifications(uid)) == 1)
    finally:
        # 清理测试数据，保证脚本可重复执行
        with db._connect() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM card_key_usage WHERE key_code LIKE 'SMOKE-%'")
            cur.execute("DELETE FROM card_keys WHERE key_code LIKE 'SMOKE-%'")
            cur.execute("DELETE FROM verifications WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM invitations WHERE inviter_id = %s OR invitee_id = %s",
                        (uid, uid))
            cur.execute("DELETE FROM users WHERE user_id = %s", (uid,))
            conn.commit()

    print("\n  全部通过 ✅" if ok else "\n  有失败项 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
