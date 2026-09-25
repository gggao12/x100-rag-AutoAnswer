from __future__ import annotations

import os
from pathlib import Path

from .secrets import load_deepseek_settings

# 运行期数据放在源码目录之外的专用数据目录，均为本地可重建产物。
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / ".rag-data"
MODEL_CACHE = DATA_DIR / "models"
DATABASE_PATH = DATA_DIR / "x100-rag.sqlite3"

os.environ.setdefault("HF_HOME", str(MODEL_CACHE))

EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
EMBEDDING_REVISION = "e534609e6b53ac54bd42d8e87995d21a73b90bad"
EMBEDDING_DIMENSION = 512
# 第一阶段余弦下限和最终混合分数阈值根据当前知识库样本校准。
MIN_VECTOR_COSINE = 0.40 # 最低分数限制
MIN_RERANKED_SCORE = 0.60 # 最低分数限制
CANDIDATE_K = 20 # top K 候选20个
FINAL_K = 4 # top K 最终4个
MAX_CONTEXT_TOKENS = 2400 # 交给llm的最大token数量，考虑成本、上下文长度等

PUBLIC_ROLES = ("user", "agent", "internal")
# 这是入库白名单；列表之外的文件（包括绿植备忘）不会解析或向量化。
# 每个入库文档都绑定密级和可访问角色，并随切片写入索引。
DOCUMENTS = (
    {"id": "01_X100_WiFi故障", "file": "01_X100_WiFi故障.md", "classification": "public", "roles": PUBLIC_ROLES},
    {"id": "02_X100设备离线", "file": "02_X100设备离线.md", "classification": "public", "roles": PUBLIC_ROLES},
    {"id": "03_X100升级失败", "file": "03_X100升级失败.md", "classification": "public", "roles": PUBLIC_ROLES},
    {"id": "04_X100密码忘记", "file": "04_X100密码忘记.md", "classification": "public", "roles": PUBLIC_ROLES},
    {"id": "05_X100售后政策", "file": "05_X100售后政策.md", "classification": "public", "roles": PUBLIC_ROLES},
    {"id": "00_X100_绝密_内部手册", "file": "00_X100_绝密_内部手册.md", "classification": "top_secret", "roles": ("internal",)},
)
DOCUMENT_IDS = frozenset(doc["id"] for doc in DOCUMENTS)

DEEPSEEK_SETTINGS = load_deepseek_settings()
DEEPSEEK_CONFIGURED = DEEPSEEK_SETTINGS.configured
LLM_MODE = DEEPSEEK_SETTINGS.mode
LLM_MODEL = DEEPSEEK_SETTINGS.model
DEV_MODE = os.getenv("X100_DEV_MODE", "1") == "1"
