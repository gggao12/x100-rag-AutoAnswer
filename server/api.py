"""仅监听本机回环地址的 HTTP API：维护会话，并将可信身份传给 RAG。"""

from __future__ import annotations

import json
import secrets
import sqlite3
import sys
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Tuple

from .config import (
    DATABASE_PATH, DEEPSEEK_CONFIGURED, DEEPSEEK_SETTINGS, DEV_MODE,
    DOCUMENTS, EMBEDDING_MODEL, LLM_MODE,
)
from .ingest import init_database
from .rag import answer_question
from .agent import run_agent, confirm_action
from .tools import Principal

HOST = "127.0.0.1"
PORT = int(__import__("os").getenv("X100_API_PORT", "8005"))
SESSIONS: dict[str, dict[str, Any]] = {}
PUBLIC_DOC_IDS = [doc["id"] for doc in DOCUMENTS if doc["classification"] == "public"]


class Handler(BaseHTTPRequestHandler):
    server_version = "X100LocalRAG/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        # 访问日志不记录完整 URL、问题正文、Cookie 或异常内容。
        sys.stderr.write(f"x100-api {self.command} {self.path.split('?')[0]}\n")

    def _headers(self, status: int = 200, cookie: Optional[str] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _json(self, payload: dict[str, Any], status: int = 200, cookie: Optional[str] = None) -> None:
        self._headers(status, cookie)
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 16_384:
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(parsed, dict):
            raise ValueError("JSON object required")
        return parsed

    def _session(self, create: bool = True) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
        # 角色与内部授权只保存在服务端会话中，不能由请求 JSON 直接指定。
        cookies = SimpleCookie()
        cookies.load(self.headers.get("Cookie", ""))
        session_id = cookies.get("x100_session").value if cookies.get("x100_session") else ""
        session = SESSIONS.get(session_id)
        if session:
            return session, None
        if not create:
            return None, None
        session_id = secrets.token_urlsafe(32)
        session = {"role": "user", "internal_authorized": False}
        SESSIONS[session_id] = session
        cookie = f"x100_session={session_id}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200"
        return session, cookie

    def do_GET(self) -> None:
        if self.path == "/api/health":
            ready = False
            public_count = 0
            if DATABASE_PATH.exists():
                with sqlite3.connect(DATABASE_PATH) as connection:
                    init_database(connection)
                    public_count = connection.execute("SELECT COUNT(*) FROM public_chunks").fetchone()[0]
                    ready = public_count > 0
            self._json({"ok": True, "indexReady": ready, "publicChunks": public_count,
                        "embeddingModel": EMBEDDING_MODEL,
                        "llmMode": LLM_MODE, "llmModel": DEEPSEEK_SETTINGS.model,
                        "deepseekConfigured": DEEPSEEK_CONFIGURED})
            return
        if self.path == "/api/session":
            session, cookie = self._session()
            self._json({"role": session["role"], "devMode": DEV_MODE,
                        "internalRoleEnabled": DEV_MODE}, cookie=cookie)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        try:
            body = self._body()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self._json({"error": "invalid request"}, 400)
            return
        session, cookie = self._session()

        if self.path == "/api/session/role":
            role = body.get("role")
            if not DEV_MODE or role not in ("user", "agent", "internal"):
                self._json({"error": "role change unavailable"}, 403, cookie)
                return
            session["role"] = role
            session["internal_authorized"] = False
            self._json({"role": role}, cookie=cookie)
            return

        if self.path == "/api/session/authorization":
            if not DEV_MODE or session["role"] != "internal" or not isinstance(body.get("authorized"), bool):
                self._json({"error": "authorization unavailable"}, 403, cookie)
                return
            session["internal_authorized"] = body["authorized"]
            self._json({"authorized": session["internal_authorized"]}, cookie=cookie)
            return

        if self.path == "/api/agent":
            question = body.get("question")
            if not isinstance(question, str) or not question.strip() or len(question) > 2000:
                self._json({"error": "请输入不超过 2000 字的问题"}, 400, cookie); return
            history = body.get("history", []) if isinstance(body.get("history", []), list) else []
            request_id = uuid.uuid4().hex
            principal = Principal(user_id="demo-user", role=session["role"], internal_authorized=session["internal_authorized"])
            try:
                response = run_agent(question, history[-8:], principal, request_id)
            except Exception as exc:
                sys.stderr.write(f"x100-agent request={request_id} error={type(exc).__name__}\\n")
                self._json({"error": "Agent 服务处理失败，请转人工"}, 500, cookie); return
            response["requestId"] = request_id; response["role"] = session["role"]
            self._json(response, cookie=cookie); return

        if self.path == "/api/agent/confirm":
            cid, action, ph = body.get("confirmationId"), body.get("expectedAction"), body.get("parametersHash")
            if not all(isinstance(x,str) and x for x in (cid,action,ph)):
                self._json({"error":"确认参数无效"}, 400, cookie); return
            principal = Principal(user_id="demo-user", role=session["role"], internal_authorized=session["internal_authorized"])
            response = confirm_action(cid, action, ph, principal)
            self._json(response, 200 if response.get("ok") else 409, cookie); return

        if self.path != "/api/ask":
            self._json({"error": "not found"}, 404, cookie)
            return
        question = body.get("question")
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            self._json({"error": "请输入不超过 2000 字的问题"}, 400, cookie)
            return
        history = body.get("history", [])
        if not isinstance(history, list):
            history = []
        history = [item for item in history[-8:] if isinstance(item, dict) and
                   isinstance(item.get("content"), str) and isinstance(item.get("role"), str)]
        request_id = uuid.uuid4().hex
        if not DATABASE_PATH.is_file():
            self._json({"error": "知识库尚未建立，请先运行 pnpm ingest"}, 503, cookie)
            return
        try:
            # 请求体只提供问题和历史；权限身份始终从服务端会话读取。
            response = answer_question(question, history, session["role"],
                                        session["internal_authorized"], request_id)
        except FileNotFoundError:
            self._json({"error": "知识库尚未建立，请先运行 pnpm ingest"}, 503, cookie)
            return
        except Exception as exc:
            # 不向浏览器回显问题正文、检索片段、凭据或异常细节。
            sys.stderr.write(f"x100-api request={request_id} error={type(exc).__name__}\n")
            self._json({"error": "本地 RAG 服务处理失败，请检查索引和模型状态"}, 500, cookie)
            return
        response["requestId"] = request_id
        response["role"] = session["role"]
        self._json(response, cookie=cookie)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"X100 RAG API listening on http://{HOST}:{PORT}")
    state = "configured" if DEEPSEEK_CONFIGURED else "not configured (Mock mode)"
    print(f"DeepSeek API: {state}")
    print(f"Model: {DEEPSEEK_SETTINGS.model}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()




