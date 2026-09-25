"""入库与查询共用的固定版本本地 BGE 向量编码器。"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable

from .config import EMBEDDING_MODEL, EMBEDDING_REVISION, MODEL_CACHE


@lru_cache(maxsize=1) # 加载embedding模型，加载一次缓存起来不要每次都加载，embedding模型通常较大，性能优化
def load_embedder():
    # 每个 API 进程只加载一次固定 revision，并使用 CPU 推理以保持环境一致。
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("缺少 PyTorch/Transformers，请先安装 requirements.txt") from exc

    # 加载tokenzier，把人类文字转化成模型能够处理的token
    tokenizer = AutoTokenizer.from_pretrained(
        EMBEDDING_MODEL, revision=EMBEDDING_REVISION, cache_dir=str(MODEL_CACHE)
    )
    # 加载embedding模型
    model = AutoModel.from_pretrained(
        EMBEDDING_MODEL, revision=EMBEDDING_REVISION, cache_dir=str(MODEL_CACHE)
    )
    model.eval() # 选择训练模式还是推理模式
    model.to("cpu")
    return tokenizer, model, torch

# 传入文本，返回向量，batch_size分批次处理，比如100个chunk一次处理16个，内存有限
def embed_texts(texts: Iterable[str], batch_size: int = 16) -> list[list[float]]:
    values = list(texts)
    if not values:
        return []
    tokenizer, model, torch = load_embedder()
    vectors: list[list[float]] = []
    with torch.inference_mode():
        for offset in range(0, len(values), batch_size):
            batch = tokenizer(
                values[offset : offset + batch_size],
                padding=True, # paddind是为了让格式统一，每一片的tokne一样，后续操作方便。
                truncation=True, # 如果文本太长就截断
                max_length=512, # 最大长度512，最多处理512个token
                return_tensors="pt",
            )
            output = model(**batch).last_hidden_state # 每个token生成一组数字表示
            # 只对非 padding token 做均值池化，再进行 L2 归一化供余弦检索使用。
            mask = batch["attention_mask"].unsqueeze(-1).to(output.dtype)
            pooled = (output * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1) # 均值池化，前面每个token一个向量，这里要整个文本一个向量，简单理解就是取平均值
            normalized = torch.nn.functional.normalize(pooled, p=2, dim=1) # 归一化，单位向量统计，为了方便后续余弦相似度检索
            vectors.extend(normalized.cpu().tolist()) # 转回Python list，这个列表就是可以存进数据库的东西
    return vectors

# 计算一个文本有多少token，用于检查文本长度/控制上下文/统计成本/判断是否超过模型限制
def token_count(text: str) -> int:
    tokenizer, _, _ = load_embedder()
    return len(tokenizer.encode(text, add_special_tokens=False))
