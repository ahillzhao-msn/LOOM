"""Knowledge 層動作註冊——對應 KAFED K 層對外介面函數。"""
from kafed.action_registry import registry, Action


def _query_fn(question="", top_k=5, domain=None, soft=True):
    from kafed.knowledge.rag.rag_engine import RAGEngine
    from kafed.knowledge.rag.vector_store import VectorStore
    engine = RAGEngine(VectorStore())
    return engine.query(question=question, top_k=top_k,
                        domain=domain, soft=soft)


def _classify_fn(text=""):
    from kafed.knowledge.classify.classify import classify
    return classify(text)


def _ingest_fn(text="", domain="GENERAL", source=""):
    from kafed.knowledge.ingest import ingest
    return ingest(text=text, domain=domain, source=source)


registry.register(Action(id="knowledge_query",    code="K",
    labels={"zh": "詢", "en": "Query"},
    description="RAG 向量查詢", fn=_query_fn))

registry.register(Action(id="knowledge_classify", code="K",
    labels={"zh": "類", "en": "Classify"},
    description="域分類", fn=_classify_fn))

registry.register(Action(id="knowledge_ingest",   code="K",
    labels={"zh": "納", "en": "Ingest"},
    description="知識攝入", fn=_ingest_fn))

registry.register(Action(id="knowledge_flywheel", code="K",
    labels={"zh": "轉", "en": "Flywheel"},
    description="飛輪事件檢查"))