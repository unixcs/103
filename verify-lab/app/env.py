"""极简 .env 加载器 —— 不引入 python-dotenv

规则很小，够用就行：
- 空行和 # 开头的行忽略；
- 支持 `KEY=VALUE` / `export KEY=VALUE`；
- 值可以用单引号或双引号包住；
- **已存在的环境变量不覆盖**（命令行 / systemd / docker -e 的优先级更高）。
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: str | Path | None = None, override: bool = False) -> Path | None:
    path = Path(path) if path is not None else DEFAULT_ENV_PATH
    if not path.exists():
        return None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value
    return path
