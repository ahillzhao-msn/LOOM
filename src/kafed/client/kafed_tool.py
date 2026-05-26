"""
KAFED Hermes Tool — in-process RAG query, ingest, classify.

Deployment: editable package in Hermes env (pip install -e ~/KAFED).

Usage from Hermes session:
  > kafed_query(query="PM notification process", k=5)
  → {"results": [...], "total": 5, "domain": "SAP_PM"}

  > kafed_ingest(text="...", domain="SAP_PM")
  → {"chunks": 12, "domain": "SAP_PM"}

  > kafed_status()
  → {"chunks": 93115, "domains": 38, "engine": "ready"}
"""

from __future__ import annotations

import json


# Hermes tools discovery
try:
    from tools.registry import registry
except ModuleNotFoundError:
    registry = None


def _safe_result(data, error_prefix="KAFED error"):
    """Wrap result in JSON, catching serialization errors."""
    try:
        if isinstance(data, dict) and "error" in data:
            return json.dumps(data)
        return json.dumps(data, default=str, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"{error_prefix}: {e}"})


# ── Tool functions ──────────────────────────


def kafed_query(query: str, domain: str = "", k: int = 5,
                soft: bool = True) -> str:
    """Query KAFED knowledge base via RAG.

    Args:
        query: Search query text
        domain: Optional domain filter (e.g. "SAP_PM"). Empty = auto-detect
        k: Number of results to return (1-20)
        soft: Enable soft classification for boundary queries
    """
    try:
        from kafed.knowledge.rag.vector_store import VectorStore
        from kafed.knowledge.rag.rag_engine import RAGEngine

        vs = VectorStore()
        engine = RAGEngine(vs)
        results = engine.query(
            question=query,
            top_k=min(max(k, 1), 20),
            domain=domain if domain else None,
            soft=soft,
        )
        return _safe_result(results)
    except Exception as e:
        return _safe_result({"error": str(e)})


def kafed_ingest(text: str, domain: str = "GENERAL",
                 source: str = "hermes_tool") -> str:
    """Ingest text into KAFED knowledge base.

    Args:
        text: Text content to ingest
        domain: Target domain (e.g. "SAP_PM", "CSP_IID")
        source: Source identifier for provenance
    """
    try:
        from kafed.knowledge.ingest import ingest

        result = ingest(text=text, domain=domain, source=source)
        return _safe_result(result)
    except Exception as e:
        return _safe_result({"error": str(e)})


def kafed_status() -> str:
    """KAFED system status: chunk count, domains, engine health."""
    try:
        from kafed.knowledge.rag.vector_store import VectorStore
        from kafed.config import get_config

        cfg = get_config()
        vs = VectorStore()

        # Access Chroma collection for stats
        collection = vs._collection
        count = collection.count()

        # Domain distribution
        results = collection.get(include=["metadatas"])
        domains = {}
        for meta in results.get("metadatas", []):
            d = meta.get("domain", "UNKNOWN") if meta else "UNKNOWN"
            domains[d] = domains.get(d, 0) + 1

        return _safe_result({
            "chunks": count,
            "domains": len(domains),
            "domain_distribution": domains,
            "chroma_path": str(cfg.chroma_path),
            "engine": "ready",
        })
    except Exception as e:
        return _safe_result({
            "chunks": 0,
            "domains": 0,
            "engine": "error",
            "error": str(e),
        })


def kafed_classify(text: str) -> str:
    """Classify text into KAFED domain.

    Args:
        text: Text to classify
    """
    try:
        from kafed.knowledge.classify.classify import classify

        result = classify(text)
        return _safe_result(result)
    except Exception as e:
        return _safe_result({"error": str(e)})


# ── Hermes tool registration ────────────────

if registry is not None:

    def _check_kafed():
        """Check if KAFED is importable."""
        try:
            import kafed  # noqa: F401
            return True
        except ImportError:
            return False

    registry.register(
        name="kafed_query",
        toolset="kafed",
        schema={
            "name": "kafed_query",
            "description": "Search KAFED knowledge base via RAG. Returns ranked chunks with domain classification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query text"
                    },
                    "domain": {
                        "type": "string",
                        "description": "Optional domain filter (e.g. SAP_PM). Empty = auto-detect",
                        "default": ""
                    },
                    "k": {
                        "type": "integer",
                        "description": "Number of results (1-20)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20
                    },
                    "soft": {
                        "type": "boolean",
                        "description": "Enable soft classification for boundary queries",
                        "default": True
                    }
                },
                "required": ["query"]
            }
        },
        handler=lambda args, **kw: kafed_query(
            query=args.get("query", ""),
            domain=args.get("domain", ""),
            k=args.get("k", 5),
            soft=args.get("soft", True),
        ),
        check_fn=_check_kafed,
        requires_env=[],
    )

    registry.register(
        name="kafed_ingest",
        toolset="kafed",
        schema={
            "name": "kafed_ingest",
            "description": "Ingest text content into KAFED knowledge base. Chunks, embeds, and stores.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text content to ingest"
                    },
                    "domain": {
                        "type": "string",
                        "description": "Target domain (e.g. SAP_PM)",
                        "default": "GENERAL"
                    },
                    "source": {
                        "type": "string",
                        "description": "Source identifier",
                        "default": "hermes_tool"
                    }
                },
                "required": ["text"]
            }
        },
        handler=lambda args, **kw: kafed_ingest(
            text=args.get("text", ""),
            domain=args.get("domain", "GENERAL"),
            source=args.get("source", "hermes_tool"),
        ),
        check_fn=_check_kafed,
        requires_env=[],
    )

    registry.register(
        name="kafed_status",
        toolset="kafed",
        schema={
            "name": "kafed_status",
            "description": "KAFED system status: chunk count, domain distribution, engine health.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        },
        handler=lambda args, **kw: kafed_status(),
        check_fn=_check_kafed,
        requires_env=[],
    )

    registry.register(
        name="kafed_classify",
        toolset="kafed",
        schema={
            "name": "kafed_classify",
            "description": "Classify text into a KAFED domain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to classify"
                    }
                },
                "required": ["text"]
            }
        },
        handler=lambda args, **kw: kafed_classify(
            text=args.get("text", ""),
        ),
        check_fn=_check_kafed,
        requires_env=[],
    )
