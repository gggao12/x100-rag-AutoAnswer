"""离线验证白名单、文档预处理、检索门控和生成结果安全校验。"""

import json
import math
import os
import tempfile
import unittest
from unittest.mock import patch

from server.config import DOCUMENT_IDS
from server.ingest import init_database, markdown_sections, purge_unlisted_documents, sanitize_top_secret, table_to_text
import sqlite3
from server.rag import allowed_tables, _dot_cosine, search_vector, validate_generation


class IngestTests(unittest.TestCase):
    def test_document_allowlist_excludes_unrelated_workspace_markdown(self):
        self.assertEqual(
            DOCUMENT_IDS,
            {"00_X100_绝密_内部手册", "01_X100_WiFi故障", "02_X100设备离线",
             "03_X100升级失败", "04_X100密码忘记", "05_X100售后政策"},
        )
        self.assertNotIn("99_办公室绿植浇水备忘", DOCUMENT_IDS)

    def test_markdown_sections_and_table_relations(self):
        title, sections = markdown_sections(
            "# 手册\n\n## 提示\n\n| 提示文案 | 含义 | 建议操作 |\n|---|---|---|\n| E1 | 离线 | 检查网络 |"
        )
        self.assertEqual(title, "手册")
        self.assertEqual(sections[0][0], "提示")
        self.assertEqual(sections[0][1], "提示文案：E1；含义：离线；建议操作：检查网络")

    def test_secret_is_removed_before_indexing(self):
        sanitized = sanitize_top_secret("# 内部手册\n工程口令：DONT-LEAK-THIS\n普通操作：先核验工单")
        self.assertNotIn("DONT-LEAK-THIS", sanitized)
        self.assertIn("普通操作：先核验工单", sanitized)

    def test_deleted_allowlist_documents_are_purged_from_persistent_index(self):
        connection = sqlite3.connect(":memory:")
        init_database(connection)
        connection.execute(
            "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("stale-doc", "过期文档", "public", "stale.md", "old", "unspecified", 1, "model", 512, "now"),
        )
        purge_unlisted_documents(connection, ["current-doc"])
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
        connection.close()


class RetrievalAndSafetyTests(unittest.TestCase):
    def test_permission_filter_selects_isolated_collection(self):
        self.assertEqual(allowed_tables("user", False), ["public_chunks"])
        self.assertEqual(allowed_tables("agent", False), ["public_chunks"])
        self.assertEqual(allowed_tables("internal", False), ["public_chunks"])
        self.assertEqual(allowed_tables("internal", True), ["public_chunks", "internal_chunks"])

    def test_cosine_scores_are_real_vector_similarity(self):
        self.assertAlmostEqual(_dot_cosine([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(_dot_cosine([1, 0], [0, 1]), 0.0)
        self.assertAlmostEqual(_dot_cosine([1, 0], [-1, 0]), -1.0)

    def test_hybrid_retrieval_requires_cosine_and_lexical_evidence(self):
        # 使用构造向量，让阈值测试可重复，避免下载真实模型。
        with tempfile.TemporaryDirectory() as directory:
            database_path = os.path.join(directory, "test.sqlite3")
            connection = sqlite3.connect(database_path)
            init_database(connection)
            rows = [
                ("below-cosine-floor", 0.39, "X100 WiFi 连接处理步骤"),
                ("off-topic", 0.59, "办公室午餐菜单和休息时间"),
                ("semantic-only", 0.61, "周末雨天适合散步阅读"),
                ("lexically-supported", 0.59, "X100 WiFi 连接处理步骤"),
            ]
            for chunk_id, score, content in rows:
                vector = [score, math.sqrt(1 - score * score)]
                connection.execute(
                    "INSERT INTO public_chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (chunk_id, chunk_id, "X100 WiFi 网络指南" if "X100" in content else "通用资料",
                     "连接处理", content,
                     json.dumps(vector), "public", '["user"]', "fixture.md", "v1", "unspecified",
                     0, chunk_id, "test-model", 2),
                )
            connection.commit()
            connection.close()
            with patch("server.rag.DATABASE_PATH", database_path):
                results, _ = search_vector("X100 WiFi 连接", "user", False, [1.0, 0.0])
            self.assertEqual([item["chunk_id"] for item in results], ["lexically-supported"])

    def test_citations_must_quote_authorized_context(self):
        context = [{"chunk_id": "public-c1", "content": "X100 支持 2.4GHz 网络。"}]
        valid = {
            "answer": "请使用 2.4GHz。", "steps": [], "warnings": [],
            "citations": [{"chunkId": "public-c1", "quote": "支持 2.4GHz"}],
            "confidence": 0.8, "needHuman": False, "handoffReason": None,
        }
        invalid_id = {"answer": "请使用 2.4GHz。", "citations": [{"chunkId": "secret-c1", "quote": "支持 2.4GHz"}]}
        invalid_quote = {"answer": "请使用 5GHz。", "citations": [{"chunkId": "public-c1", "quote": "支持 5GHz"}]}
        self.assertTrue(validate_generation(valid, context)[0])
        self.assertFalse(validate_generation(invalid_id, context)[0])
        self.assertFalse(validate_generation(invalid_quote, context)[0])

    def test_sensitive_material_in_any_generated_field_blocks_response(self):
        context = [{"chunk_id": "public-c1", "content": "正常公开内容。"}]
        generated = {
            "answer": "正常回答。", "warnings": ["token sk-1234567890abcdefghijkl"],
            "citations": [{"chunkId": "public-c1", "quote": "正常公开内容"}],
        }
        self.assertFalse(validate_generation(generated, context)[0])

    def test_malformed_structured_output_is_rejected(self):
        context = [{"chunk_id": "public-c1", "content": "正常公开内容。"}]
        malformed = {
            "answer": "正常回答。", "steps": "不是数组",
            "citations": [{"chunkId": "public-c1", "quote": "正常公开内容"}],
        }
        self.assertFalse(validate_generation(malformed, context)[0])


if __name__ == "__main__":
    unittest.main()
