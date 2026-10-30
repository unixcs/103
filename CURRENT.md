# CURRENT — 103 热状态（干完活更新这里）

## 2026-10-30 · GitHub 跨设备交接仓已建立并公开

- 本地目录 `/mnt/Projects/103` 即 Git 仓库根，主分支 `main`
- 远端：`https://github.com/unixcs/103`（**public**）
- 密钥与本机产物不入库：`.env`、`.venv/`、`*.db`、`outputs/`、`.tmp/`、日志均由 `.gitignore` 挡住
- 新设备接手：先读 `docs/HANDOFF.md`（含 Linux / Windows 步骤），再 `git clone`、建 `.venv`、复制 `.env.example` 重建 `.env`、跑默认测试
- CI：`.github/workflows/tests.yml`，每次 push/PR 自动跑 SQLite 默认测试
- 仓库含 `chat-51afdd4f/` 会话导出（接手背景）；公开前已扫描无 Token / PAT / 云密钥 / 私钥 / 手机号 / 身份证号 / 内网 IP
- Windows 尚未实机验收：代码含 Windows 字体回退与 `.bat`，但本轮只在 Linux 跑过

## 2026-10-30 · Bot 落地 + 墨菲测试完成；真实入站待主人 /start

### 本次完成

- **Telegram Bot 全部实现**：`bot.py` / `app/bot_service.py`
  - 用户命令：`/start [邀请码]`、`/help`、`/balance`、`/qd`、`/redeem`、`/verify`
  - 管理员命令：`/addbalance`、`/block`、`/white`、`/blacklist`、`/genkey`、`/listkeys`、`/stats`、`/broadcast`
  - 私聊守卫、黑名单、未注册拦截、失败自动退分、证书 PNG 发送、广播
- **本地 Telegram Bot API 仿真**：`tests/fake_telegram_api.py`，真实 PTB 轮询栈跑完整命令链路
- **真实 MySQL 8.0**：Docker 起库，建表、事务、`FOR UPDATE`、并发扣分/卡密防超发、`datetime` 归一化全部实测
- **Linux Pillow 中文渲染**：加 Noto CJK / DejaVu 字体回退，肉眼核对无豆腐块
- **Docker**：`Dockerfile` + compose `bot` profile（连 MySQL、装 `fonts-noto-cjk`、非 root）
- **修复 `.env` 启动路径 bug**：此前误读 `app/.env`，现在正确读 `verify-lab/.env`，输出目录也回到 `outputs/`；新增 4 个 `test_env.py` 用例
- **墨菲定律加固**：Token 从日志抹除、证书 HTML 注入转义、证书文件名防路径穿越、超长文本截断/字体缩放、`getMe` 与启动网络抖动重试、管理员参数上下界、超长消息自动分条
- **测试**：54 个用例（默认 48 通过 + 6 跳过；`VERIFY_LAB_MYSQL=1` 时 53 通过 + 1 跳过）
- **文档**：`verify-lab/README.md` 重写、新增 `verify-lab/TEST-REPORT.md`

### 真实性测试结果

| 检查 | 结果 |
|---|---|
| `python3 -m unittest discover -s tests -t . -v` | 54 个，`OK (skipped=6)` |
| `VERIFY_LAB_MYSQL=1 ...` 全量 | 54 个，`OK (skipped=1)` |
| `python3 demo.py` | 全流程通过，`全部完成 ✅` |
| `VERIFY_LAB_MYSQL=1 python3 scripts/smoke_mysql.py` | 10/10 通过 |
| Docker 内 `python bot.py --check`（MySQL） | 通过，证书 1000×700 |
| 假 Token 调 `getMe` | HTTP 401 → `api.telegram.org` 可达（预期） |
| 真实 Token `getMe` | ✅ `@yunbian666_bot`（id 9088234520），Bot 已在线轮询 |
| 真实 Telegram 消息收发 | ⏳ 等主人给 `@yunbian666_bot` 发 `/start` 建立私聊（Bot 不能主动开私聊） |

详见 `verify-lab/TEST-REPORT.md`。

### 墨菲定律测试发现并修复

1. **Token 泄进日志**：httpx 把 `/bot<TOKEN>/getMe` 完整打进日志；已加统一脱敏 Formatter，并把 httpx/httpcore 压到 WARNING。
2. **`.env` 读错路径**：实际读 `app/.env`，README 要求的根目录 `.env` 不生效；已修默认路径。
3. **证书 HTML 注入 / 文件名穿越**：姓名/课程未转义、证书编号直接拼文件名；已转义 + 白名单化文件名 + 超长文本截断/缩放。
4. **启动网络抖动直接退出**：一次 `ConnectError` 就让 Bot 死掉；已加 5s 起指数退避重试。
5. **管理员参数无上下界**：超大积分/次数/天数、超长卡密、0 天、4000 字以上广播都会报错或写坏数据；已全部加边界校验。
6. **超长列表消息发不出**：`/listkeys`、`/blacklist` 用户多时超过 Telegram 4096 字上限；已按行自动分条。
7. **重复实例互相踢**：两个 bot 进程同时 getUpdates 会 `409 Conflict`；运维上必须保证单实例（本轮已清理重复进程）。

### 环境（dell）

Python 3.13.5 · Pillow 13.0.0 · python-telegram-bot 22.8 · Playwright 1.64.1（Chromium 可用）· PyMySQL 1.2.3 · Docker 26.1.5 / Compose 2.26.1 · MySQL 8.0 容器 `verify-lab-mysql`（healthy）

### 迁移备份（历史）

- 来源：feng-1（Windows）`D:\mnt\Projects\103`
- 落点：dell `/mnt/Projects/103`
- 方式：`scp -r` 全量复制，44 个文件 SHA256 逐文件对账 44/44 一致

## 已知缺口 / 坑

1. **真实 Telegram 入站闭环未完成**：Token 已验证、Bot 已在线轮询，但还没有任何用户给 `@yunbian666_bot` 发过 `/start`，因此拿不到 `chat_id`，无法做真实 `sendMessage` / `sendDocument`。Telegram 不允许 Bot 主动给未建立会话的用户发私聊；主人在 Telegram 里发一句 `/start` 即可解锁后续验收。
2. **真实 MySQL 测试默认跳过**：必须显式 `VERIFY_LAB_MYSQL=1`，避免没起库的机器误报失败。
3. **Windows 脚本仍是旧文案**：`一键测试.bat` 的提示没有写测试数量，可继续用；`零基础说明.md` 已改为 Linux 优先。
4. **GitHub 仓库已建但尚未接入 `proj-sync`**：目前用原生 `git pull --ff-only` / `git push` 交接；要进三机同步网再登记 `proj-sync.conf`。
5. **Windows 未实机验收**：Pillow 中文字体、`.env` 无 BOM、Docker Desktop MySQL、Playwright Chromium、两个 `.bat` 都需要在 Windows 上按 `docs/HANDOFF.md` 第 7 节跑一遍；注意 `.bat` 调用系统 `python`，依赖装在 venv 时先激活。
6. **顶层架构文档有空洞**：§2「专用数据表结构」和「核心读写源码」是空代码块，只能当提纲读，细节以 `verify-lab/app/` 实现为准。
7. **Token 已在聊天里出现过**：测试结束后建议在 BotFather 里 `/revoke` 轮换，并把新 Token 只写进 `.env`（权限 600）。

## 下一步（候选，未拍板）

1. 主人在 Telegram 给 `@yunbian666_bot` 发 `/start` 后，把真实 user id 写进 `.env` 的 `ADMIN_USER_ID`，重启 Bot，跑真实管理员命令与证书发送验收（不提交任何真实身份材料）。
2. 在 Windows 上按 `docs/HANDOFF.md` 第 7 节做一次最小验收，把结果回写到文档第 4.3 节。
3. 若要纳入多机同步：确认后登记 `proj-sync.conf`；当前原生 git 交接已够用。
4. 若要继续小说证书：从 Windows 把 `novel/make_guild_cert.py` 与预设迁过来（不在 103 内）。
