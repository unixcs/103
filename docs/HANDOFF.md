# 103 接手文档（HANDOFF）

> 更新时间：2026-10-30  
> 适用环境：Linux（当前已验证）/ Windows（待实机验证）  
> 仓库：<https://github.com/unixcs/103>（public，`main` 分支）

这份文档的目标：**新设备、新会话、新接手人，读完这一份就能知道项目是什么、做到哪、怎么跑、哪里有坑、下一步干什么。**

---

## 0. 一句话结论

`103` 是从 `PastKing/tgbot-verify` 抽出来的**合法教学骨架**：保留 Telegram Bot、SQLite/MySQL 双后端、原子扣分、卡密防超发、HTML→PNG 渲染、Docker 部署这些通用技术结构；把原项目的「伪造学生证件 → 提交 SheerID 审核」全部换成本地 mock。

**它不是原项目的可用伪造工具，也不允许被改回那个方向。**

---

## 1. 先看哪里（接手顺序）

1. 本文件：全局状态、Linux/Windows 差异、坑、下一步。
2. [`AGENTS.md`](../AGENTS.md)：AI 会话装载卡、红线、目录地图。
3. [`CURRENT.md`](../CURRENT.md)：热状态（最近到哪了）。
4. [`verify-lab/README.md`](../verify-lab/README.md)：工程细节、命令、文件地图。
5. [`verify-lab/TEST-REPORT.md`](../verify-lab/TEST-REPORT.md)：真实性测试证据。
6. [`chat-51afdd4f/`](../chat-51afdd4f/)：2026-10-29 原始会话导出，只读背景，不要改。

---

## 2. 项目是什么 / 不是什么

### 2.1 原项目做了什么

上游 `PastKing/tgbot-verify` 的链路大致是：

```text
Telegram Bot 接单
  → 生成/伪造学生身份信息
  → 生成学生证或学校系统截图
  → 提交 SheerID 审核
  → 拿到学生折扣
```

### 2.2 本工程保留了什么

只保留通用技术结构：

- 异步 Telegram Bot（python-telegram-bot）
- 用户/管理员命令、私聊守卫、黑名单
- SQLite / MySQL 双后端
- 原子扣分、行锁、卡密防超发
- 本地 mock 审核状态机
- HTML 模板 → PNG 证书（Pillow / Playwright 双后端）
- Docker 镜像 + compose
- 测试与 CI

### 2.3 本工程永远不做什么（红线）

1. **不接真实 SheerID API**，不接任何真实审核通道。
2. **不生成可用于认证的学生证、学校系统截图、身份材料**。
3. **不把任何真实个人信息、证件、账号、密钥写进项目或示例**。
4. 证书只用于教学、小说设定、设计样机，必须保留 `SAMPLE` /「教学示例，不具备任何效力」标识。
5. 不因为「反正过不了风控」「只是学习」「已经不能用了」等理由放宽边界。
6. 本目录没有生产服务；不要为了跑 demo 去动 NAS/tx 的生产容器。

---

## 3. 本次接手做了什么（时间线）

### 2026-10-29：从 Windows 迁入 Linux

- 来源：feng-1（Windows）`D:\mnt\Projects\103`
- 落点：dell `/mnt/Projects/103`
- 方式：`scp -r` 全量复制
- 对账：44 个文件 SHA256 逐文件核对，44/44 一致
- 当时项目里已有：上游架构分析文档、原始会话导出、`verify-lab` 教学骨架

### 2026-10-30：接手并补完链路

完成内容：

- **Telegram Bot 全部实现**：`bot.py` / `app/bot_service.py`
  - 用户命令：`/start [邀请码]`、`/help`、`/balance`、`/qd`、`/redeem`、`/verify`
  - 管理员命令：`/addbalance`、`/block`、`/white`、`/blacklist`、`/genkey`、`/listkeys`、`/stats`、`/broadcast`
  - 私聊守卫、黑名单、未注册拦截、失败自动退分、证书 PNG 发送、广播
- **本地 Telegram Bot API 仿真**：`tests/fake_telegram_api.py`，用真实 PTB 轮询栈跑完整命令链路
- **真实 MySQL 8.0**：Docker 起库，建表、事务、`FOR UPDATE`、并发扣分/卡密防超发、`datetime` 归一化全部实测
- **Linux Pillow 中文渲染**：加 Noto CJK / DejaVu 字体回退，肉眼核对无豆腐块
- **Docker**：`Dockerfile` + compose `bot` profile（连 MySQL、装 `fonts-noto-cjk`、非 root）
- **修复 `.env` 启动路径 bug**：此前误读 `app/.env`，现在正确读 `verify-lab/.env`，输出目录也回到 `outputs/`
- **墨菲定律加固**：Token 从日志抹除、证书 HTML 注入转义、证书文件名防路径穿越、超长文本截断/字体缩放、`getMe` 与启动网络抖动重试、管理员参数上下界、超长消息自动分条
- **测试**：54 个用例（默认 48 通过 + 6 跳过；`VERIFY_LAB_MYSQL=1` 时 53 通过 + 1 跳过）
- **文档**：`verify-lab/README.md` 重写、新增 `verify-lab/TEST-REPORT.md`

### 2026-10-30：GitHub 跨设备交接

- 本地 `git init -b main`
- 首次提交：`827c71f chore: 初始化 103 教学工程与跨设备交接仓`
- 创建 GitHub 仓库 `unixcs/103`，推到 `main`
- 增加 `.gitignore`、根 README、`.github/workflows/tests.yml`
- CI 首次运行：**success**（默认 SQLite 测试）
- 仓库由 private 改为 **public**
- 新增本接手文档

---

## 4. 当前能力与验证结果

### 4.1 测试

| 场景 | 命令 | 结果 |
|---|---|---|
| 默认 SQLite | `python -m unittest discover -s tests -t . -v` | 54 个，48 通过 + 6 跳过，`OK` |
| 真实 MySQL | `VERIFY_LAB_MYSQL=1 python -m unittest discover -s tests -t . -v` | 54 个，53 通过 + 1 跳过，`OK` |
| 离线 demo | `python demo.py` | 全流程通过，`全部完成 ✅` |
| MySQL 冒烟 | `VERIFY_LAB_MYSQL=1 python scripts/smoke_mysql.py` | 10/10 通过 |
| Docker 自检 | 容器内 `python bot.py --check`（MySQL） | 通过，证书 1000×700 |
| GitHub Actions | push 后自动跑 | success |

### 4.2 真实 Telegram 状态

| 检查 | 状态 |
|---|---|
| 假 Token 调 `getMe` | HTTP 401 → `api.telegram.org` 可达 |
| 真实 Token `getMe` | ✅ `@yunbian666_bot`（id 9088234520） |
| Bot 在线轮询 | ✅ 已验证 |
| 真实入站消息 | ⏳ **等用户先给 Bot 发 `/start`** |
| 真实 `sendMessage` / `sendDocument` | ⏳ 依赖上一步拿到真实 `chat_id` |

Telegram 的规则：**Bot 不能主动给从未建立会话的用户发私聊**。所以真实入站闭环不是代码问题，只差用户在 Telegram 里给 `@yunbian666_bot` 发一句 `/start`。

### 4.3 验证边界（重要）

- **Linux（dell）已实测**：Python 3.13.5、Pillow 13.0.0、python-telegram-bot 22.8、Playwright 1.64.1、PyMySQL 1.2.3、Docker 26.1.5 / Compose 2.26.1、MySQL 8.0。
- **Windows 尚未实机验证**：代码本身是跨平台的，Windows 字体路径也已写进 `render.py`；但批处理脚本、Docker Desktop、Playwright Chromium 在 Windows 上的组合没有跑过。按本文第 7 节操作后，以实际测试结果为准。

---

## 5. 架构与关键文件

### 5.1 请求链路

```text
Telegram 用户
  → bot_service.py（命令解析 / 权限 / 私聊守卫）
  → admin.py（管理员业务纯函数）
  → base.py（业务规则 + 全部 SQL）
  → db.py / db_mysql.py（SQLite / MySQL 方言）
  → mock_verifier.py（本地审核状态机，不联网）
  → render.py（HTML 模板 → Pillow 或 Playwright → PNG）
  → outputs/（证书 PNG + HTML）
```

### 5.2 关键设计

1. **原子扣分**：`UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?`，看 `rowcount`，不做「先查后写」。
2. **卡密防超发**：SQLite `BEGIN IMMEDIATE` / MySQL `SELECT ... FOR UPDATE`，加 `card_key_usage(user_id, key_id)` 联合主键。
3. **同步库不进事件循环**：Bot 层所有阻塞调用都包 `asyncio.to_thread`。
4. **失败退分**：`/verify` 失败（网关异常、审核拒绝）自动退回积分并记 `failed`。
5. **证书安全**：姓名/课程 HTML 转义、长度截断、字体缩放；证书编号白名单化，防路径穿越。
6. **日志脱敏**：统一 Formatter 抹掉 Bot Token；httpx/httpcore 压到 WARNING。

### 5.3 关键文件

| 文件 | 作用 |
|---|---|
| `verify-lab/bot.py` | Bot 入口，`--check` 自检 |
| `verify-lab/app/bot_service.py` | Telegram 适配层 + 全部命令 + 启动自检 |
| `verify-lab/app/base.py` | 业务逻辑 + 全部 SQL |
| `verify-lab/app/dialect.py` | SQLite / MySQL 方言 |
| `verify-lab/app/db.py` / `db_mysql.py` / `factory.py` | 双后端 |
| `verify-lab/app/render.py` | Pillow / Playwright 双渲染后端 |
| `verify-lab/app/mock_verifier.py` | 本地审核状态机 |
| `verify-lab/app/admin.py` | 管理员业务纯函数 |
| `verify-lab/app/env.py` | 极简 `.env` 读取（无 python-dotenv） |
| `verify-lab/tests/fake_telegram_api.py` | 本地 Telegram Bot API 仿真 |
| `verify-lab/sql/schema_mysql.sql` | MySQL 建表 |
| `verify-lab/docker-compose.yml` | MySQL + 可选 Bot 容器 |
| `.github/workflows/tests.yml` | push/PR 自动跑默认测试 |

### 5.4 Bot 命令速查

| 命令 | 谁可用 | 作用 |
|---|---|---|
| `/start [邀请码]` | 所有人 | 注册；邀请人 +3、被邀请人 +1 |
| `/help` | 已注册 | 命令说明 |
| `/balance` | 已注册 | 查余额与签到状态 |
| `/qd` | 已注册 | 每日签到 +1（重复签到被拒） |
| `/redeem <卡密>` | 已注册 | 兑换卡密积分（每人每卡一次） |
| `/verify <课程名>` | 已注册 | 扣 1 分 → 本地 mock 审核 → 证书 PNG |
| `/addbalance <用户ID> <分数>` | 管理员 | 加/减余额 |
| `/block <用户ID>` / `/white <用户ID>` | 管理员 | 拉黑 / 解除 |
| `/blacklist` | 管理员 | 查看黑名单 |
| `/genkey <前缀> <积分> [次数] [天数]` | 管理员 | 生成卡密 |
| `/listkeys` | 管理员 | 查看卡密及到期状态 |
| `/stats` | 管理员 | 用户/卡密/认证记录统计 |
| `/broadcast <文本>` | 管理员 | 给所有未拉黑用户群发 |

只接受**私聊**；群聊命令会被忽略，避免公开泄露余额与卡密。

---

## 6. Linux 快速接手（当前已验证环境）

```bash
# 1. 克隆
git clone https://github.com/unixcs/103.git
cd 103/verify-lab

# 2. 虚拟环境 + 依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. 离线验证（不需要 Token）
python3 demo.py
.venv/bin/python -m unittest discover -s tests -t . -v

# 4. 配置 Bot（Token 只放本机）
cp .env.example .env
chmod 600 .env
# 编辑 .env：BOT_TOKEN=...  ADMIN_USER_ID=...

# 5. 自检 + 启动
.venv/bin/python bot.py --check
.venv/bin/python bot.py
```

可选 MySQL：

```bash
docker compose up -d mysql
VERIFY_LAB_MYSQL=1 .venv/bin/python scripts/smoke_mysql.py
VERIFY_LAB_MYSQL=1 .venv/bin/python -m unittest discover -s tests -t . -v
```

注意：

- 默认 SQLite，零配置；MySQL 用例默认跳过，必须显式 `VERIFY_LAB_MYSQL=1`。
- 同一个 Bot Token **只允许一个实例轮询**；重复启动会 `409 Conflict`。先确认进程再启动。
- 从 `verify-lab/` 目录启动，保证 `verify_lab.db`、`outputs/` 等相对路径落在预期位置。

---

## 7. Windows 接手注意事项（重点）

> 当前只在 Linux 实测过。以下步骤按 Windows 10/11 + PowerShell 7 或 Windows Terminal 编写；第一次接手请按「最小验收清单」逐项跑。

### 7.1 路径与终端

- 建议克隆到**纯英文、无空格、非 OneDrive 同步目录**，例如：
  ```powershell
  D:\Projects\103
  ```
- 避免 `C:\Users\张三\OneDrive\...`：OneDrive 会锁文件、同步 `.venv` 和 SQLite，容易出怪问题。
- 推荐 **Windows Terminal + PowerShell 7**；中文输出更稳。
- Windows 上没有 `python3` 命令，统一用 `python` 或 `py`。

### 7.2 Python 与虚拟环境

安装 Python 3.13（安装时勾选 **Add python.exe to PATH**），然后：

```powershell
cd D:\Projects\103\verify-lab

py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -U pip
pip install -r requirements.txt
```

如果 PowerShell 报「禁止运行脚本」：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

cmd.exe 用：

```bat
.venv\Scripts\activate.bat
```

### 7.3 `.env` 文件

```powershell
copy .env.example .env
notepad .env
```

填写：

```dotenv
BOT_TOKEN=你的BotFather Token
ADMIN_USER_ID=你的Telegram数字ID
```

注意事项：

- **必须保存为 UTF-8（不要带 BOM）**。用 VS Code 选 `UTF-8`，不要选 `UTF-8 with BOM`。
- Windows 没有 `chmod 600`。`.env` 不要提交到 Git；如需要限制本机权限，可在 cmd 里执行：
  ```bat
  icacls .env /inheritance:r /grant:r "%USERNAME%:F"
  ```
- Token 只放本机 `.env`，不要写进命令参数、截图、文档或聊天记录。
- `.env` 默认从 `verify-lab/.env` 读取，不是 `app/.env`，也不是仓库根目录。

### 7.4 运行测试与 demo

```powershell
python demo.py
python -m unittest discover -s tests -t . -v
```

预期：

- `demo.py` 最后输出 `全部完成 ✅`
- 测试 54 个：**48 通过 + 6 跳过**（跳过的是真实 MySQL 用例）
- 生成的证书在 `verify-lab\outputs\`

如果报 `ModuleNotFoundError: No module named 'telegram'` 或 `PIL`：说明没激活 `.venv`，或者依赖装到了系统 Python。先确认提示符前有 `(.venv)`。

### 7.5 证书渲染（Pillow / Playwright）

- **Pillow 后端**（推荐先跑通）：
  - 代码已优先找 Windows 字体：`C:\Windows\Fonts\msyh.ttc`（微软雅黑）、`simhei.ttf`、`simsun.ttc`。
  - 如果中文显示成方框，先确认这些字体存在；仍不行就在 `.env` 设：
    ```dotenv
    RENDER_BACKEND=pillow
    ```
- **Playwright 后端**：
  ```powershell
  python -m playwright install chromium
  ```
  - 需要下载 Chromium；公司网络/代理可能失败。
  - 失败不影响主流程：`RENDER_BACKEND=auto` 会自动回退 Pillow；也可以强制 `pillow`。
- Windows 上 Playwright 的 Chromium 与 Docker、杀毒软件偶有冲突；先跑 Pillow 验收。

### 7.6 MySQL / Docker Desktop

```powershell
docker compose up -d mysql
docker compose ps
```

- 需要 **Docker Desktop 正在运行**。
- 默认映射 `3306:3306`；如果本机已有 MySQL 占用 3306，在 `.env` 改 `MYSQL_PORT=3307` 再起。
- 首次启动会自动执行 `sql/schema_mysql.sql`；如果改过 schema，需要删除 volume 重建：
  ```powershell
  docker compose down -v
  docker compose up -d mysql
  ```
- 跑真实 MySQL 测试（PowerShell）：
  ```powershell
  $env:VERIFY_LAB_MYSQL="1"
  python -m unittest discover -s tests -t . -v
  ```
  cmd：
  ```bat
  set VERIFY_LAB_MYSQL=1
  python -m unittest discover -s tests -t . -v
  ```
- 没有 Docker 就保持默认 SQLite，不影响 48 个默认测试。

### 7.7 启动 Bot

```powershell
cd D:\Projects\103\verify-lab
.\.venv\Scripts\Activate.ps1
python bot.py --check
python bot.py
```

- 必须先让用户在 Telegram 给 `@yunbian666_bot` 发 `/start`，Bot 才能拿到 `chat_id` 做真实回复。
- 只能跑一个实例。Windows 上查重复进程：
  ```powershell
  Get-Process python* | Select-Object Id, Path
  ```
  出现 `409 Conflict` 基本就是同一个 Token 有两个进程在轮询，先停掉多余的那个。
- 停止：在运行窗口按 `Ctrl+C`。

### 7.8 两个 `.bat` 脚本的坑

仓库里有：

- `verify-lab\一键运行.bat`
- `verify-lab\一键测试.bat`

它们是早期 Windows 入口，**调用的是系统 `python`，不是 `.venv\Scripts\python.exe`**。如果你把依赖只装进了 `.venv`，双击可能报 `ModuleNotFoundError`。

推荐做法（二选一）：

1. 先激活 `.venv`，再运行：
   ```bat
   .venv\Scripts\activate.bat
   python demo.py
   ```
2. 或直接用 venv 里的解释器：
   ```bat
   .venv\Scripts\python.exe demo.py
   .venv\Scripts\python.exe -m unittest discover -s tests -t . -v
   ```

这两个 `.bat` 文件是 UTF-8 with BOM + CRLF，**不要用 ANSI 另存**，否则中文提示会乱码。

### 7.9 Git 行尾与中文路径

- Windows 建议：
  ```powershell
  git config --global core.autocrlf true
  git config --global core.quotepath false
  ```
  后者让 `git status` 正常显示中文文件名。
- 如果发现「只改了一行却整个文件都变了」，多半是 CRLF/LF 混用；先 `git diff --stat` 确认，不要盲目提交。
- `.env`、`.venv\`、`*.db`、`outputs\`、`.tmp\`、日志都已在 `.gitignore` 里；提交前仍然要跑：
  ```powershell
  git status -sb
  git ls-files | Select-String -Pattern '(^|/)\.env$'
  ```
  第二条必须没有输出。

### 7.10 Windows 最小验收清单

按顺序打勾：

- [ ] `git clone` 到 `D:\Projects\103`（非 OneDrive）
- [ ] `py -3.13 -m venv .venv`
- [ ] 激活 `.venv`，`pip install -r requirements.txt`
- [ ] `copy .env.example .env`，填 `BOT_TOKEN` / `ADMIN_USER_ID`，UTF-8 无 BOM
- [ ] `python demo.py` → `全部完成 ✅`
- [ ] `python -m unittest discover -s tests -t . -v` → 54 个，`OK (skipped=6)`
- [ ] `python bot.py --check` → 全绿
- [ ] 只启动一个 `python bot.py`
- [ ] Telegram 给 `@yunbian666_bot` 发 `/start`，确认 Bot 回复
- [ ] 跑一遍 `/balance`、`/qd`、`/verify 测试课程`
- [ ] 管理员命令只用自己的 ID，不写死别人的真实 ID

---

## 8. 密钥与公开仓库说明

### 8.1 不会入库的东西

- `verify-lab/.env`（真实 Token）
- `.venv/`
- `*.db` / `*.sqlite` / `*.sqlite3`
- `outputs/`、`.tmp/`
- 日志、`__pycache__/`
- 私钥、证书文件

仓库里只有 `.env.example` 占位模板。

### 8.2 当前公开状态

仓库已改为 **public**，并已启用 GitHub 的 **secret scanning + push protection**（以后误提交密钥会被拦）。公开前已扫描：

- 无 Telegram Bot Token
- 无 GitHub PAT
- 无 OpenAI / AWS 密钥
- 无私钥
- 无手机号、身份证号
- 无 Tailscale / 内网 IP

扫描到的邮箱只有：

- `pastking69@gmail.com`：上游作者公开信息
- `xxx.yyy123@psu.edu`：示例假邮箱
- `git@github.com`：Git SSH 地址，不是邮箱

### 8.3 公开仓库里仍然要注意

- `chat-51afdd4f/` 是**原始会话导出**，包含上游项目代码、设计讨论、Windows 本机路径（如 `C:\Users\...`）等背景信息。它没有密钥，但属于对话原文；如果以后不希望公开，可以删除该目录或把仓库改回 private。
- 架构分析文档讨论的是上游的伪造链路；本工程只做技术拆解，**不要照着文档去实现真实审核**。
- Token 曾经在聊天里出现过（不在仓库里）。真实测试结束后建议去 BotFather `/revoke` 轮换，并把新 Token 只写进本机 `.env`。
- 如果误提交了 `.env`：立即 `git rm --cached .env`、提交、轮换 Token，并检查历史（`git log -p -- .env`）；不要只删工作区文件。

### 8.4 改回 private（如果需要）

```bash
gh repo edit unixcs/103 --visibility private --accept-visibility-change-consequences
```

---

## 9. 常见故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: telegram` / `PIL` | 没激活 venv，或依赖装到系统 Python | 激活 `.venv` 后重装 |
| `409 Conflict` | 同一个 Token 有多个 Bot 实例 | `ps` / `Get-Process python*` 找到并停掉多余进程 |
| `getMe` 401 | Token 错误、已 revoke、或多了空格 | 重新从 BotFather 复制，检查 `.env` 无引号/空格问题 |
| Bot 不回复 | 用户没先 `/start`；或 Bot 没在轮询 | 先让用户发 `/start`，再看进程日志 |
| `Connection refused` 连 MySQL | Docker 没起 / 端口冲突 | `docker compose ps`；改 `MYSQL_PORT` |
| MySQL 测试全跳过 | 没设 `VERIFY_LAB_MYSQL=1` | 设置环境变量再跑 |
| 中文变方框 | 缺中文字体 / 渲染后端选错 | Windows 用微软雅黑；Linux 装 Noto CJK；设 `RENDER_BACKEND=pillow` |
| `.env` 不生效 | 文件放错目录 / BOM / 变量名拼错 | 确认 `verify-lab/.env`；UTF-8 无 BOM；先跑 `bot.py --check` |
| 证书文件名奇怪 | 证书编号被白名单化（预期） | 只保留字母数字 `._-`，其余替换为 `-` |
| GitHub Actions 失败 | 默认测试在 CI 上失败 | 本地先跑默认 54 个；看 Actions 日志 |
| `git status` 显示整个文件改动 | CRLF/LF 混用 | 检查 `core.autocrlf`，不要盲目提交 |

---

## 10. 每次接手的固定动作

```text
1. git pull --ff-only
2. 读 CURRENT.md，确认上次到哪
3. 跑默认测试（54 个）
4. 改代码 / 改文档
5. 再跑默认测试；涉及 MySQL 再跑 VERIFY_LAB_MYSQL=1
6. 更新 CURRENT.md（到哪了 / 新坑 / 下一步）
7. git status -sb；确认没有 .env / db / outputs
8. git add -A；git commit；git push
9. 需要时看 GitHub Actions 是否绿
```

提交前自检：

```bash
git status -sb
git ls-files | grep -E '(^|/)\.env$'    # 必须为空
git diff --cached --stat
```

---

## 11. 下一步（未完成 / 候选）

1. **真实 Telegram 入站闭环**（最高优先）
   - 用户在 Telegram 给 `@yunbian666_bot` 发 `/start`
   - 拿到真实 `chat_id` / user id，写入 `.env` 的 `ADMIN_USER_ID`
   - 重启 Bot，验证 `/balance`、`/qd`、`/verify`、`/genkey`、`/stats`
   - 验证真实 `sendMessage` / `sendDocument`
   - 测完去 BotFather `/revoke` 轮换 Token
2. **Windows 实机验收**
   - 按第 7 节跑一遍最小清单
   - 重点验证：Pillow 中文字体、`.env` 编码、Docker Desktop MySQL、Playwright Chromium、两个 `.bat`
   - 把结果回写到本文件第 4.3 节
3. **接入三机同步（可选）**
   - 目前用原生 `git pull --ff-only` / `git push`
   - 若要接入 AIOS 的 `proj-sync`，再登记 `proj-sync.conf`；不要和 GitHub 交接冲突
4. **小说证书线（可选，不在本仓库）**
   - 从 Windows 把 `novel/make_guild_cert.py` 与预设迁过来
   - 仍然遵守红线：只做教学/设定/样机，保留 SAMPLE 标识

---

## 12. 给新会话的短提示词（可直接粘贴）

```text
接手 /mnt/Projects/103（Windows 则是 D:\Projects\103）。
先读 docs/HANDOFF.md、AGENTS.md、CURRENT.md、verify-lab/README.md，再按 README 建 .venv、复制 .env.example 为 .env、跑默认测试（54 个，48 通过 + 6 跳过）。
红线：只做合法教学，不接真实 SheerID、不生成/提交真实身份材料，证书必须保留 SAMPLE。
当前待办：让用户给 @yunbian666_bot 发 /start，拿真实 chat_id 后完成入站验收；Token 只放本机 .env，不提交、不打印。
```
