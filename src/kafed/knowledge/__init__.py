"""KAFED Knowledge — 知识管理与飞轮事件。

子模块:
  rag/        — 向量存储、分块、嵌入、检索引擎
  classify/   — embedding-based 领域分类
  quality/    — 文档质量检测与清洗
  flywheel/   — 飞轮事件触发器 (E1-E5)
  context/    — 知识召回层 (ContextProvider, Director 评前调用)
"""

from kafed.knowledge.rag.rag_engine import RAGEngine
from kafed.knowledge.rag.vector_store import VectorStore
from kafed.knowledge.rag.chunker import chunk_document
from kafed.knowledge.rag.embedding import embed_texts, embed_query, get_model
from kafed.knowledge.classify.classify import classify, build_centroids, load_centroids
from kafed.knowledge.classify.domain_registry import DomainRegistry
from kafed.knowledge.classify.embedding_space import Registry, Entity
from kafed.knowledge.quality.quality import clean_text, compute_quality_score
from kafed.knowledge.flywheel_events import EventChecker
from kafed.knowledge.context.context_provider import ContextProvider, ContextBundle, ContextItem

__all__ = [
    "RAGEngine", "VectorStore", "chunk_document",
    "embed_texts", "embed_query", "get_model",
    "classify", "build_centroids", "load_centroids",
    "DomainRegistry", "Registry", "Entity",
    "clean_text", "compute_quality_score",
    "EventChecker",
    "ContextProvider", "ContextBundle", "ContextItem",
]
