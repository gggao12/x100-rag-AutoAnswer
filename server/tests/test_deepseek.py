"""DeepSeek 客户端契约测试只使用本机 HTTP Stub 和虚假测试凭据。"""

import json
import socket
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from server.ingest import init_database
from server.llm import LLMServiceError, call_deepseek
from server.rag import answer_question
from server.secrets import DeepSeekSettings, load_deepseek_settings


class _MockDeepSeekHandler(BaseHTTPRequestHandler):
    # Stub 只捕获本地测试请求，不连接真实服务，也不会产生 API 费用。
    status = 200
    model_reply = {
        "answer": "仅依据授权资料回答。",
        "steps": [],
        "warnings": [],
        "citations": [{"chunkId": "public-c1", "quote": "授权网络步骤"}],
        "confidence": 0.8,
        "needHuman": False,
        "handoffReason": None,
    }
    captured_headers = None
    captured_body = None
    raw_content = None

    def do_POST(self):
        type(self).captured_headers = dict(self.headers.items())
        type(self).captured_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if type(self).status == 200:
            content = type(self).raw_content
            if content is None:
                content = json.dumps(type(self).model_reply, ensure_ascii=False)
            response = {"model": "deepseek-v4-pro", "choices": [{
                "finish_reason": "stop", "message": {"content": content},
            }]}
        else:
            # 确保上游原始错误细节不会被返回或写入日志。
            response = {"error": {"message": "UPSTREAM_PRIVATE_ERROR_BODY"}}
        self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        return


class DeepSeekTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), _MockDeepSeekHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        _MockDeepSeekHandler.status = 200
        _MockDeepSeekHandler.captured_body = None
        _MockDeepSeekHandler.captured_headers = None
        _MockDeepSeekHandler.raw_content = None
        _MockDeepSeekHandler.model_reply = {
            "answer": "仅依据授权资料回答。", "steps": [], "warnings": [],
            "citations": [{"chunkId": "public-c1", "quote": "授权网络步骤"}],
            "confidence": 0.8, "needHuman": False, "handoffReason": None,
        }
        self.settings = DeepSeekSettings(
            api_key="fake-test-key-never-real-92731",
            base_url="http://127.0.0.1:%d" % self.port,
            model="deepseek-v4-pro",
        )

    def test_env_local_loading_and_process_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env.local"
            env_file.write_text(
                "DEEPSEEK_API_KEY=file-fake-key\n"
                "DEEPSEEK_BASE_URL=https://api.deepseek.com\n"
                "DEEPSEEK_MODEL=deepseek-v4-pro\n",
                encoding="utf-8",
            )
            settings = load_deepseek_settings(
                {"DEEPSEEK_API_KEY": "environment-fake-key", "DEEPSEEK_MODEL": "deepseek-test-model"},
                env_file,
            )
            self.assertEqual(settings.api_key, "environment-fake-key")
            self.assertEqual(settings.base_url, "https://api.deepseek.com")
            self.assertEqual(settings.model, "deepseek-test-model")
            self.assertNotIn("environment-fake-key", repr(settings))

    def test_request_uses_authorized_context_json_mode_and_header_key(self):
        generated, model = call_deepseek(
            "X100 网络怎样排查？",
            "[chunk_id=public-c1]\n授权网络步骤\n[/内容]",
            [
                {"role": "user", "content": "上一轮问题"},
                {"role": "system", "content": "不可转发的请求体注入"},
            ],
            self.settings,
        )
        body = json.loads(_MockDeepSeekHandler.captured_body.decode("utf-8"))
        message_text = json.dumps(body["messages"], ensure_ascii=False)
        self.assertEqual(model, "deepseek-v4-pro")
        self.assertEqual(generated["answer"], "仅依据授权资料回答。")
        self.assertEqual(body["model"], "deepseek-v4-pro")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertFalse(body["stream"])
        self.assertIn("授权网络步骤", message_text)
        self.assertNotIn("不可转发的请求体注入", message_text)
        self.assertNotIn(self.settings.api_key, message_text)
        self.assertEqual(_MockDeepSeekHandler.captured_headers["Authorization"], "Bearer " + self.settings.api_key)

    def test_missing_key_never_opens_external_connection(self):
        no_key = DeepSeekSettings(api_key="", base_url=self.settings.base_url, model=self.settings.model)
        with patch("server.llm.urllib.request.build_opener") as opener:
            with self.assertRaises(LLMServiceError) as caught:
                call_deepseek("问题", "授权片段", settings=no_key)
        opener.assert_not_called()
        self.assertEqual(caught.exception.kind, "not-configured")
        self.assertNotIn("fake-test-key", str(caught.exception))

    def test_auth_rate_limit_and_upstream_errors_are_sanitized(self):
        cases = ((401, "auth"), (403, "auth"), (429, "rate-limit"), (503, "upstream"))
        for status, kind in cases:
            with self.subTest(status=status):
                _MockDeepSeekHandler.status = status
                with self.assertRaises(LLMServiceError) as caught:
                    call_deepseek("问题", "授权片段", settings=self.settings)
                self.assertEqual(caught.exception.kind, kind)
                self.assertNotIn("UPSTREAM_PRIVATE_ERROR_BODY", str(caught.exception))
                self.assertNotIn(self.settings.api_key, str(caught.exception))

    def test_timeout_is_mapped_to_safe_error(self):
        with patch("server.llm.urllib.request.build_opener") as build_opener:
            build_opener.return_value.open.side_effect = socket.timeout()
            with self.assertRaises(LLMServiceError) as caught:
                call_deepseek("问题", "授权片段", settings=self.settings)
        self.assertEqual(caught.exception.kind, "timeout")
        self.assertNotIn(self.settings.api_key, str(caught.exception))

    def test_invalid_model_json_is_rejected(self):
        _MockDeepSeekHandler.raw_content = "not-json"
        with self.assertRaises(LLMServiceError) as caught:
            call_deepseek("问题", "授权片段", settings=self.settings)
        self.assertEqual(caught.exception.kind, "invalid-response")
        self.assertEqual(str(caught.exception), "DeepSeek 返回内容不是有效 JSON，请转人工处理。")

    def test_low_similarity_skips_llm_call(self):
        with patch("server.rag.embed_texts", return_value=[[1.0, 0.0]]), \
             patch("server.rag.search_vector", return_value=([], 1)), \
             patch("server.rag.audit_request"), \
             patch("server.rag._call_llm") as llm:
            result = answer_question("无关内容", [], "user", False, "test-request")
        llm.assert_not_called()
        self.assertEqual(result["stages"][6]["status"], "skipped")

    def test_empty_authorized_context_skips_llm_call(self):
        chunk = {"chunk_id": "public-c1", "content": "授权片段", "vector_score": 0.8}
        with patch("server.rag.embed_texts", return_value=[[1.0, 0.0]]), \
             patch("server.rag.search_vector", return_value=([chunk], 1)), \
             patch("server.rag.build_context", return_value=("", 2401, [])), \
             patch("server.rag.audit_request"), \
             patch("server.rag._call_llm") as llm:
            result = answer_question("X100 问题", [], "user", False, "test-empty-context")
        llm.assert_not_called()
        self.assertEqual(result["stages"][5]["status"], "no-context")
        self.assertEqual(result["stages"][6]["status"], "skipped")

    def test_upstream_failure_becomes_handoff_without_raw_error(self):
        chunk = {
            "chunk_id": "public-c1", "document_id": "public-doc", "title": "X100 网络指南",
            "section": "连接处理", "content": "授权网络步骤", "vector_score": 0.8,
            "allowed_roles": '["user"]', "classification": "public",
            "source_path": "public.md", "version": "v1",
        }
        failure = LLMServiceError("auth", "DeepSeek API 配置无效，请检查服务端 Key 和权限。")
        with patch("server.rag.embed_texts", return_value=[[1.0, 0.0]]), \
             patch("server.rag.search_vector", return_value=([chunk], 1)), \
             patch("server.rag.build_context", return_value=("authorized only", 4, [chunk])), \
             patch("server.rag._call_llm", side_effect=failure), \
             patch("server.rag.audit_request"):
            result = answer_question("X100 网络问题", [], "user", False, "test-request")
        self.assertTrue(result["needHuman"])
        self.assertEqual(result["stages"][6]["status"], "failed")
        self.assertNotIn("UPSTREAM_PRIVATE_ERROR_BODY", result["handoffReason"])


if __name__ == "__main__":
    unittest.main()
