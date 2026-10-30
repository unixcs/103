"""本地 Telegram Bot API 仿真 —— 只实现测试用得到的方法

目的：不用真实 BOT_TOKEN 也能把 python-telegram-bot 的**真实调度栈**
（HTTP 请求 → Update 解析 → CommandHandler → handler → 回复 API）跑一遍。
它不是 Telegram 的完整实现，也不访问外网：

- getMe / deleteWebhook / getUpdates
- sendMessage / editMessageText / sendDocument
- 其他方法统一返回 true（例如 setMyCommands、close）

测试可以：
    api = FakeTelegramAPI(); api.start()
    api.inject_message(user_id=1, text="/start")
    ... 等 bot 调 sendMessage ...
    api.messages / api.documents
"""
from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional


def _parse_multipart(body: bytes, boundary: str) -> tuple[dict[str, str], dict[str, dict]]:
    fields: dict[str, str] = {}
    files: dict[str, dict] = {}
    delimiter = b"--" + boundary.encode()
    for chunk in body.split(delimiter):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        head, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = head.decode("utf-8", "replace")
        name_match = re.search(r'name="([^"]*)"', headers)
        if not name_match:
            continue
        name = name_match.group(1)
        file_match = re.search(r'filename="([^"]*)"', headers)
        if file_match:
            if data.endswith(b"\r\n"):
                data = data[:-2]
            files[name] = {"filename": file_match.group(1), "data": data}
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


class _State:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.next_update_id = 1
        self.next_message_id = 1
        self.pending_updates: list[dict] = []
        self.messages: list[dict] = []
        self.documents: list[dict] = []
        self.requests: list[dict] = []

    def new_message_id(self) -> int:
        with self.lock:
            mid = self.next_message_id
            self.next_message_id += 1
            return mid

    def inject_message(self, user_id: int, text: str, username: str = "tester",
                       first_name: str = "Test User") -> int:
        with self.lock:
            update_id = self.next_update_id
            self.next_update_id += 1
            entities = []
            if text.startswith("/"):
                command = text.split()[0]
                entities.append({"type": "bot_command", "offset": 0, "length": len(command)})
            self.pending_updates.append({
                "update_id": update_id,
                "message": {
                    "message_id": self.new_message_id(),
                    "date": int(time.time()),
                    "chat": {
                        "id": user_id, "type": "private",
                        "first_name": first_name, "username": username,
                    },
                    "from": {
                        "id": user_id, "is_bot": False,
                        "first_name": first_name, "username": username,
                        "language_code": "zh-hans",
                    },
                    "text": text,
                    "entities": entities,
                },
            })
            return update_id

    def take_updates(self, offset: Optional[int]) -> list[dict]:
        with self.lock:
            if offset:
                self.pending_updates = [
                    u for u in self.pending_updates if u["update_id"] >= offset
                ]
            batch = self.pending_updates[:100]
            self.pending_updates = self.pending_updates[len(batch):]
            return batch


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeTelegramAPI/1.0"

    @property
    def state(self) -> _State:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, *args):          # 测试输出保持干净
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        body: dict[str, Any] = {}
        files: dict[str, dict] = {}

        if "application/json" in content_type:
            try:
                body = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                body = {}
        elif "multipart/form-data" in content_type:
            match = re.search(r"boundary=([^;]+)", content_type)
            if match:
                body, files = _parse_multipart(raw, match.group(1).strip('"'))
        elif raw:
            from urllib.parse import parse_qs
            parsed = parse_qs(raw.decode("utf-8", "replace"))
            body = {k: v[0] for k, v in parsed.items() if v}

        method = self.path.rstrip("/").rsplit("/", 1)[-1]
        with self.state.lock:
            self.state.requests.append({"method": method, "body": body,
                                        "files": {k: v["filename"] for k, v in files.items()}})
        result = self._dispatch(method, body, files)
        payload = json.dumps({"ok": True, "result": result}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _dispatch(self, method: str, body: dict, files: dict) -> Any:
        if method == "getMe":
            return {
                "id": 777000, "is_bot": True, "first_name": "Verify Lab",
                "username": "verify_lab_test_bot", "can_join_groups": True,
                "can_read_all_group_messages": False, "supports_inline_queries": False,
            }
        if method == "deleteWebhook":
            return True
        if method == "getUpdates":
            offset = body.get("offset")
            try:
                offset = int(offset) if offset is not None else None
            except (TypeError, ValueError):
                offset = None
            return self.state.take_updates(offset)
        if method == "sendMessage":
            chat_id = int(body.get("chat_id", 0))
            text = body.get("text", "")
            message = self._message(chat_id, text=text,
                                    message_id=self.state.new_message_id())
            with self.state.lock:
                self.state.messages.append({
                    "method": method, "chat_id": chat_id, "text": text,
                    "message_id": message["message_id"],
                })
            return message
        if method == "editMessageText":
            chat_id = int(body.get("chat_id", 0))
            text = body.get("text", "")
            message_id = int(body.get("message_id", 0))
            with self.state.lock:
                self.state.messages.append({
                    "method": method, "chat_id": chat_id, "text": text,
                    "message_id": message_id,
                })
            return self._message(chat_id, text=text, message_id=message_id)
        if method == "sendDocument":
            chat_id = int(body.get("chat_id", 0))
            document = files.get("document", {"filename": "unnamed", "data": b""})
            caption = body.get("caption", "")
            message_id = self.state.new_message_id()
            with self.state.lock:
                self.state.documents.append({
                    "chat_id": chat_id,
                    "filename": document["filename"],
                    "data": document["data"],
                    "size": len(document["data"]),
                    "caption": caption,
                })
                self.state.messages.append({
                    "method": method, "chat_id": chat_id, "text": caption,
                    "message_id": message_id,
                })
            return self._message(
                chat_id, caption=caption, message_id=message_id,
                document={
                    "file_id": f"file-{message_id}",
                    "file_unique_id": f"uniq-{message_id}",
                    "file_name": document["filename"],
                    "mime_type": "image/png",
                    "file_size": len(document["data"]),
                },
            )
        if method == "close":
            return True
        return True

    def _message(self, chat_id: int, text: str | None = None, caption: str | None = None,
                 message_id: Optional[int] = None, document: Optional[dict] = None) -> dict:
        message: dict[str, Any] = {
            "message_id": message_id or self.state.new_message_id(),
            "date": int(time.time()),
            "chat": {"id": chat_id, "type": "private", "first_name": "Verify Lab"},
            "from": {"id": 777000, "is_bot": True, "first_name": "Verify Lab",
                     "username": "verify_lab_test_bot"},
        }
        if text is not None:
            message["text"] = text
        if caption is not None:
            message["caption"] = caption
        if document is not None:
            message["document"] = document
        return message


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.state = _State()
        self.httpd = _Server(("127.0.0.1", 0), _Handler)
        self.httpd.state = self.state  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.started = False

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/bot"

    @property
    def messages(self) -> list[dict]:
        with self.state.lock:
            return list(self.state.messages)

    @property
    def documents(self) -> list[dict]:
        with self.state.lock:
            return list(self.state.documents)

    @property
    def requests(self) -> list[dict]:
        with self.state.lock:
            return list(self.state.requests)

    def start(self) -> "FakeTelegramAPI":
        if not self.started:
            self.thread.start()
            self.started = True
        return self

    def stop(self) -> None:
        if self.started:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.thread.join(timeout=5)
            self.started = False

    def inject_message(self, user_id: int, text: str, username: str = "tester",
                       first_name: str = "Test User") -> int:
        return self.state.inject_message(user_id, text, username, first_name)

    def clear(self) -> None:
        with self.state.lock:
            self.state.messages.clear()
            self.state.documents.clear()
            self.state.requests.clear()

    def __enter__(self) -> "FakeTelegramAPI":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
