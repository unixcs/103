"""并发竞态实验 —— 对照原项目 database_mysql.py 的两个真实 bug

    python tests/test_atomicity.py

用 20 个线程同时扣同一份余额 / 同时用同一张卡密，
把"先 SELECT 再 UPDATE"和"一条原子 UPDATE"的结果摆在一起对比。
"""
from __future__ import annotations

import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.db import Database  # noqa: E402

DB_PATH = BASE / "test_atomicity.db"
THREADS = 20


def setup(balance: int = 10) -> Database:
    if DB_PATH.exists():
        DB_PATH.unlink()
    db = Database(DB_PATH)
    db.create_user(1, "u", "User")
    with db._connect() as conn:
        conn.execute("UPDATE users SET balance = ? WHERE user_id = 1", (balance,))
    return db


# ---------- 错误示范：先查后改（原项目的写法） ----------

def naive_deduct(user_id: int, amount: int) -> bool:
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    try:
        row = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None or row[0] < amount:
            return False
        time.sleep(0.002)                       # 放大"读"和"写"之间的窗口
        conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        return True
    finally:
        conn.close()


def naive_use_card(key: str, user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    try:
        card = conn.execute("SELECT * FROM card_keys WHERE key_code = ?", (key,)).fetchone()
        if card is None or card[3] >= card[2]:          # current_uses >= max_uses
            return False
        time.sleep(0.002)
        conn.execute("INSERT OR IGNORE INTO card_key_usage (key_code, user_id) VALUES (?,?)",
                     (key, user_id))
        conn.execute("UPDATE card_keys SET current_uses = current_uses + 1 WHERE key_code = ?", (key,))
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (card[1], user_id))
        return True
    finally:
        conn.close()


def run_parallel(fn, args_list):
    barrier = threading.Barrier(len(args_list))

    def wrapped(args):
        barrier.wait()                      # 尽量让所有线程同时起跑
        return fn(*args)

    with ThreadPoolExecutor(max_workers=len(args_list)) as pool:
        return list(pool.map(wrapped, args_list))


def main() -> int:
    print(f"\n{'=' * 62}\n  并发竞态实验（{THREADS} 线程）\n{'=' * 62}")

    # --- 实验 1：余额扣减 ---
    print("\n[实验 1] 余额 10，20 个线程各扣 1")
    db = setup(balance=10)
    ok = run_parallel(naive_deduct, [(1, 1)] * THREADS)
    naive_balance = db.get_user(1)["balance"]
    print(f"  错误示范（先查后改）：成功 {sum(ok)} 次，余额 = {naive_balance}"
          f"  {'← 透支了！' if naive_balance < 0 else ''}")

    db = setup(balance=10)
    ok = run_parallel(db.deduct_balance, [(1, 1)] * THREADS)
    atomic_balance = db.get_user(1)["balance"]
    print(f"  正确写法（原子 UPDATE）：成功 {sum(ok)} 次，余额 = {atomic_balance}")
    assert sum(ok) == 10 and atomic_balance == 0, "原子版本出错了"

    # --- 实验 2：卡密超发 ---
    print("\n[实验 2] 卡密 max_uses=3，10 个不同用户同时兑换")
    db = setup()
    db.create_card_key("RACE-001", balance=5, max_uses=3)
    for uid in range(2, 12):
        db.create_user(uid, f"u{uid}", f"User {uid}")

    ok = run_parallel(naive_use_card, [("RACE-001", uid) for uid in range(2, 12)])
    with db._connect() as conn:
        card = conn.execute("SELECT current_uses, max_uses FROM card_keys WHERE key_code='RACE-001'").fetchone()
    print(f"  错误示范（先查后改）：成功 {sum(ok)} 次，current_uses = {card[0]}/{card[1]}"
          f"  {'← 超发了！' if sum(ok) > 3 else ''}")

    db = setup()
    db.create_card_key("RACE-002", balance=5, max_uses=3)
    for uid in range(2, 12):
        db.create_user(uid, f"u{uid}", f"User {uid}")
    ok = run_parallel(db.use_card_key, [("RACE-002", uid) for uid in range(2, 12)])
    successes = sum(1 for r in ok if r > 0)
    with db._connect() as conn:
        card = conn.execute("SELECT current_uses, max_uses FROM card_keys WHERE key_code='RACE-002'").fetchone()
    print(f"  正确写法（写锁 + 唯一主键）：成功 {successes} 次，current_uses = {card[0]}/{card[1]}")
    assert successes == 3 and card[0] == 3, "卡密防超发失败"

    print("\n  结论：读写之间只要没有原子性保证，并发就会穿透检查。")
    print("  修法只有两类：① 把判断塞进同一条 SQL 的 WHERE；② 显式加锁（FOR UPDATE / BEGIN IMMEDIATE）。\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
