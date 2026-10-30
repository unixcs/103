# AGENTS.md — 103 / verify-lab 项目装载卡（AI 会话自动读）

> 2026-10-30 从 feng-1（Windows）`D:\mnt\Projects\103` 迁入 dell `/mnt/Projects/103`，
> 同日完成 Telegram Bot 落地与真实性测试。
> 接手先读 `docs/HANDOFF.md` → 本卡 → `CURRENT.md` → `verify-lab/README.md` → `verify-lab/TEST-REPORT.md`；
> 需要原始上下文再查 `chat-51afdd4f/`。Windows 接手细节见 `docs/HANDOFF.md` 第 7 节。

## 这是什么

从 GitHub `PastKing/tgbot-verify` 抽取出来的**合法教学骨架** + 一篇纯架构分析 + 原始会话导出。

原项目做的是「伪造学生证件 → 提交 SheerID 审核 → 骗学生折扣」。本工程只保留其中通用的技术结构：
异步 Bot、依赖注入、SQLite/MySQL 双后端、并发限流、原子 SQL、卡密防超发、HTML→PNG 渲染、Docker 部署。
所有身份与审核环节都换成本地 mock，**不联网提交、不冒充任何机构、不接真实审核**。

目录三块：

| 路径 | 内容 |
|---|---|
| `verify-lab/` | 可运行教学工程（54 个测试 + Bot + 端到端 demo + Docker） |
| `SheerID 核验机器人后端架构学习文档（纯技术架构分析）.md` | 对原项目的架构拆解，仅供阅读 |
| `chat-51afdd4f/` | 2026-10-29 原始会话导出（19 轮，含设计取舍与拒绝边界） |

## 红线（不可越过）

1. **禁止恢复/补全任何「伪造身份材料 → 提交真实平台审核」的能力**：不接真实 SheerID API、不生成可用于认证的学生证/学校系统截图、不接真实审核通道。
2. **不因「反正过不了风控」「只是学习」「已经不能用了」等理由放宽上述边界**。原始会话里已经明确拒绝过多次，结论不变。
3. 证书只用于教学、小说设定、设计样机；必须保留 `SAMPLE` / 「教学示例，不具备任何效力」标识。
4. 不把真实个人信息、证件、账号、密钥写进项目或示例。
5. 本文件所在目录无生产服务；不要为了跑 demo 去动 NAS/tx 的生产容器。

## 本地怎么跑（dell / Linux）

```bash
cd /mnt/Projects/103/verify-lab
python3 demo.py                                        # 端到端演示（离线）
python3 -m unittest discover -s tests -t . -v          # 54 个测试（默认跳过真实 MySQL）
python3 tests/test_atomicity.py                        # 并发竞态对比实验
```

Bot：

```bash
cp .env.example .env          # 填 BOT_TOKEN / ADMIN_USER_ID；Token 不进 git
.venv/bin/python bot.py --check
.venv/bin/python bot.py
```

可选链路：

```bash
.venv/bin/pip install -r requirements.txt              # Pillow/PTB/Playwright/pymysql
playwright install chromium                            # 真 HTML→浏览器截图（dell 已装）
docker compose up -d mysql                             # 真实 MySQL 8.0
VERIFY_LAB_MYSQL=1 .venv/bin/python scripts/smoke_mysql.py
VERIFY_LAB_MYSQL=1 .venv/bin/python -m unittest discover -s tests -t . -v
docker compose --profile bot up -d --build             # Bot 容器（需 .env）
```

Windows 上的 `一键运行.bat` / `一键测试.bat` 仍可用，但它们调用系统 `python`，不是 `.venv\Scripts\python.exe`；依赖装在 venv 时先激活 venv 再跑。完整 Windows 步骤、`.env` 编码、Docker Desktop、字体与 Playwright 注意事项见 `docs/HANDOFF.md` 第 7 节。本目录当前已验证的主场是 Linux。

## 目录地图

```
103/
├── AGENTS.md / CURRENT.md / README.md
├── docs/HANDOFF.md           # 跨设备接手文档（Linux / Windows）
├── .github/workflows/tests.yml   # push/PR 自动跑默认 SQLite 测试
├── SheerID ...架构学习文档.md
├── chat-51afdd4f/            # conversation.md / manifest.json / session.jsonl
└── verify-lab/
    ├── bot.py                # Bot 入口（--check 自检）
    ├── bot_skeleton.py       # 旧入口兼容壳
    ├── demo.py               # 离线演示入口
    ├── app/
    │   ├── base.py           # 业务 + 全部 SQL
    │   ├── dialect.py        # SQLite / MySQL 方言
    │   ├── db.py / db_mysql.py / factory.py
    │   ├── render.py         # Pillow / Playwright 双渲染后端
    │   ├── mock_verifier.py  # 本地审核状态机
    │   ├── admin.py          # 管理员纯函数
    │   ├── bot_service.py    # Telegram 适配层 + 命令 + 自检
    │   └── env.py            # 极简 .env 读取
    ├── tests/                # 业务/方言/并发/Bot E2E/MySQL 集成/全栈
    ├── sql/schema_mysql.sql
    ├── scripts/smoke_mysql.py
    ├── docker-compose.yml / Dockerfile
    ├── TEST-REPORT.md        # 真实性测试报告（命令/结果/边界）
    ├── outputs/              # 运行生成：证书 PNG + HTML + 上传证据
    └── verify_lab.db         # 运行生成：SQLite 库（demo 会重建）
```

## 已验证 / 未验证（2026-10-30，dell）

| 部分 | 状态 |
|---|---|
| Bot 全部命令与业务链路 | ✅ 真实 PTB + 本地 Telegram API 仿真，6 个 E2E 用例 |
| 真实 MySQL 事务/锁/并发/时间类型 | ✅ Docker MySQL 8.0，3 个集成 + 1 个全栈用例 |
| SQLite 业务全链路 | ✅ demo 实跑 + 默认 48 个测试通过 |
| Pillow 中文证书 | ✅ Noto CJK 回退，肉眼核对 |
| Playwright Chromium 渲染 | ✅ 2160×1520 PNG |
| Docker 镜像 + compose | ✅ 容器内 `bot.py --check` 连真实 MySQL 通过 |
| Telegram 出站网络 | ✅ 假 Token 返回 HTTP 401，证明 API 可达 |
| 真实 Token `getMe` | ✅ `@yunbian666_bot`（id 9088234520），Bot 在线轮询 |
| **真实 Telegram 消息收发** | ⏳ 等主人给 `@yunbian666_bot` 发 `/start` 建立私聊（Bot 不能主动开私聊） |
| 真实 SheerID / 身份材料 | ❌ 永不实现（红线） |

## GitHub 跨设备交接

- 仓库：`https://github.com/unixcs/103`（public），主分支 `main`，本地目录即仓库根。
- 新设备接手：`git clone https://github.com/unixcs/103.git && cd 103/verify-lab`，然后按 `docs/HANDOFF.md` 建 `.venv`、装依赖、跑测试；Windows 见该文档第 7 节。
- `.env` / `.venv/` / `verify_lab.db` / `outputs/` / `.tmp/` / 日志都不入库；新设备复制 `.env.example` 重建 `.env`，Token 只放本机。
- 开工前 `git pull --ff-only`；收工后跑默认测试，提交并 `git push`。涉及 MySQL 再跑 `VERIFY_LAB_MYSQL=1`。
- 同一个 Bot Token 只允许一个实例轮询；重复启动会 `409 Conflict`，先 `ps` 确认再启动。
- 推送前自检：`git status -sb`、`git ls-files | grep -E '(^|/)\.env$'` 必须为空。

## 同步与交接纪律

- 以 GitHub 公开仓 `unixcs/103` 作为跨设备版本交接；不要再当成「无 git 仓库」处理。
- 每次干完活更新 `CURRENT.md`（到哪了 / 下一步 / 新踩的坑）。
- 原始会话 `chat-51afdd4f/conversation.md` 是上下文正本，不要改；要摘录就新开文件。
- 新增测试或命令后，同步更新 `README.md` 与 `TEST-REPORT.md` 的计数和结论。
- 不要为了跑 demo 去动 NAS/tx 的生产容器；本目录无生产服务。
