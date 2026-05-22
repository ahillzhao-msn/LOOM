"""
KAFED 本地后端 — 直接导入模块，零 HTTP 开销。

与 HTTP 后端（KafedClient）共享同一接口，可无缝切换。

用法:
    from kafed.client.local_backend import KafedLocalBackend
    backend = KafedLocalBackend()
    result = backend.query("IW31 是什么？", domain="SAP_PM")
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# ── 已删除旧 sys.path hack ── KAFED 现在是可安装包


class KafedLocalBackend:
    """直接导入 KAFED 模块的本地后端。

    共享全局的 VectorStore / embedding 模型单例。
    无需启动 FastAPI 服务。
    """

    _initialized = False
    _vs = None
    _rag = None
    _checker = None

    def __init__(self) -> None:
        if not self._initialized:
            self._init_backend()

    @classmethod
    def _init_backend(cls) -> None:
        """惰性初始化（只运行一次）。"""
        from kafed.config import get_config
        from kafed.knowledge.rag.embedding import get_model
        from kafed.knowledge.rag.vector_store import VectorStore
        from kafed.knowledge.rag.rag_engine import RAGEngine
        from kafed.knowledge.flywheel.event_checker import EventChecker
        from kafed.knowledge.rag.chunker import chunk_document
        # 预热嵌入模型
        get_model()

        cls._config = get_config()
        cls._vs = VectorStore()
        cls._rag = RAGEngine(cls._vs)
        cls._checker = EventChecker(cls._vs, cls._rag)
        cls._initialized = True

    # ── 摄入 ──────────────────────────────────────────────

    def ingest(self, file_path: str | Path, domain: str | None = None) -> dict:
        """摄入 MD/TXT 文件。domain=None 时自动分类。"""
        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "message": f"文件不存在: {path}"}

        if path.suffix.lower() not in (".md", ".markdown", ".txt"):
            return {"status": "error",
                    "message": f"只接受 MD/TXT（收到 {path.suffix}）"}

        text = path.read_text(encoding="utf-8", errors="replace")
        if domain is None:
            from kafed.knowledge.classify.classify import classify
            domain = classify(text[:500]).get("domain", "GENERAL")
        return self._process_text(text, path.name, domain)

    def ingest_text(self, text: str, filename: str = "inline.md",
                    domain: str | None = None) -> dict:
        """直接摄入文本。domain=None 时自动分类。"""
        if domain is None:
            from kafed.knowledge.classify.classify import classify
            domain = classify(text[:500]).get("domain", "GENERAL")
        return self._process_text(text, filename, domain)

    def _process_text(self, text: str, source: str, domain: str) -> dict:
        """共享处理逻辑（与 HTTP 后端一致）。"""
        from kafed.knowledge.rag.chunker import chunk_document

        chunks = chunk_document(text, domain=domain)
        if not chunks:
            return {"status": "warning", "chunks": 0, "domain": domain}

        texts = [c["content"] for c in chunks]
        metadatas = [
            {
                "source": source,
                "domain": domain,
                "heading": c.get("heading") or "",
                "heading_chain": " > ".join(c.get("heading_chain", [])),
                "chunk_index": c["chunk_index"],
                "quality_score": c["quality_score"],
                "quality_issues": ",".join(c.get("quality_issues", [])),
                "chars": c["chars"],
            }
            for c in chunks
        ]

        self._vs.add(texts, metadatas)
        events = self._checker.after_ingest(domain, len(chunks))

        return {
            "status": "ok",
            "chunks": len(chunks),
            "domain": domain,
            "events": events,
        }

    # ── 查询 ──────────────────────────────────────────────

    def query(self, question: str, top_k: int = 5,
              domain: str | None = None) -> dict:
        """语义搜索。"""
        return self._rag.query(question, top_k=top_k, domain=domain)

    # ── 反馈 ──────────────────────────────────────────────

    def feedback(self, query_id: str, doc_id: str, score: int = 5,
                 user_id: str = "hermes") -> dict:
        """记录检索评分。"""
        result = self._rag.feedback(query_id, doc_id, score, user_id)
        events = self._checker.after_feedback()
        return {**result, "events": events}

    # ── 统计 ──────────────────────────────────────────────

    def stats(self) -> dict:
        """系统统计。"""
        domains = self._vs.list_domains()
        centroid_path = self._config.data_dir / "centroids.json"
        centroids_count = 0
        if centroid_path.exists():
            with open(centroid_path) as f:
                centroids_count = len(json.load(f))

        return {
            "total_chunks": self._vs.count(),
            "domains": [
                {"name": d, "count": self._vs.count_by_domain(d)}
                for d in domains
            ],
            "total_feedback": self._rag.count_feedback(),
            "centroids_count": centroids_count,
        }

    def domains(self) -> list[dict]:
        """所有知识域。"""
        return [
            {"name": d, "count": self._vs.count_by_domain(d)}
            for d in self._vs.list_domains()
        ]
