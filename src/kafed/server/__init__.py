"""
KAFED server backward compatibility shim.
All server.* modules have moved to knowledge/ subpackages.
This shim re-exports the key symbols for existing callers.
"""
from kafed.knowledge.rag.chunker import chunk_document
from kafed.knowledge.rag.embedding import get_model
from kafed.knowledge.rag.vector_store import VectorStore
from kafed.knowledge.rag.rag_engine import RAGEngine
from kafed.knowledge.flywheel.event_checker import EventChecker
from kafed.knowledge.classify.classify import classify, build_centroids, load_centroids
from kafed.knowledge.quality.quality import clean_text, compute_quality_score
from kafed.config import get_config
from kafed.schemas import KnowledgeLevel, KnowledgeType, SourceType

__all__ = [
    "chunk_document", "get_model", "VectorStore", "RAGEngine",
    "EventChecker", "classify", "build_centroids", "load_centroids",
    "clean_text", "compute_quality_score", "get_config",
    "KnowledgeLevel", "KnowledgeType", "SourceType",
]
