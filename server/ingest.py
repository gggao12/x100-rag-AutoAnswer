"""解析配置白名单 Markdown、脱敏受限内容，并将切片向量持久化到 SQLite。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from .config import DATA_DIR, DATABASE_PATH, DOCUMENTS, EMBEDDING_DIMENSION, EMBEDDING_MODEL, ROOT
from .embedding import embed_texts


def init_database(connection: sqlite3.Connection) -> None:
    # 公开和内部资料使用独立表，默认公开检索路径不会扫描受限切片。
    connection.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS public_chunks (
          chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, title TEXT NOT NULL,
          section TEXT NOT NULL, content TEXT NOT NULL, embedding TEXT NOT NULL,
          classification TEXT NOT NULL CHECK(classification='public'), allowed_roles TEXT NOT NULL,
          source_path TEXT NOT NULL, version TEXT NOT NULL, effective_at TEXT NOT NULL,
          chunk_index INTEGER NOT NULL, content_hash TEXT NOT NULL, model_name TEXT NOT NULL,
          dimension INTEGER NOT NULL, UNIQUE(document_id, content_hash, model_name)
        );
        CREATE TABLE IF NOT EXISTS internal_chunks (
          chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, title TEXT NOT NULL,
          section TEXT NOT NULL, content TEXT NOT NULL, embedding TEXT NOT NULL,
          classification TEXT NOT NULL CHECK(classification='top_secret'), allowed_roles TEXT NOT NULL,
          source_path TEXT NOT NULL, version TEXT NOT NULL, effective_at TEXT NOT NULL,
          chunk_index INTEGER NOT NULL, content_hash TEXT NOT NULL, model_name TEXT NOT NULL,
          dimension INTEGER NOT NULL, UNIQUE(document_id, content_hash, model_name)
        );
        CREATE TABLE IF NOT EXISTS documents (
          document_id TEXT PRIMARY KEY, title TEXT NOT NULL, classification TEXT NOT NULL,
          source_path TEXT NOT NULL, version TEXT NOT NULL, effective_at TEXT NOT NULL,
          chunk_count INTEGER NOT NULL, model_name TEXT NOT NULL, dimension INTEGER NOT NULL,
          indexed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_log (
          event_id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
          request_id TEXT NOT NULL, principal_role TEXT NOT NULL, authorization TEXT NOT NULL,
          query_hash TEXT NOT NULL, rewritten_hash TEXT NOT NULL, permission_decision TEXT NOT NULL,
          chunk_ids TEXT NOT NULL, model_version TEXT NOT NULL, confidence REAL NOT NULL,
          need_human INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_public_document ON public_chunks(document_id);
        CREATE INDEX IF NOT EXISTS idx_internal_document ON internal_chunks(document_id);
        CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_log(request_id);
        """
    )


def purge_unlisted_documents(connection: sqlite3.Connection, present_ids: list[str]) -> None:
    if present_ids:
        placeholders = ",".join("?" for _ in present_ids)
        connection.execute(f"DELETE FROM public_chunks WHERE document_id NOT IN ({placeholders})", present_ids)
        connection.execute(f"DELETE FROM internal_chunks WHERE document_id NOT IN ({placeholders})", present_ids)
        connection.execute(f"DELETE FROM documents WHERE document_id NOT IN ({placeholders})", present_ids)
    else:
        connection.execute("DELETE FROM public_chunks")
        connection.execute("DELETE FROM internal_chunks")
        connection.execute("DELETE FROM documents")


def sanitize_top_secret(text: str) -> str:
    # 在向量化和持久化之前移除包含凭据的行，同时保留安全操作说明。
    safe_lines = []
    for line in text.splitlines():
        if re.search(r"工程口令|工程密码|访问令牌|API.?Key|私钥", line, re.IGNORECASE):
            safe_lines.append("- 敏感凭据已从 Demo 索引中移除；请通过授权工单的秘密管理流程核验。")
        else:
            safe_lines.append(line)
    return "\n".join(safe_lines)


def table_to_text(lines: list[str]) -> list[str]:
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    rows = [row for row in rows if row and not all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in row)]
    if len(rows) < 2:
        return [" ".join(" ".join(row) for row in rows)]
    headers = rows[0]
    converted = []
    for row in rows[1:]:
        pairs = [f"{headers[i]}：{value}" for i, value in enumerate(row) if i < len(headers) and value]
        if pairs:
            converted.append("；".join(pairs))
    return converted

# 先把md文件转化成字符串，然后在这里转化成结构化内容
def markdown_sections(markdown: str) -> tuple[str, list[tuple[str, str]]]:
    title = "未命名文档"
    section = title
    paragraphs: list[tuple[str, str]] = []
    text_lines: list[str] = []
    table_lines: list[str] = []

    def flush_text() -> None:
        nonlocal text_lines
        body = " ".join(line.strip() for line in text_lines if line.strip())
        if body:
            paragraphs.append((section, body))
        text_lines = []

    def flush_table() -> None:
        nonlocal table_lines
        for body in table_to_text(table_lines):
            if body:
                paragraphs.append((section, body))
        table_lines = []

    for line in markdown.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            flush_text()
            flush_table()
            section = heading.group(2).strip()
            if len(heading.group(1)) == 1:
                title = section
            continue
        if line.lstrip().startswith("|"):
            flush_text()
            table_lines.append(line)
        else:
            flush_table()
            if not line.strip():
                flush_text()
            else:
                text_lines.append(line)
    flush_text()
    flush_table()
    return title, paragraphs

# 把paragraph按照标点切成更小的块，最大不超过700，超过700就按照700截断，保留最后80拼接到下一chunk
def split_paragraph(text: str, limit: int = 700, overlap: int = 80) -> list[str]:
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[。！？；.!?])", text)
    output: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > limit:
            if current:
                output.append(current)
                current = current[-overlap:]
            output.append(sentence[:limit])
            sentence = sentence[max(1, limit - overlap) :]
        if current and len(current) + len(sentence) > limit:
            output.append(current)
            current = current[-overlap:]
        current += sentence
    if current.strip():
        output.append(current)
    return output

# 切片
def make_chunks(title: str, sections: list[tuple[str, str]]) -> list[dict[str, Union[str, int]]]:
    chunks: list[dict[str, Union[str, int]]] = []
    current_section = ""
    current = ""
    for section, paragraph in sections:
        if section != current_section:
            if current.strip():
                chunks.append({"section": current_section, "content": current.strip()})
                current = ""
            current_section = section
        for part in split_paragraph(paragraph):
            if current and len(current) + len(part) + 1 > 700: # 每一个chunk最长700字符
                chunks.append({"section": current_section, "content": current.strip()})
                current = current[-80:] #切块的时候，不是从零开始，而是保留上一块最后80个字符
            current = f"{current}\n{part}" if current else part
    if current.strip():
        chunks.append({"section": current_section or title, "content": current.strip()})
    return chunks

# 文档加载，把md文件读进来
def load_document(doc: dict) -> tuple[str, str, str, list[dict[str, Union[str, int]]]]:
    path = ROOT / doc["file"] # 根目录下找文件
    raw = path.read_text(encoding="utf-8-sig") # 读取为字符串
    raw = sanitize_top_secret(raw) if doc["classification"] == "top_secret" else raw # 如果是机密文件就进行脱敏/清理
    title, sections = markdown_sections(raw) # 把刚才的字符串，解析成结构化内容
    chunks = make_chunks(title, sections) # 切片，传入标题以及结构化内容
    version = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return title, path.name, version, chunks


def ingest() -> dict[str, Union[int, str, list[str]]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    prepared = []
    present_ids = []
    missing_documents = []
    # DOCUMENTS 是 config.py 中的显式白名单；这里不会扫描或自动发现工作区文件。
    for doc in DOCUMENTS:
        if not (ROOT / doc["file"]).is_file():
            missing_documents.append(doc["id"])
            continue
        title, source_path, version, chunks = load_document(doc)
        present_ids.append(doc["id"])
        for index, chunk in enumerate(chunks):
            content = str(chunk["content"])
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            chunk_id = f"{doc['id']}-c{index + 1:03d}-{content_hash[:10]}"
            prepared.append({
                "document": doc, "title": title, "source_path": source_path,
                "version": version, "section": str(chunk["section"]), "content": content,
                "content_hash": content_hash, "chunk_id": chunk_id, "chunk_index": index,
                "embed_text": f"{title}\n{chunk['section']}\n{content}",
            })

    # 含敏感凭据的原文会先脱敏，再进行向量化和持久化。
    # 只有完成白名单筛选、切片和受限文档脱敏后，才会生成 Embedding。
    vectors = embed_texts([str(item["embed_text"]) for item in prepared])
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DATABASE_PATH) as connection:
        init_database(connection)
        model_in_db = connection.execute(
            "SELECT DISTINCT model_name FROM public_chunks UNION SELECT DISTINCT model_name FROM internal_chunks"
        ).fetchall()
        if any(row[0] != EMBEDDING_MODEL for row in model_in_db):
            connection.execute("DELETE FROM public_chunks")
            connection.execute("DELETE FROM internal_chunks")
            connection.execute("DELETE FROM documents")

        # 清理已从白名单移除或已从磁盘删除的文档向量。
        purge_unlisted_documents(connection, present_ids)

        counts = {"public": 0, "top_secret": 0}
        for doc in DOCUMENTS:
            table = "internal_chunks" if doc["classification"] == "top_secret" else "public_chunks"
            connection.execute(f"DELETE FROM {table} WHERE document_id = ?", (doc["id"],))

        for item, vector in zip(prepared, vectors):
            doc = item["document"]
            table = "internal_chunks" if doc["classification"] == "top_secret" else "public_chunks"
            values = (
                item["chunk_id"], doc["id"], item["title"], item["section"], item["content"],
                json.dumps(vector, separators=(",", ":")), doc["classification"],
                json.dumps(list(doc["roles"])), item["source_path"], item["version"],
                "unspecified", item["chunk_index"], item["content_hash"], EMBEDDING_MODEL,
                len(vector),
            )
            connection.execute(
                f"INSERT INTO {table} VALUES ({','.join('?' for _ in values)})", values
            )
            counts[doc["classification"]] += 1

        for doc in DOCUMENTS:
            items = [item for item in prepared if item["document"]["id"] == doc["id"]]
            if not items:
                continue
            connection.execute(
                "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)",
                (doc["id"], items[0]["title"], doc["classification"], items[0]["source_path"],
                 items[0]["version"], "unspecified", len(items), EMBEDDING_MODEL,
                 EMBEDDING_DIMENSION, now),
            )

    return {"public_chunks": counts["public"], "internal_chunks": counts["top_secret"],
            "embedding_model": EMBEDDING_MODEL, "dimension": EMBEDDING_DIMENSION,
            "missing_documents": missing_documents}


if __name__ == "__main__":
    try:
        result = ingest()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        # 控制台不输出文档正文和异常细节，避免泄露知识库内容。
        print(f"入库失败：{type(exc).__name__}。请检查模型下载、原文文件和 Python 依赖。", file=sys.stderr)
        raise SystemExit(1)
