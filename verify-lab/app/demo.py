"""端到端演示 —— 一条命令跑完整个系统

    python demo.py

它做的事（全部本地、离线、不提交任何真实信息）：
  1. 注册两个用户，演示邀请奖励；
  2. 签到，演示"一天只能签一次"的原子判断；
  3. 管理员发卡密，用户体验"次数限制 / 重复使用 / 过期"；
  4. 扣积分 + 渲染结业证书 PNG；
  5. 走一遍本地模拟的审核状态机（创建 → 填资料 → 上传 → 完成 → 轮询）；
  6. 演示失败路径：审核失败要退积分，并记录到 verifications 表。
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

# Windows 控制台默认不是 UTF-8，先修一下，否则中文可能乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import db as db_module                       # noqa: E402
from app.db import Database                           # noqa: E402
from app.mock_verifier import GatewayError, MockReviewGateway  # noqa: E402
from app.render import render_certificate             # noqa: E402


def title(text: str) -> None:
    print(f"\n{'=' * 62}\n  {text}\n{'=' * 62}")


def show(tag: str, ok: bool, extra: str = "") -> None:
    """按显示宽度对齐（中文占 2 列，直接 len() 会歪）。"""
    width = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in tag)
    print(f"  [{'✓' if ok else '✗'}] {tag}{' ' * max(1, 36 - width)} {extra}")


def main() -> int:
    dbfile = BASE / "verify_lab.db"
    if dbfile.exists():
        dbfile.unlink()

    db = Database(dbfile)
    gateway = MockReviewGateway(BASE / "outputs" / "evidence")

    title("1. 注册与邀请奖励")
    db.create_user(1001, "alice", "Alice Zhang")
    db.create_user(1002, "bob", "Bob Li", invited_by=1001)
    alice, bob = db.get_user(1001), db.get_user(1002)
    show("Alice 注册", True, f"积分 = {alice['balance']}")
    show("Bob 通过 Alice 的邀请注册", True, f"Bob = {bob['balance']} 分, Alice = {alice['balance']} 分")
    assert alice["balance"] == 1 + db_module.INVITE_REWARD, "邀请奖励没到账"

    title("2. 签到（原子 UPDATE）")
    show("Bob 今天第一次签到", db.checkin(1002), f"余额 = {db.get_user(1002)['balance']}")
    show("Bob 再签一次（应失败）", not db.checkin(1002), f"余额 = {db.get_user(1002)['balance']}")

    title("3. 卡密（次数 / 重复 / 过期）")
    db.create_user(1003, "carol", "Carol Wang")
    db.create_user(1004, "dave", "Dave Liu")
    db.create_card_key("LAB-VIP-001", balance=5, max_uses=2)
    code = db.use_card_key("LAB-VIP-001", 1002)
    show("Bob 使用卡密", code == 5, f"+{code} 积分 → {db.get_user(1002)['balance']}")
    code2 = db.use_card_key("LAB-VIP-001", 1002)
    show("Bob 重复使用同一张（应拒绝）", code2 == -3, f"返回 {code2} (-3 = 本人已用过)")
    code3 = db.use_card_key("LAB-VIP-001", 1003)
    show("Carol 用掉最后一次", code3 == 5, f"+{code3} 积分（2/2 已用满）")
    code4 = db.use_card_key("LAB-VIP-001", 1004)
    show("Dave 再兑换（应拒绝）", code4 == -1, f"返回 {code4} (-1 = 次数已满)")

    title("4. 扣积分 + 渲染证书")
    before = db.get_user(1002)["balance"]
    charged = db.deduct_balance(1002, db_module.VERIFY_COST)
    show("原子扣分", charged, f"{before} → {db.get_user(1002)['balance']}")
    show("余额不足时扣分（应失败）", not db.deduct_balance(9999, 1), "用户不存在")

    serial = "VL-2026-0001"
    png = render_certificate("Bob Li", "Python 异步编程（教学示例）", hours=12, score=92,
                             serial=serial, out_dir=BASE / "outputs")
    show("生成证书 PNG", png.exists(), f"{png.relative_to(BASE)}  ({png.stat().st_size / 1024:.1f} KB)")

    title("5. 本地模拟审核状态机")
    vid = gateway.create(1002)
    show("创建审核单", True, vid)
    step = gateway.collect_applicant_info(vid, full_name="Bob Li",
                                          course="Python 异步编程（教学示例）")
    show("提交申请信息", step == "uploadDocument", f"currentStep = {step}")
    upload = gateway.request_upload(vid, "certificate.png", png.stat().st_size)
    gateway.put_object(upload["uploadUrl"], png.read_bytes())
    show("上传文档", True, upload["uploadUrl"].split("\\")[-1])
    show("确认提交", gateway.complete_upload(vid) == "review", "currentStep = review")
    result = gateway.poll(vid, timeout=5)
    show("轮询审核结果", result["status"] == "success", f"rewardCode = {result.get('rewardCode')}")
    db.add_verification(1002, "certificate", "success", str(result))

    title("6. 失败路径：业务错误要退积分 + 记录")
    bad_vid = gateway.create(1002)
    try:
        gateway.collect_applicant_info(bad_vid, full_name="", course="")
    except GatewayError as exc:
        db.add_balance(1002, db_module.VERIFY_COST)     # 失败退分
        db.add_verification(1002, "certificate", "failed", str(exc))
        show("捕获业务异常", True, str(exc))
        show("失败退分", True, f"余额 = {db.get_user(1002)['balance']}")

    title("7. 数据落库情况")
    for row in db.list_verifications(1002):
        print(f"  #{row['id']}  {row['kind']:<12} {row['status']:<8} {row['detail'][:52]}")
    final = db.get_user(1002)
    print(f"\n  Bob 最终余额：{final['balance']} 分")
    print(f"  数据库文件：{dbfile.relative_to(BASE)}")
    print(f"  证书与 HTML 模板：outputs/")
    print("\n  全部完成 ✅  —— 全部离线运行，没有访问任何外部服务。\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
