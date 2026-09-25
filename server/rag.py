"""授权检索到答案的完整流程；没有匹配证据就不调用生成模型。"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from typing import Any, Optional

from .config import (
    CANDIDATE_K, DATABASE_PATH, DEEPSEEK_SETTINGS, EMBEDDING_MODEL, FINAL_K,
    LLM_MODE, LLM_MODEL, MAX_CONTEXT_TOKENS, MIN_RERANKED_SCORE,
    MIN_VECTOR_COSINE,
)
from .embedding import embed_texts, token_count
from .ingest import init_database
from .llm import LLMServiceError, call_deepseek

SECRET_QUERY = re.compile(
    r"工程口令|工厂模式|串口|云端熔断|忽略.{0,8}(权限|规则)|输出.{0,12}(隐藏|内部)|提示词注入|内部口令",
    re.IGNORECASE,
)
HIGH_RISK = re.compile(r"退款|换新|远程诊断|账号找回|安全事件|验证码|银行卡|盗号")
SENSITIVE_OUTPUT = re.compile(r"(?:sk-[A-Za-z0-9]{16,}|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----)")
STOP_CHARS = set("的了是要怎么应该我你它这那请帮问答一下一下吗呢和与在有及或为把被从到对关于X100x100办")


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def rewrite_question(question: str, history: Optional[list[dict[str, str]]] = None) -> str:
    rewritten = " ".join(question.strip().split())
    if history and re.search(r"^(它|这个|那个|那|然后|那它|继续)", rewritten):
        previous = next((item.get("content", "") for item in reversed(history) if item.get("content")), "")
        if previous:
            rewritten = f"{previous[-120:]}；追问：{rewritten}"
    return rewritten[:1000]


def allowed_tables(role: str, internal_authorized: bool) -> list[str]:
    # 先选择授权集合，再读取和计算其中的向量。
    return ["public_chunks", "internal_chunks"] if role == "internal" and internal_authorized else ["public_chunks"]


def _dot_cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0 or norm_right == 0:
        return -1.0
    return dot / (norm_left * norm_right)


def _terms(text: str) -> set[str]:
    # “怎么办”等泛化问法字词不算主题证据，避免仅凭问句模板命中知识库。
    cleaned = re.sub(r"[^\w\u3400-\u9fff]", "", text.lower())
    return {char for char in cleaned if char not in STOP_CHARS}

# 用户问题、身份、权限、问题向量
def search_vector(query: str, role: str, internal_authorized: bool, query_vector: list[float]) -> tuple[list[dict[str, Any]], int]:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    init_database(connection)
    rows: list[sqlite3.Row] = []
    for table in allowed_tables(role, internal_authorized):
        # 角色和密级过滤在 SQL 中先完成，再进行向量评分。
        if table == "public_chunks":
            rows.extend(connection.execute(
                "SELECT * FROM public_chunks WHERE classification='public' AND allowed_roles LIKE ?",
                (f'%"{role}"%',),
            ).fetchall())
        elif role == "internal" and internal_authorized:
            rows.extend(connection.execute(
                "SELECT * FROM internal_chunks WHERE classification='top_secret' AND allowed_roles LIKE '%\"internal\"%'"
            ).fetchall())
    connection.close()

    query_terms = _terms(query)
    candidates = []
    for row in rows:
        metadata = dict(row) # 数据库的数据
        roles = json.loads(metadata["allowed_roles"])
        if role not in roles:
            continue
        if metadata["classification"] == "top_secret" and not (role == "internal" and internal_authorized):
            continue
        vector_score = _dot_cosine(query_vector, json.loads(metadata["embedding"])) # 用户问题和数据库数据的的embedding余弦相似度匹配
        metadata["vector_score"] = vector_score
        metadata["score"] = vector_score
        candidates.append(metadata)

    # CandidateK 来自持久化向量的评分结果，不是固定文档列表。
    candidates.sort(key=lambda item: item["vector_score"], reverse=True) # 按相似度排序
    pre_rerank = candidates[:CANDIDATE_K] # top-K的候选集，CANDIDATE_K在配置文件中，20表示取前20个
    # 混合向量相关度和主题词重叠度：仅靠语义相似度可能放入无关问题。
    for item in pre_rerank:
        doc_terms = _terms(f"{item['title']} {item['section']} {item['content']}")
        lexical = len(query_terms & doc_terms) / max(1, len(query_terms)) # 不只用语义相似度，还根据关键词覆盖程度打分。
        item["score"] = 0.8 * item["vector_score"] + 0.2 * lexical # 两个分数共同打分得到最终的分数
    pre_rerank.sort(key=lambda item: item["score"], reverse=True) # 新分数重新排序
    eligible = [item for item in pre_rerank # 设置最低分数
                if item["vector_score"] >= MIN_VECTOR_COSINE
                and item["score"] >= MIN_RERANKED_SCORE]

    # 在 Top-K 和 Context 组装前再次检查授权，防止中途越权。
    eligible = [item for item in eligible if
                role in json.loads(item["allowed_roles"]) and
                (item["classification"] != "top_secret" or (role == "internal" and internal_authorized))]
    return eligible[:FINAL_K], len(rows) #

# 构造给llm的上下文，
def build_context(results: list[dict[str, Any]]) -> tuple[str, int, list[dict[str, Any]]]:
    context_parts = []
    selected = []
    total_tokens = 0
    for item in results:
        block = (
            f"[chunk_id={item['chunk_id']}]\n"
            f"[来源={item['title']} / {item['section']}]\n"
            f"[内容]\n{item['content']}\n[/内容]"
        )
        block_tokens = token_count(block)
        # 只有在 Token 预算内加入的片段，才会成为模型依据和可引用内容。
        if total_tokens + block_tokens > MAX_CONTEXT_TOKENS:
            continue
        context_parts.append(block)
        total_tokens += block_tokens
        selected.append(item)
    return "\n\n".join(context_parts), total_tokens, selected


def _mock_llm(question: str, context: list[dict[str, Any]]) -> dict[str, Any]:
    """Explicit extractive Mock LLM fallback, used only when no LLM endpoint is configured."""
    best = context[0]
    content = best["content"].strip()
    steps = [part.strip(" -•\n") for part in re.split(r"[；\n]+", content) if part.strip(" -•\n")]
    quote = content[: min(30, len(content))]
    answer = f"根据授权知识片段，{content}"
    return {
        "answer": answer,
        "steps": steps[:8],
        "warnings": ["该问题需要人工核验。"] if HIGH_RISK.search(question) else [],
        "citations": [{"chunkId": best["chunk_id"], "quote": quote}],
        "confidence": max(0.0, min(0.99, best["vector_score"])),
        "needHuman": bool(HIGH_RISK.search(question)),
        "handoffReason": "需要人工核验业务信息" if HIGH_RISK.search(question) else None,
    }


def _call_llm(
    question: str, context_text: str, context: list[dict[str, Any]],
    history: Optional[list[dict[str, str]]] = None,
) -> tuple[dict[str, Any], str]:
    if LLM_MODE == "mock":
        return _mock_llm(question, context), "mock-extractive-v1"
    try:
        return call_deepseek(question, context_text, history, None)
    except LLMServiceError as exc:
        # 仅网络或超时故障使用授权 Context 兜底；模型 ID、鉴权、参数等错误必须显式报告。
        if exc.kind in ("network", "timeout"):
            return _mock_llm(question, context), "mock-fallback-v1"
        raise


def validate_generation(generated: dict[str, Any], authorized_context: list[dict[str, Any]]) -> tuple[bool, list[dict[str, str]]]:
    # 模型输出一律视为不可信；每条引用都必须属于本次请求的授权 Context。
    if not isinstance(generated, dict):
        return False, []
    required_fields = {"answer", "steps", "warnings", "citations", "confidence", "needHuman", "handoffReason"}
    if not required_fields.issubset(generated):
        return False, []
    by_id = {item["chunk_id"]: item for item in authorized_context}
    citations = generated.get("citations")
    if not isinstance(citations, list) or not citations:
        return False, []
    # 模型可能为同一片段列出多个结论；同一 chunk 只保留第一条，避免重复引用触发数量上限。
    unique_citations = []
    seen_chunk_ids = set()
    for citation in citations:
        chunk_id = citation.get("chunkId") if isinstance(citation, dict) else None
        if chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk_id)
        unique_citations.append(citation)
    if len(unique_citations) > FINAL_K:
        return False, []
    valid = []
    for citation in unique_citations:
        if not isinstance(citation, dict):
            return False, []
        chunk_id = citation.get("chunkId")
        quote = citation.get("quote")
        item = by_id.get(chunk_id) if isinstance(chunk_id, str) else None
        if not item or not isinstance(quote, str) or not quote or quote not in item["content"]:
            return False, []
        # 模型可能无视提示词复制整句内容；只保留已验证原文的前 30 字，返回短且准确的引用。
        valid.append({"chunkId": chunk_id, "quote": quote[:30]})
    answer = generated.get("answer")
    output_text = json.dumps(generated, ensure_ascii=False, default=str)
    steps = generated.get("steps", [])
    warnings = generated.get("warnings", [])
    confidence = generated.get("confidence", 0.0)
    need_human = generated.get("needHuman", False)
    handoff = generated.get("handoffReason")
    if (not isinstance(answer, str) or not answer.strip() or len(answer) > 5000 or
            not isinstance(steps, list) or len(steps) > 12 or
            any(not isinstance(step, str) or len(step) > 500 for step in steps) or
            not isinstance(warnings, list) or len(warnings) > 12 or
            any(not isinstance(warning, str) or len(warning) > 500 for warning in warnings) or
            isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or
            not math.isfinite(confidence) or not 0 <= confidence <= 1 or
            not isinstance(need_human, bool) or
            (handoff is not None and (not isinstance(handoff, str) or len(handoff) > 500)) or
            SENSITIVE_OUTPUT.search(output_text)):
        return False, []
    if re.search(r"(?:工程口令|私钥|访问令牌)\s*[:：=]", output_text, re.IGNORECASE):
        return False, []
    return True, valid


def safe_source(item: dict[str, Any], citation: dict[str, str]) -> dict[str, Any]:
    return {
        "chunkId": item["chunk_id"], "docId": item["document_id"], "title": item["title"],
        "section": item["section"], "excerpt": item["content"], "quote": citation["quote"],
        "sourcePath": item["source_path"], "version": item["version"],
        "classification": item["classification"], "score": round(float(item["vector_score"]), 4),
    }


def audit_request(
    request_id: str, role: str, internal_authorized: bool, question: str, rewritten: str,
    decision: str, results: list[dict[str, Any]], model_version: str, confidence: float, need_human: bool,
) -> None:
    connection = sqlite3.connect(DATABASE_PATH)
    init_database(connection)
    connection.execute(
        "INSERT INTO audit_log (created_at,request_id,principal_role,authorization,query_hash,rewritten_hash,permission_decision,chunk_ids,model_version,confidence,need_human) VALUES (datetime('now'),?,?,?,?,?,?,?,?,?,?)",
        (request_id, role, "internal-work-order-simulated" if internal_authorized else "default",
         hash_text(question), hash_text(rewritten), decision,
         json.dumps([item["chunk_id"] for item in results]),
         f"{EMBEDDING_MODEL};{model_version}", confidence, int(need_human)),
    )
    connection.commit()
    connection.close()


def answer_question(
    question: str, history: Optional[list[dict[str, str]]], role: str,
    internal_authorized: bool, request_id: str,
) -> dict[str, Any]:
    rewritten = rewrite_question(question, history)
    stages = [
        {"name": "问题改写", "status": "completed"},
        {"name": "Query Embedding", "status": "pending"},
        {"name": "权限过滤", "status": "pending"},
        {"name": "向量检索", "status": "pending"},
        {"name": "Top-K", "status": "pending"},
        {"name": "Context 组装", "status": "pending"},
        {"name": "LLM 生成", "status": "pending"},
        {"name": "引用校验", "status": "pending"},
    ]

    if SECRET_QUERY.search(question) and not (role == "internal" and internal_authorized):
        stages[1]["status"] = "skipped"
        stages[2]["status"] = "completed"
        stages[3]["status"] = "blocked"
        for stage in stages[4:]:
            stage["status"] = "skipped"
        audit_request(request_id, role, internal_authorized, question, rewritten, "blocked-sensitive-query", [], "not-called", 0, True)
        return {
            "answer": "该问题需要授权人工处理。", "steps": [],
            "warnings": ["为保护受限信息，无法提供该问题的自动回答。"],
            "citations": [], "sources": [], "confidence": 0.0, "needHuman": True,
            "handoffReason": "需要授权人工核验", "stages": stages,
            "debug": None, "llmModel": None,
        }

    # 读取索引元数据，并在查询向量检索前应用当前身份过滤。
    stages[2]["status"] = "completed"
    vector = embed_texts([rewritten])[0]
    stages[1]["status"] = "completed"
    results, authorized_count = search_vector(rewritten, role, internal_authorized, vector)
    stages[3]["status"] = "completed"
    stages[4]["status"] = "completed" if results else "no-match"
    if not results:
        # 低相关或无匹配查询在此终止，不组装 Context，也不产生模型调用费用。
        for stage in stages[5:]:
            stage["status"] = "skipped"
        audit_request(request_id, role, internal_authorized, question, rewritten, "below-min-score-or-no-match", [], "not-called", 0, True)
        return {
            "answer": "知识库暂无可靠答案，建议转人工客服核验。", "steps": [],
            "warnings": [], "citations": [], "sources": [], "confidence": 0.0,
            "needHuman": True, "handoffReason": "没有超过相似度阈值的授权知识片段",
            "stages": stages, "debug": None, "llmModel": None,
        }

    context_text, context_tokens, context_items = build_context(results)
    stages[5]["status"] = "completed" if context_items else "no-context"
    if not context_items:
        # Token 预算过滤后 Context 可能为空；没有证据时绝不调用模型。
        for stage in stages[6:]:
            stage["status"] = "skipped"
        audit_request(request_id, role, internal_authorized, question, rewritten, "empty-context", [], "not-called", 0, True)
        return {
            "answer": "知识库暂无可用依据，建议转人工客服核验。", "steps": [],
            "warnings": [], "citations": [], "sources": [], "confidence": 0.0,
            "needHuman": True, "handoffReason": "没有可提供给模型的授权 Context",
            "stages": stages, "debug": None, "llmModel": None,
        }
    try:
        generated, llm_version = _call_llm(rewritten, context_text, context_items, history)
    except LLMServiceError as exc:
        stages[6]["status"] = "failed"
        for stage in stages[7:]:
            stage["status"] = "skipped"
        audit_request(request_id, role, internal_authorized, question, rewritten, "llm-error", context_items, f"{LLM_MODEL}:{exc.kind}", 0, True)
        return {
            "answer": "回答服务暂不可用，请转人工客服处理。", "steps": [],
            "warnings": [], "citations": [], "sources": [], "confidence": 0.0,
            "needHuman": True, "handoffReason": exc.public_reason,
            "stages": stages, "debug": None, "llmModel": None,
        }
    except Exception:
        stages[6]["status"] = "failed"
        for stage in stages[7:]:
            stage["status"] = "skipped"
        audit_request(request_id, role, internal_authorized, question, rewritten, "llm-error", context_items, f"{LLM_MODEL}:internal-error", 0, True)
        return {
            "answer": "回答服务暂不可用，请转人工客服处理。", "steps": [],
            "warnings": [], "citations": [], "sources": [], "confidence": 0.0,
            "needHuman": True, "handoffReason": "LLM 调用失败，请转人工处理。",
            "stages": stages, "debug": None, "llmModel": None,
        }
    stages[6]["status"] = "completed"
    valid, citations = validate_generation(generated, context_items)
    stages[7]["status"] = "completed" if valid else "blocked"
    if not valid:
        audit_request(request_id, role, internal_authorized, question, rewritten, "citation-or-output-validation-failed", context_items, llm_version, 0, True)
        return {
            "answer": "无法校验回答引用，已停止自动回复，请转人工客服。", "steps": [],
            "warnings": [], "citations": [], "sources": [], "confidence": 0.0,
            "needHuman": True, "handoffReason": "引用校验或输出安全检查失败",
            "stages": stages, "debug": None, "llmModel": llm_version,
        }

    item_by_id = {item["chunk_id"]: item for item in context_items}
    sources = [safe_source(item_by_id[citation["chunkId"]], citation) for citation in citations]
    score = max(item["vector_score"] for item in context_items)
    confidence = min(0.99, max(0.0, float(generated.get("confidence", score))))
    need_human = bool(generated.get("needHuman")) or bool(HIGH_RISK.search(question))
    handoff_reason = generated.get("handoffReason") or ("该问题需要人工核验" if need_human else None)
    audit_request(request_id, role, internal_authorized, question, rewritten, "authorized-context-used", context_items, llm_version, confidence, need_human)

    debug = None
    if role in ("agent", "internal"):
        debug = {
            "rewrittenQuestion": rewritten,
            "topK": [{"chunkId": source["chunkId"], "score": source["score"]} for source in sources],
            "authorizedIndexCount": authorized_count,
            "finalCount": len(context_items),
            "contextTokens": context_tokens,
            "embeddingModel": EMBEDDING_MODEL,
            "llmModel": llm_version,
            "authorization": "work-order-simulated" if role == "internal" and internal_authorized else "default",
        }
    warnings = list(generated.get("warnings", []))
    if llm_version == "mock-fallback-v1":
        # 让前端明确显示：已尝试调用 DeepSeek，失败原因是网络连接而非未调用。
        warnings.append("已尝试调用 DeepSeek，但当前服务端无法连接其接口；本次使用授权知识片段兜底。")
    return {
        "answer": generated["answer"], "steps": generated.get("steps", []),
        "warnings": warnings, "citations": citations, "sources": sources,
        "confidence": confidence, "needHuman": need_human, "handoffReason": handoff_reason,
        "stages": stages, "debug": debug, "llmModel": llm_version,
    }
