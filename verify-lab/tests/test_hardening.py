"""墨菲定律加固测试：注入、超长文本、路径穿越、日志泄密、网络抖动。"""
from __future__ import annotations

import json
import logging
import shutil
import sys
import unittest
import urllib.error
import uuid
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.bot_service import (  # noqa: E402
    _RedactingFormatter,
    _check_telegram_token,
    _run_polling_with_retry,
    _split_message,
)
from app.render import render_certificate, render_html  # noqa: E402

try:
    from telegram.error import NetworkError
    PTB_INSTALLED = True
except ImportError:
    PTB_INSTALLED = False


class RenderHardeningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = BASE / ".tmp" / f"hard-{uuid.uuid4().hex[:8]}"
        self.tmp.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_html_injection_is_escaped(self):
        html = render_html(
            "<script>alert(1)</script>",
            '<img src=x onerror="alert(2)">',
            12, 95, "../../evil",
        )
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)

    def test_long_text_and_serial_cannot_break_layout_or_path(self):
        html = render_html("长" * 100, "课" * 200, 12, 95, "x" * 300)
        self.assertIn("…", html)
        self.assertLessEqual(html.count("长"), 48)
        self.assertLessEqual(html.count("课"), 80)

        out = render_certificate(
            "长" * 100, "课" * 200, 12, 95, "../../evil", self.tmp, "pillow"
        )
        self.assertEqual(out.parent, self.tmp)
        self.assertEqual(out.name, "evil.png")
        self.assertTrue(out.exists())
        from PIL import Image
        with Image.open(out) as img:
            self.assertEqual(img.size, (1000, 700))


class LoggingHardeningTest(unittest.TestCase):
    def test_token_is_redacted_from_formatted_log(self):
        token = "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        fmt = _RedactingFormatter("%(message)s", token)
        record = logging.LogRecord(
            "httpx", logging.INFO, "", 0,
            "POST https://api.telegram.org/bot%s/getMe", (token,), None,
        )
        text = fmt.format(record)
        self.assertNotIn(token, text)
        self.assertIn("***", text)


class MessageLengthHardeningTest(unittest.TestCase):
    def test_long_reply_is_split_under_telegram_limit(self):
        text = "\n".join(f"第 {i} 行：卡密说明" for i in range(2000))
        chunks = _split_message(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 4000 for c in chunks))
        self.assertTrue(all(c.strip() for c in chunks))
        # 没有切坏任何一行
        self.assertTrue(all(line.startswith("第 ") for c in chunks for line in c.splitlines()))

    def test_short_reply_stays_one_message(self):
        self.assertEqual(_split_message("短消息"), ["短消息"])
        self.assertEqual(_split_message(""), [])


@unittest.skipUnless(PTB_INSTALLED, "需要 python-telegram-bot")
class StartupRetryHardeningTest(unittest.TestCase):
    def test_startup_network_error_is_retried(self):
        first = mock.Mock()
        first.run_polling.side_effect = NetworkError("temporary DNS failure")
        second = mock.Mock()
        cfg = mock.Mock(drop_pending=False, poll_interval=1.0)

        with mock.patch("app.bot_service.build_application", side_effect=[first, second]), \
                mock.patch("app.bot_service.time.sleep") as sleep:
            rc = _run_polling_with_retry(cfg)

        self.assertEqual(rc, 0)
        self.assertEqual(first.run_polling.call_count, 1)
        self.assertEqual(second.run_polling.call_count, 1)
        sleep.assert_called_once_with(5)


class TelegramCheckHardeningTest(unittest.TestCase):
    class _Resp:
        def __init__(self, payload: dict):
            self._body = json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self._body

    def test_transient_timeouts_are_retried(self):
        calls = []

        def fake_urlopen(req, timeout=0):
            calls.append(req if isinstance(req, str) else req.full_url)
            if len(calls) < 3:
                raise TimeoutError("temporary")
            return self._Resp({"ok": True, "result": {"username": "lab_bot", "id": 1}})

        with mock.patch("app.bot_service.urllib.request.urlopen", fake_urlopen), \
                mock.patch("app.bot_service.time.sleep", lambda _: None):
            ok, message = _check_telegram_token("123:abc")
        self.assertTrue(ok, message)
        self.assertEqual(len(calls), 3)

    def test_401_is_not_retried(self):
        calls = []

        def fake_urlopen(req, timeout=0):
            url = req if isinstance(req, str) else req.full_url
            calls.append(url)
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

        with mock.patch("app.bot_service.urllib.request.urlopen", fake_urlopen), \
                mock.patch("app.bot_service.time.sleep", lambda _: None):
            ok, message = _check_telegram_token("123:abc")
        self.assertFalse(ok)
        self.assertIn("401", message)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
