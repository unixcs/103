# 103 — verify-lab 教学工程

从 `PastKing/tgbot-verify` 抽出来的**合法教学骨架**：保留异步 Telegram Bot、SQLite/MySQL 双后端、原子扣分、卡密防超发、HTML→PNG 渲染、Docker 部署这些通用技术结构；把原项目的「伪造学生证件 → 提交 SheerID 审核」全部换成本地 mock。

> **红线**：不接真实 SheerID，不生成可用于认证的学生证/学校系统截图，不提交任何真实身份材料。证书只用于教学、小说设定、设计样机，并始终保留 `SAMPLE` /「教学示例，不具备任何效力」。

## 现在有什么

> 跨设备接手先看 [`docs/HANDOFF.md`](docs/HANDOFF.md)：Linux / Windows 的完整步骤、已知坑、验收清单都在里面。

| 能力 | 状态 |
|---|---|
| Telegram Bot 全部用户/管理员命令 | ✅ 已实现 |
| 本地 Telegram Bot API 仿真 + 真实 PTB 端到端 | ✅ 6 个 E2E 用例 |
| 真实 MySQL 8.0 事务/行锁/并发 | ✅ 3 个集成 + 1 个全栈用例 |
| SQLite 零配置全链路 | ✅ demo + 默认测试 |
| Pillow 中文证书 / Playwright 浏览器渲染 | ✅ 双后端 |
| Docker 镜像 + compose（MySQL / Bot） | ✅ 已实测 |
| 测试总数 | **54 个**（默认 48 通过 + 6 跳过；MySQL 53 通过 + 1 跳过） |
| 真实 Token / 入站消息 | Token 已验证；入站需用户先给 Bot 发 `/start` |

## 快速开始

```bash
git clone https://github.com/unixcs/103.git
cd 103/verify-lab

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 离线端到端演示
python3 demo.py

# 默认 SQLite 全量测试（真实 MySQL 用例自动跳过）
.venv/bin/python -m unittest discover -s tests -t . -v
```

连真实 MySQL：

```bash
docker compose up -d mysql
VERIFY_LAB_MYSQL=1 .venv/bin/python scripts/smoke_mysql.py
VERIFY_LAB_MYSQL=1 .venv/bin/python -m unittest discover -s tests -t . -v
```

## 启动 Telegram Bot

```bash
cd verify-lab
cp .env.example .env          # 填 BOT_TOKEN / ADMIN_USER_ID
.venv/bin/python bot.py --check
.venv/bin/python bot.py
```

`BOT_TOKEN` 只放本机 `.env`，**不要提交**。Bot 不能主动给未建立会话的用户发私聊，必须先由用户在 Telegram 里发 `/start`。

## 跨设备接手顺序

1. 先读 [`docs/HANDOFF.md`](docs/HANDOFF.md)（完整接手文档：状态、Linux/Windows 步骤、坑、验收清单）。
2. 再读 [`AGENTS.md`](AGENTS.md)（30 秒装载卡：红线、命令、目录、已验证状态）。
3. 再读 [`CURRENT.md`](CURRENT.md)（最近到哪了、已知坑、下一步）。
4. 需要细节进 [`verify-lab/README.md`](verify-lab/README.md) 和 [`verify-lab/TEST-REPORT.md`](verify-lab/TEST-REPORT.md)。
5. 原始设计上下文在 [`chat-51afdd4f/`](chat-51afdd4f/)，只读，不要改。

Windows 接手要点（详见 HANDOFF 第 7 节）：

- 克隆到纯英文、非 OneDrive 路径，例如 `D:\Projects\103`。
- 用 `py -3.13 -m venv .venv`，激活 `.venv\Scripts\Activate.ps1`，之后统一用 `python`。
- `.env` 用 `copy .env.example .env` 生成，保存为 UTF-8 **无 BOM**。
- 两个 `.bat` 脚本调用系统 `python`，若依赖只装在 `.venv`，请先激活 venv 或用 `.venv\Scripts\python.exe`。

跨设备约定：

- 开工前 `git pull --ff-only`，收工后提交并 `git push`。
- `.env`、`.venv/`、`verify_lab.db`、`outputs/`、`.tmp/`、日志都不入库；新设备按 `.env.example` 重建。
- 同一个 Bot Token 只允许一个实例轮询，重复启动会 `409 Conflict`。
- 推送前跑一遍默认测试；涉及 MySQL 再跑 `VERIFY_LAB_MYSQL=1`。

## 目录

```text
103/
├── AGENTS.md                     # AI 会话装载卡 / 红线 / 命令
├── CURRENT.md                    # 热状态与下一步
├── README.md                     # 本文件
├── docs/HANDOFF.md               # 跨设备接手文档（Linux / Windows）
├── SheerID ...架构学习文档.md     # 原项目纯技术架构分析
├── chat-51afdd4f/                # 2026-10-29 原始会话导出（只读上下文）
└── verify-lab/                   # 可运行教学工程
    ├── app/                      # 业务、数据层、渲染、mock 审核、Bot 适配
    ├── tests/                    # 业务/方言/并发/Bot E2E/MySQL 集成/墨菲加固
    ├── sql/                      # MySQL schema
    ├── scripts/                  # MySQL 冒烟
    ├── docker-compose.yml
    ├── Dockerfile
    ├── README.md
    └── TEST-REPORT.md
```

## 安全

- `.env`、数据库、生成证书、日志均由 `.gitignore` 排除；仓库里只有 `.env.example`。
- 如果 Token 曾经出现在聊天/日志里，测试完成后去 BotFather `/revoke` 轮换。
- 本仓库当前为 **public**。公开前已扫描 Token / PAT / 云密钥 / 私钥 / 手机号 / 身份证号 / 内网 IP，均未发现。
- `chat-51afdd4f/` 是原始会话导出，含上游项目代码和本机路径等背景信息（无密钥）；如果以后不想公开，删除该目录或把仓库改回 private。
