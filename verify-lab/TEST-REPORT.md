# 真实性测试报告 — verify-lab

- **日期**：2026-10-30
- **机器**：dell（Debian，`Linux 6.12.107+deb13-amd64 x86_64`）
- **目录**：`/mnt/Projects/103/verify-lab`
- **Python**：3.13.5（`.venv`）
- **依赖**：Pillow 13.0.0、python-telegram-bot 22.8、Playwright 1.64.1、PyMySQL 1.2.3、cryptography 50.0.2
- **数据库**：Docker `mysql:8.0`，容器 `verify-lab-mysql`（healthy）
- **Docker**：26.1.5 / Compose 2.26.1

## 结论

1. **Bot 全部命令与业务链路已实现并通过端到端测试**：使用真实 `python-telegram-bot` 调度栈 + 本地 Telegram Bot API 仿真，覆盖注册、签到、卡密、扣分、审核、证书发送、失败退分、管理员命令、广播。
2. **真实 MySQL 8.0 全链路通过**：建表、事务、行锁、并发原子性、`datetime` 类型归一化均实测。
3. **真实 Token 出站验证通过**：主人提供的 Token 调 `getMe` 返回 `@yunbian666_bot`（id 9088234520），Bot 已在本机轮询运行。
4. **真实 Telegram 消息收发尚未执行**：还没有用户给 `@yunbian666_bot` 发过 `/start`，拿不到 `chat_id`；Telegram 不允许 Bot 主动给未建立会话的用户发私聊。这是唯一剩余项，不是代码问题。
5. **墨菲定律加固已完成**：Token 日志脱敏、HTML 注入转义、文件名防穿越、超长文本收缩、网络抖动重试、管理员参数边界、超长消息分条，均有测试锁定。
6. **合规边界未突破**：审核仍是本地 mock，未接 SheerID，未生成/提交任何真实身份材料，证书保留 `SAMPLE` 与「教学示例，不具备任何效力」。

## 测试矩阵

| # | 项目 | 命令 | 结果 |
|---|---|---|---|
| 1 | 默认全量（SQLite） | `python -m unittest discover -s tests -t . -v` | **54 个，48 通过，6 跳过**（`OK (skipped=6)`） |
| 2 | 全量含真实 MySQL | `VERIFY_LAB_MYSQL=1 python -m unittest discover -s tests -t . -v` | **54 个，53 通过，1 跳过**（`OK (skipped=1)`） |
| 3 | Bot 端到端（假 API + 真 PTB） | 包含在第 1 项 | 6/6 通过 |
| 4 | 真实 MySQL 集成 | 包含在第 2 项 | 3/3 通过 |
| 5 | Bot + MySQL 全栈 | 包含在第 2 项 | 1/1 通过 |
| 6 | 离线 demo | `python demo.py` | 全流程通过，输出 `全部完成 ✅` |
| 7 | MySQL 冒烟 | `VERIFY_LAB_MYSQL=1 python scripts/smoke_mysql.py` | 10/10 通过 |
| 8 | Docker 容器自检 | `docker compose --profile bot run --rm --no-deps bot python bot.py --check` | 通过（`DB_BACKEND=mysql`） |
| 9 | 出站 Telegram 连通 | 假 Token 运行 `bot.py --check` | `HTTP 401`，退出码 1（预期） |
| 10 | 无 Token 自检 | `python bot.py --check` | 通过，Token 项为警告，退出码 0 |
| 11 | `.env` 加载 | 临时写入假 Token 的 `.env` 后 `bot.py --check` | 读到 Token 与管理员 ID，返回 HTTP 401（预期）；临时文件已删除 |
| 12 | 真实 Token `getMe` | 真实 Token 运行 `bot.py --check` | ✅ `@yunbian666_bot`（id 9088234520） |
| 13 | 真实 Bot 轮询 | `.venv/bin/python bot.py` | ✅ `Application started`，无 webhook 冲突、无待处理积压 |

> 第 1 项的 6 个跳过 = 真实 MySQL 集成 3 + Bot+MySQL 全栈 1 + `TestRealMySQL` 2（其中 1 个是「缺驱动时跳过」的自检用例）。
> 第 2 项唯一跳过的是「缺驱动时跳过」用例——驱动已安装，所以按设计跳过。

## 逐项证据

### 1. Bot 端到端（`tests/test_bot_e2e.py`，6 个用例）

真实 PTB `Application` 轮询本地仿真 API，覆盖：

1. 用户主链路：`/start` → `/balance` → `/qd` ×2 → 管理员 `/genkey` → `/listkeys` → `/redeem` → 重复兑换被拒 → `/verify` → 收到 PNG → `/help`；断言余额 6、认证记录 `success`、PNG 文件头与 caption。
2. 邀请奖励：邀请人 +3、被邀请人 +1。
3. 网关异常：扣分后 mock 抛 `GatewayError` → 自动退分 → 记录 `failed`。
4. 管理员权限与黑名单：非管理员拒绝、拉黑/解除、黑名单列表、`/stats`、未注册用户拦截。
5. 卡密错误路径：不存在、过期、次数耗尽、余额不足、未知命令、普通文本。
6. 广播：两个用户都收到，管理员看到「广播完成：成功 2/2」。

### 2. 真实 MySQL 集成（`tests/test_mysql_integration.py`，3 个用例）

- 全链路 + `datetime` 归一化：注册、邀请、签到、卡密四种状态、过期、`admin.listkeys`、拉黑/解除、认证记录、计数；断言 `created_at` / `last_checkin` / `expire_at` 均为 ISO 字符串。
- 20 线程并发扣 10 分：**恰好 10 次成功，余额 0，无负数**。
- 20 用户抢 `max_uses=3` 的卡密：**恰好 3 次成功，`current_uses=3`，无超发**。

### 3. Bot + MySQL 全栈（`tests/test_bot_mysql_e2e.py`，1 个用例）

真实 PTB + 仿真 Bot API + 真实 MySQL + Pillow 渲染：
`/start` → `/qd` → `/genkey` → `/redeem` → `/listkeys` → `/verify`，断言证书 PNG、余额 6、时间字段为字符串、认证记录 `success`，teardown 精确清理 MySQL 行。

### 4. 证书渲染

| 后端 | 文件 | 尺寸 | 结果 |
|---|---|---|---|
| Playwright Chromium | `outputs/VL-2026-0001.png` | 2160×1520，101,877 字节 | 肉眼核对：中文姓名、课程、`SAMPLE`、免责声明均正确 |
| Pillow（Noto CJK） | `app/outputs/_selfcheck/VL-SELFCHECK.png` | 1000×700，46,609 字节 | 肉眼核对：中文正常，无豆腐块 |

### 5. Docker

容器内自检输出：

```text
数据库后端：mysql
[✓] 数据库连通：用户 0 / 卡密 0 / 认证记录 0
[✓] 证书渲染：/data/outputs/_selfcheck/VL-SELFCHECK.png (1000x700, 46739 bytes)
[✓] 本地审核状态机：REWARD-LAB000001
[!] Telegram Token：未设置 BOT_TOKEN（真实联网测试需要它）
自检通过 ✅（未做真实联网消息测试）
```

镜像基于 `python:3.13-slim`，安装 `fonts-noto-cjk` 与 `tzdata`，非 root 用户运行。

### 6. `.env` 启动路径

测试中发现并修复了一个真实启动 bug：`app/bot_service.py` 把 `.env` 路径算成了 `app/.env`，
导致按 README 把 `.env` 放在 `verify-lab/` 根目录时**不会被读取**。修复后：

- 默认从 `verify-lab/.env` 读取；
- 默认输出目录回到 `verify-lab/outputs/`；
- 新增 `tests/test_env.py` 的 4 个用例，锁定默认路径、注释/引号/`export` 解析、环境变量优先级、缺文件行为。

手动验证：临时写入假 Token 的 `.env` 后运行 `bot.py --check`，正确读到 Token 与 `ADMIN_USER_ID=9000`，`getMe` 返回 HTTP 401（预期，Token 是假的），随后已删除临时 `.env`。

### 7. 墨菲定律加固（全部有测试锁定）

| # | 故障注入 | 修复前表现 | 修复 | 对应测试 |
|---|---|---|---|---|
| 1 | 查看运行日志 | httpx 把 `/bot<TOKEN>/getMe`、`getUpdates` 完整 URL 打进日志，Token 出现 3 次 | 统一日志脱敏 Formatter，httpx/httpcore 降为 WARNING；复测 Token 出现 0 次 | `test_hardening.py::LoggingHardeningTest` |
| 2 | 姓名/课程传 `<script>`、`<img onerror>` | 原样拼进证书 HTML | `html.escape` + 截断 + 空白归一 | `test_html_injection_is_escaped` |
| 3 | 证书编号传 `../../evil` | 直接作为输出文件名，可写出输出目录 | 文件名白名单化，`../../evil` → `evil.png`，断言父目录不变 | `test_long_text_and_serial_cannot_break_layout_or_path` |
| 4 | 姓名 100 字、课程 200 字 | 文字溢出证书边界 | 姓名 48 字/课程 80 字截断 + Pillow 字体逐级缩小 | 同上 |
| 5 | `getMe` 首次超时 | 直接判 Token 失败 | 瞬时异常重试 3 次（指数退避），HTTP 401 不重试 | `TelegramCheckHardeningTest` |
| 6 | Bot 启动瞬间断网 | `ConnectError` 直接退出进程 | 捕获 `NetworkError`/`TimedOut`，5s 起指数退避重建 Application | `StartupRetryHardeningTest` |
| 7 | `/genkey K 10 1 -1`、超大积分/次数/天数、101 字卡密 | 0 天被标成"永久"、超大天数 `OverflowError`、超长卡密触发 MySQL `VARCHAR(100)` 错误 | 积分/次数 1..1,000,000，天数 1..3650，卡密 1..100 字，非法输入中文提示 | `test_admin_genkey_bounds` |
| 8 | `/addbalance 1 0`、`/addbalance 1 1000001` | 0 分空操作、超大值可能溢出 INT | 拒绝 0 与绝对值超过 1,000,000 的调整 | `test_admin_add_balance_bounds` |
| 9 | `/broadcast` 发 4001 字 | 每个用户都发送失败 | 4000 字上限，超长直接提示拆分 | `test_broadcast_targets` |
| 10 | `/listkeys` / `/blacklist` 用户很多 | 单条超过 Telegram 4096 字上限，发送失败 | 按换行自动拆成多条（每段 ≤4000 字） | `MessageLengthHardeningTest` |
| 11 | 同时起两个 Bot 进程 | `409 Conflict: terminated by other getUpdates`，两个实例互相踢 | 运维约束：单实例运行；本轮已清理重复进程并重启单一实例 | 手工复现并验证 |

> Token 从未写进文档、git、数据库或命令行参数；只存在于 `verify-lab/.env`（权限 600，已被 `.gitignore` 覆盖）。

### 8. 数据清理

测试与冒烟结束后，真实 MySQL 中 `users=0`、`card_keys=0`、`card_key_usage=0`、`verifications=0`（该 schema 无独立黑名单表，黑名单是 `users` 字段）。测试使用随机 user_id/卡密并精确删除，不依赖清库。

## 真实 Telegram 的最后一步

Token 已收到并验证：`getMe` 返回 `@yunbian666_bot`（id 9088234520），Bot 已在本机轮询运行。
剩下的入站闭环只差一条用户消息：

1. 主人在 Telegram 里给 `@yunbian666_bot` 发 `/start`。
2. Bot 会自动注册并回复「注册成功」；此时数据库 `users` 表出现真实 user id。
3. 把这个 id 写进 `verify-lab/.env` 的 `ADMIN_USER_ID`，重启 Bot。
4. 再发 `/balance`、`/qd`、`/verify 测试课程` 和管理员 `/genkey`、`/stats`，即可完成真实 `sendMessage` + `sendDocument` 验收。

**为什么不能由我主动完成**：Telegram Bot API 不允许 Bot 主动给从未与它建立会话的用户发私聊；没有 `chat_id` 就没有合法的发送目标。不使用其他生产配置里的 chat_id，也不复用别人的 Token。

Token 只保存在 `verify-lab/.env`（600）；测试完成后建议在 BotFather 里 `/revoke` 轮换。

## 本次未做（且不会做）

- 未接真实 SheerID API，未复现真实审核通道。
- 未生成可用于认证的学生证、学校系统截图或任何身份材料。
- 未提交任何真实个人信息。
- 未改动 NAS/tx 的任何生产容器或服务。

## 已知限制

- 本地仿真 API 覆盖 Bot 所需的 6 个端点（`getMe`、`deleteWebhook`、`getUpdates`、`sendMessage`、`editMessageText`、`sendDocument`），不覆盖 Telegram 全部 API；对本项目的命令链路已足够。
- 仿真环境下 `sendDocument` 校验的是 multipart 内容与 PNG 文件头，不校验 Telegram 服务端的内容审核策略。
- MySQL 时间字段已统一为 ISO 字符串；若直接查库仍会看到 `DATETIME` 原生类型，这是预期。
