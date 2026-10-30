# verify-lab —— 从 tgbot-verify 里抽出来的「合法教学骨架」

> 配套 <https://github.com/PastKing/tgbot-verify> 代码导读的**可运行教学版**。
> 原项目做的是「伪造学生证件 → 提交 SheerID 审核 → 骗学生折扣」；本工程只保留通用技术结构，
> 业务内容换成「生成教学结业证书」，审核换成本地 mock，**不接真实 SheerID、不生成可用假证、不提交任何真实审核**。

## 现在能跑到哪一步

2026-10-30 在 dell（Linux）完成落地与真实性测试：

| 能力 | 状态 |
|---|---|
| Telegram Bot 完整命令与业务链路 | ✅ 已实现（`bot.py` / `app/bot_service.py`） |
| 真实 Telegram Bot API 出站连通 | ✅ 已打通（假 Token 返回 401，证明 `api.telegram.org` 可达） |
| 真实 Token | ✅ `@yunbian666_bot`（id 9088234520），`getMe` 通过，Bot 已在线轮询 |
| 真实 Telegram 消息收发 | ⏳ 等主人给 `@yunbian666_bot` 发 `/start` 建立私聊（Bot 不能主动开私聊） |
| SQLite 全链路 | ✅ demo + 48 个默认测试通过 |
| 真实 MySQL 8.0（Docker） | ✅ 建表/事务/行锁/并发/时间类型全部实测 |
| Pillow 中文证书渲染 | ✅ Linux Noto CJK 字体，肉眼核对 |
| Playwright Chromium 渲染 | ✅ HTML → 真实浏览器截图 |
| Docker 镜像 + compose | ✅ 容器内 `bot.py --check` 连真实 MySQL 通过 |
| 伪造学生身份 / 真实 SheerID | ❌ 永不实现（见 AGENTS.md 红线） |

完整命令、输出与证据见 [`TEST-REPORT.md`](TEST-REPORT.md)。

## 快速开始（Linux）

```bash
cd verify-lab

# 1. 端到端 demo（离线，不需要 Token）
python3 demo.py

# 2. 全部测试（默认 SQLite；真实 MySQL 用例自动跳过）
python3 -m unittest discover -s tests -t . -v

# 3. 只跑并发竞态实验
python3 tests/test_atomicity.py
```

依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`Pillow` 必需；`python-telegram-bot` 只在跑 Bot 时需要；`playwright` 只在用浏览器渲染后端时需要；
`pymysql` + `cryptography` 只在连 MySQL 时需要。

## 启动 Telegram Bot

### 1. 准备 Token 与管理员 ID

在 Telegram 里找 `@BotFather` 建一个**你自己的测试 Bot**，拿 Token。
管理员 ID 可以找 `@userinfobot` 查，或先启动 Bot 后看日志里的 `from.id`。

```bash
cd verify-lab
cp .env.example .env
# 编辑 .env：
#   BOT_TOKEN=123456:ABC...
#   ADMIN_USER_ID=你的数字ID
```

Token 只从环境变量或 `.env` 读取，**不会写进数据库、日志或 git**。

### 2. 先做启动自检

```bash
.venv/bin/python bot.py --check
```

会检查：数据库连通（只读计数）、Pillow 中文渲染、本地审核状态机、可选的真实 Telegram `getMe`。
任一项失败会返回非 0，并在最后列出原因。

### 3. 启动

```bash
.venv/bin/python bot.py
```

默认 SQLite。要连 MySQL：

```bash
DB_BACKEND=mysql MYSQL_HOST=127.0.0.1 MYSQL_USER=lab MYSQL_PASSWORD=labpass \
  MYSQL_DATABASE=verify_lab .venv/bin/python bot.py
```

### 4. 在 Telegram 里验收

先给 `@yunbian666_bot` 发一句 `/start`（Bot 不能主动给没建立会话的人发私聊）。
然后在私聊里依次发送：

```text
/start
/balance
/qd
/qd
/verify Python 入门
/help
```

管理员再发：

```text
/genkey TESTKEY 5 10
/listkeys
/stats
```

然后普通用户 `/redeem TESTKEY`，余额 +5，再用 `/verify` 消耗 1 分并收到证书 PNG。
证书上保留 `SAMPLE` 与「教学示例，不具备任何效力」。

## Bot 命令

| 命令 | 谁可用 | 作用 |
|---|---|---|
| `/start [邀请码]` | 所有人 | 注册；填邀请码时邀请人 +3、被邀请人 +1 |
| `/help` | 已注册 | 命令说明 |
| `/balance` | 已注册 | 查余额与签到状态 |
| `/qd` | 已注册 | 每日签到 +1（重复签到被拒） |
| `/redeem <卡密>` | 已注册 | 兑换卡密积分（每人每卡一次，卡密有次数/有效期） |
| `/verify <课程名>` | 已注册 | 扣 1 分 → 本地 mock 审核 → 生成证书 PNG |
| `/addbalance <用户ID> <分数>` | 管理员 | 加/减余额 |
| `/block <用户ID>` / `/white <用户ID>` | 管理员 | 拉黑 / 解除 |
| `/blacklist` | 管理员 | 查看黑名单 |
| `/genkey <前缀> <积分> [次数] [天数]` | 管理员 | 生成卡密 |
| `/listkeys` | 管理员 | 查看卡密及到期状态 |
| `/stats` | 管理员 | 用户/卡密/认证记录统计 |
| `/broadcast <文本>` | 管理员 | 给所有未拉黑用户群发 |

设计约定：

- 只接受**私聊**；群聊里的命令会被忽略，避免在公开场合泄露余额与卡密。
- 所有数据库、渲染、网关调用都走 `asyncio.to_thread`，不阻塞事件循环。
- `/verify` 失败（网关异常、审核拒绝）**自动退分**并记录 `failed`，不会出现「扣了分没证书」。
- 并发扣分用原子 SQL；卡密用行锁 + `card_key_usage` 联合主键双重防超发。
- 姓名/课程会做 HTML 转义、长度截断与字体缩放；证书编号会白名单化，防止注入和路径穿越。
- 日志统一脱敏 Bot Token；超长列表消息按行拆成多条，避免超过 Telegram 4096 字上限。

## 技术结构

```
app/base.py        业务逻辑 + 全部 SQL（SQLite/MySQL 只写一遍，{p} 占位符）
app/dialect.py     方言：占位符、NOW()、CURDATE()、BEGIN IMMEDIATE / FOR UPDATE
app/db.py          SQLite 后端（默认，零配置）
app/db_mysql.py    MySQL 后端（已实测）
app/factory.py     make_database()：按 DB_BACKEND 选后端
app/render.py      HTML 模板 → PNG（Pillow 零依赖 / Playwright 浏览器双后端）
app/mock_verifier.py  本地多步审核状态机（上传 → 轮询 → 通过/拒绝）
app/admin.py       管理员业务纯函数（不 import telegram，可直接单测）
app/bot_service.py Telegram 适配层 + 全部命令 + 启动自检
app/env.py         极简 .env 读取（无第三方依赖）
bot.py             Bot 入口：python bot.py [--check]
bot_skeleton.py    旧入口兼容壳，等价于 bot.py
demo.py            离线端到端演示
```

三个关键的正确性设计：

1. **原子扣分**：`UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?`，看 `rowcount`，不做「先查后写」。
2. **卡密防超发**：SQLite `BEGIN IMMEDIATE` / MySQL `SELECT ... FOR UPDATE`，加 `card_key_usage(user_id, key_id)` 联合主键。
3. **同步库不进事件循环**：Bot 层所有阻塞调用都包 `asyncio.to_thread`。

## 真实 MySQL / Docker

```bash
# 起库（首次自动执行 sql/schema_mysql.sql）
docker compose up -d mysql

# 等 healthy 后跑冒烟（随机数据，跑完自清理）
VERIFY_LAB_MYSQL=1 .venv/bin/python scripts/smoke_mysql.py

# 连真实 MySQL 的测试（3 个集成 + 1 个 Bot 全栈）
VERIFY_LAB_MYSQL=1 .venv/bin/python -m unittest discover -s tests -t . -v
```

Bot 容器：

```bash
cp .env.example .env    # 填 BOT_TOKEN / ADMIN_USER_ID
docker compose --profile bot up -d --build
docker compose logs -f bot
```

容器内已装 `fonts-noto-cjk`，`RENDER_BACKEND=pillow` 可离线出中文证书。

## 文件地图

```
verify-lab/
├── bot.py                    # Bot 入口
├── bot_skeleton.py           # 旧入口兼容壳
├── demo.py                   # 离线演示入口
├── app/                      # 业务、数据层、渲染、审核 mock、Bot 适配
├── tests/
│   ├── test_lab.py           # 业务单测
│   ├── test_backends.py      # 方言 / SQL 形状 / 工厂 / 真实 MySQL 冒烟
│   ├── test_atomicity.py     # 并发竞态对比实验
│   ├── test_env.py           # .env 解析与默认路径
│   ├── test_hardening.py     # 注入/超长/日志脱敏/网络抖动/启动重试
│   ├── test_bot_e2e.py       # 本地假 Bot API 的 6 个端到端用例
│   ├── test_mysql_integration.py  # 真实 MySQL 全链路 + 并发原子性
│   ├── test_bot_mysql_e2e.py      # 真实 MySQL + 真实 PTB + 假 API 全栈
│   └── fake_telegram_api.py       # 线程安全的本地 Telegram Bot API 仿真
├── sql/schema_mysql.sql
├── scripts/smoke_mysql.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── TEST-REPORT.md            # 真实性测试报告（命令 + 结果 + 边界）
├── outputs/                  # 运行生成：证书 PNG / HTML / 上传证据
└── verify_lab.db             # 运行生成：SQLite 库（demo 会重建）
```

## 教学练习

1. 把 `app/base.py` 的 `deduct_balance` 改回「先查后写」，跑 `test_atomicity.py`，看余额变负。
2. 给 `render.py` 加一个新模板（如「参训证明」），只改 HTML + 参数。
3. 给 `mock_verifier.py` 加规则：「姓名必须与申请人一致」，让审核真的会拒绝。
4. 用 pytest 重写 `test_atomicity.py`，补 fixture 与断言。

## 边界

- 不接真实 SheerID，不实现真实身份材料生成/提交。
- 证书只用于教学、小说设定、设计样机，必须保留 `SAMPLE` / 「教学示例，不具备任何效力」。
- 不把真实个人信息、证件、账号、密钥写进项目。
- 不为了跑本工程去动 NAS/tx 的生产容器。
