"""LOOM Knowledge — 知识管理与飞轮事件。

子模块:
  rag/        — 向量存储、分块、嵌入、检索引擎
  classify/   — embedding-based 领域分类
  quality/    — 文档质量检测与清洗
  flywheel/   — 飞轮事件触发器 (E1-E5)
  context/    — 知识召回层 (ContextProvider, Director 评前调用)
"""

from loom.knowledge.rag.rag_engine import RAGEngine
from loom.knowledge.rag.vector_store import VectorStore
from loom.knowledge.rag.chunker import chunk_document
from loom.knowledge.rag.embedding import embed_texts, embed_query, get_model
from loom.knowledge.classify.classify import classify, build_centroids, load_centroids
from loom.knowledge.classify.domain_registry import DomainRegistry
from loom.knowledge.classify.embedding_space import Registry, Entity
from loom.knowledge.quality.quality import clean_text, compute_quality_score
from loom.knowledge.flywheel_events import EventChecker
from loom.knowledge.context.context_provider import ContextProvider, ContextBundle, ContextItem

__all__ = [
    "RAGEngine", "VectorStore", "chunk_document",
    "embed_texts", "embed_query", "get_model",
    "classify", "build_centroids", "load_centroids",
    "DomainRegistry", "Registry", "Entity",
    "clean_text", "compute_quality_score",
    "EventChecker",
    "ContextProvider", "ContextBundle", "ContextItem",
]
