"""
向量存储模块 — Chroma 封装。

提供增/删/查/统计接口。全部操作走 embedding 模型。
"""
from __future__ import annotations

import uuid
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from kafed.config import get_config
from kafed.knowledge.rag.embedding import embed_texts


class VectorStore:
    """Chroma 持久化向量存储封装。"""

    def __init__(self) -> None:
        cfg = get_config()
        self._client = chromadb.PersistentClient(
            path=str(cfg.chroma_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=cfg.chroma_collection
        )
        self._dim = cfg.embedding_dim
        self._config = cfg

    # ── 写入 ──────────────────────────────────────────────

    def add(self, texts: list[str], metadatas: list[dict[str, Any]],
            ids: list[str] | None = None) -> list[str]:
        """添加文档（自动嵌入）。返回 IDs。"""
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in texts]
        embeddings = embed_texts(texts)
        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )
        return ids

    def delete(self, ids: list[str]) -> None:
        """按 ID 删除文档。"""
        self._collection.delete(ids=ids)

    # ── 查询 ──────────────────────────────────────────────

    def search(self, query: str, top_k: int | None = None,
               where: dict[str, Any] | None = None) -> list[dict]:
        """语义搜索。返回排序后的结果列表。"""
        cfg = get_config()
        top_k = top_k or cfg.top_k_default
        query_emb = embed_texts([query])[0]
        results = self._collection.query(
            query_embeddings=[query_emb],
            n_results=top_k,
            where=where,
        )
        out = []
        if results["ids"]:
            for i in range(len(results["ids"][0])):
                out.append({
                    "id": results["ids"][0][i],
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "score": 1.0 - (results["distances"][0][i]
                                    if results.get("distances") else 0),
                })
        return out

    # ── 统计 ──────────────────────────────────────────────

    def count(self) -> int:
        """总条目数。"""
        return self._collection.count()

    def count_by_domain(self, domain: str) -> int:
        """按域名统计条目数。"""
        results = self._collection.get(
            where={"domain": domain},
        )
        return len(results["ids"]) if results and results.get("ids") else 0

    def get_all(self, limit: int = 10_000) -> dict:
        """批量读取（用于打包/导出）。"""
        return self._collection.get(limit=limit)

    def get_by_domain(self, domain: str, limit: int = 10_000) -> dict:
        """按域批量读取。"""
        return self._collection.get(
            where={"domain": domain},
            limit=limit,
        )

    # ── 领域列表 ──────────────────────────────────────────

    def list_domains(self) -> list[str]:
        """返回所有已知域名。"""
        all_data = self._collection.get(limit=100_000)
        domains = set()
        if all_data["metadatas"]:
            for m in all_data["metadatas"]:
                if m and "domain" in m:
                    domains.add(m["domain"])
        return sorted(domains)
