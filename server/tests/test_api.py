"""API 边界测试：身份与内部授权必须来自服务端状态。"""

import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from server.api import Handler


class ServerIdentityTests(unittest.TestCase):
    def test_request_body_cannot_spoof_role_or_internal_authorization(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.NamedTemporaryFile() as database:
                fake_result = {"answer": "test", "stages": [], "sources": [], "debug": None}
                with patch("server.api.DATABASE_PATH", Path(database.name)), \
                     patch("server.api.answer_question", return_value=fake_result) as answer:
                    body = json.dumps({
                        "question": "测试问题", "role": "internal", "internal_authorized": True,
                    }).encode("utf-8")
                    request = urllib.request.Request(
                        "http://127.0.0.1:%d/api/ask" % server.server_address[1],
                        data=body,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request) as response:
                        self.assertEqual(response.status, 200)
                    args = answer.call_args[0]
                    self.assertEqual(args[2], "user")
                    self.assertFalse(args[3])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
