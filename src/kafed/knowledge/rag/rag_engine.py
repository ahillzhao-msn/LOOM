"""
RAG 引擎 — 检索 + 反馈 + 上下文拼装。

将向量存储的原始检索结果转化为可消费的结构。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kafed.config import get_config
from kafed.knowledge.rag.vector_store import VectorStore


class RAGEngine:
    """知识检索引擎。每请求一个 query_id, 供反馈追踪。"""

    def __init__(self, vector_store: VectorStore) -> None:
        self._vs = vector_store
        self._cfg = get_config()

    # ── 检索 ──────────────────────────────────────────────

    def query(self, question: str, top_k: int | None = None,
              domain: str | None = None) -> dict:
        """检索知识片段，返回匹配 chunks + 域 centroid 上下文。

        返回:
            {
                "query_id": str,
                "question": str,
                "results": [{"id", "content", "metadata", "score"}, ...],
                "total_found": int,
                "domain_context": {
                    "domain": str | None,
                    "centroid": [float] | None,   # 域原型向量
                    "total_entries": int,           # 域内条目数
                },
            }
        """
        cfg = get_config()
        where = {"domain": domain} if domain else None
        results = self._vs.search(question, top_k=top_k, where=where)
        query_id = str(uuid.uuid4())

        # 加载 centroid 域上下文
        centroid_path = cfg.data_dir / "centroids.json"
        domain_context = None
        if domain and centroid_path.exists():
            try:
                with open(centroid_path) as f:
                    centroids = json.load(f)
                if domain in centroids:
                    domain_context = {
                        "domain": domain,
                        "total_entries": centroids[domain].get("count", 0),
                    }
            except Exception:
                pass

        return {
            "query_id": query_id,
            "question": question,
            "results": results,
            "total_found": len(results),
            "domain_context": domain_context,
        }

    # ── 反馈 ──────────────────────────────────────────────

    def feedback(self, query_id: str, doc_id: str, score: int,
                 user_id: str = "anonymous") -> dict:
        """记录用户对检索结果的评分。

        score: 1(差) ~ 5(优)
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query_id": query_id,
            "doc_id": doc_id,
            "score": score,
            "user_id": user_id,
        }
        log_file = self._cfg.feedback_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"status": "ok", "query_id": query_id}

    def count_feedback(self) -> int:
        """累计反馈条目数。"""
        total = 0
        for f in self._cfg.feedback_dir.glob("*.jsonl"):
            total += sum(1 for _ in f.open())
        return total

    # ── 领域 centroid ────────────────────────────────────

    def rebuild_centroids(self) -> dict:
        """为每个域计算 centroid（平均 embedding）。

        从 Chroma 计算为主，从 labels 补充（无 Chroma 数据的域）。
        """
        import numpy as np
        from kafed.knowledge.rag.embedding import embed_texts

        domains = self._vs.list_domains()
        centroids = {}
        for domain in domains:
            data = self._vs.get_by_domain(domain)
            contents = data.get("documents", [])
            if not contents:
                continue
            samples = contents[:200]
            vectors = embed_texts(samples)
            centroid = np.mean(vectors, axis=0).tolist()
            centroids[domain] = centroid

        # 补充 labels 中的域（可能无 Chroma 数据，但参与了分类）
        labels_path = self._cfg.data_dir / "classification_labels.jsonl"
        if labels_path.exists():
            from kafed.knowledge.classify.classify import build_centroids_from_labels
            label_centroids = build_centroids_from_labels()
            for domain, info in label_centroids.items():
                if domain not in centroids:
                    centroids[domain] = info["centroid"]

        # 保存到磁盘
        centroid_path = self._cfg.data_dir / "centroids.json"
        centroid_data = {
            k: {"centroid": v, "count": self._vs.count_by_domain(k) or 0}
            for k, v in centroids.items()
        }
        with open(centroid_path, "w") as f:
            json.dump(centroid_data, f, ensure_ascii=False, indent=2)

        return {d: {"count": self._vs.count_by_domain(d)}
                for d in centroids}

    # ── 成功 QA 追踪（E4 事件） ──────────────────────────

    def track_success(self, query_id: str, question: str,
                      answer: str, domain: str = "GENERAL") -> None:
        """记录一次成功的 QA（用户认可）。"""
        log_dir = self._cfg.data_dir / "successful_qa"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{domain}.jsonl"
        entry = {
            "query_id": query_id,
            "question": question,
            "answer": answer,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(log_file, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
