"""`.env` 加载器测试 —— Bot 启动路径的第一环，不能被静默跳过。"""
from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.env import DEFAULT_ENV_PATH, load_env  # noqa: E402


class EnvLoaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = BASE / ".tmp" / f"env-{uuid.uuid4().hex[:8]}"
        self.tmp.mkdir(parents=True)
        self.path = self.tmp / ".env"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_path_is_project_root(self):
        self.assertEqual(DEFAULT_ENV_PATH, BASE / ".env")
        self.assertEqual(DEFAULT_ENV_PATH.name, ".env")

    def test_parse_basic_export_quotes_and_comments(self):
        self.path.write_text(
            "# comment\n"
            "\n"
            "PLAIN=value\n"
            "export EXPORTED=yes\n"
            'QUOTED="a b"\n'
            "SINGLE='c d'\n"
            "NO_EQUALS\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in ("PLAIN", "EXPORTED", "QUOTED", "SINGLE"):
                os.environ.pop(key, None)
            self.assertEqual(load_env(self.path), self.path)
            self.assertEqual(os.environ["PLAIN"], "value")
            self.assertEqual(os.environ["EXPORTED"], "yes")
            self.assertEqual(os.environ["QUOTED"], "a b")
            self.assertEqual(os.environ["SINGLE"], "c d")

    def test_existing_env_wins_unless_override(self):
        self.path.write_text("KEEP=from-file\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"KEEP": "from-shell"}, clear=False):
            load_env(self.path)
            self.assertEqual(os.environ["KEEP"], "from-shell")
            load_env(self.path, override=True)
            self.assertEqual(os.environ["KEEP"], "from-file")

    def test_missing_file_is_none(self):
        self.assertIsNone(load_env(self.tmp / "nope.env"))


if __name__ == "__main__":
    unittest.main()
