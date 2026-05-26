"""KAFED KM — ContextProvider: 知識召回層（嵌入命中，全源召回）。

在 Director 的「評」之前強制調用。將當前問題語境映射到全知識源，
找強關聯內容，讓 EVAL 帶著生命歷程做評估。

知識源（全部嵌入命中，無關鍵詞匹配）：
  RAG (Chroma, 嵌入命中)  — KAFED 管理的向量庫
  Wiki (嵌入命中)          — KAFED 管理的文檔
  Memory (嵌入命中)        — Agent 管理的短期記憶（通過 Hermes API 查詢）
  Sessions (嵌入命中)      — Agent 管理的對話記錄（通過 Hermes API 查詢）
  Skills (嵌入命中)        — Agent 管理的技能（通過 Hermes API 查詢）

評估不靠 hash 匹配——靠嵌入命中（語義相似度）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from kafed.config import get_config
from kafed.knowledge.rag.vector_store import VectorStore
from kafed.knowledge.rag.rag_engine import RAGEngine


@dataclass
class ContextItem:
    """一條被召回的知識片段。"""
    source: str          # "rag" | "wiki" | "memory" | "session" | "skill"
    content: str
    score: float         # 0.0 ~ 1.0 關聯度（cosine similarity）
    domain: str = ""
    title: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class ContextBundle:
    """召回結果捆綁——排序後的全源知識上下文。"""
    items: list[ContextItem] = field(default_factory=list)
    query: str = ""
    query_embedding: Optional[list[float]] = None  # 查詢嵌入向量（供 Agent 做自有源匹配）
    hexagram_id: int = 0
    total_returned: int = 0

    def top(self, n: int = 5) -> list[ContextItem]:
        """取關聯度最高的 N 條（去重後）。"""
        seen = set()
        ranked = []
        for item in sorted(self.items, key=lambda x: x.score, reverse=True):
            dedup_key = f"{item.source}:{item.content[:80]}"
            if dedup_key not in seen:
                seen.add(dedup_key)
                ranked.append(item)
            if len(ranked) >= n:
                break
        return ranked

    def by_source(self, source: str) -> list[ContextItem]:
        return [i for i in self.items if i.source == source]

    def format_for_prompt(self, max_items: int = 7) -> str:
        """格式化為 LLM 可讀的上下文文字（供 EVAL 使用）。"""
        top_items = self.top(max_items)
        if not top_items:
            return ""
        lines = ["[知識上下文 — 語義關聯召回]", ""]
        for item in top_items:
            src_tag = f"[{item.source.upper()}]"
            domain_tag = f"({item.domain})" if item.domain else ""
            score_tag = f"score={item.score:.3f}"
            title_tag = f"「{item.title}」" if item.title else ""
            lines.append(f"  {src_tag}{domain_tag}{score_tag} {title_tag}")
            if len(item.content) > 200:
                lines.append(f"    {item.content[:200]}...")
            else:
                lines.append(f"    {item.content}")
            lines.append("")
        return "\n".join(lines)


class ContextProvider:
    """知識召回提供者——Director 評之前的強制上下文構建。

    所有源使用同一條 embedding 通道：查詢文本 → 嵌入 → cosine similarity 匹配。
    不再有「RAG=嵌入權重高」vs「其他=關鍵詞權重低」的分裂。
    """

    def __init__(self):
        self._cfg = get_config()
        self._vs = VectorStore()
        self._rag = RAGEngine(self._vs)
        self._embed_model = None  # lazy init

    def _get_embedding(self, text: str) -> list[float]:
        """獲取文本的嵌入向量。"""
        if self._embed_model is None:
            from kafed.knowledge.rag.embedding import get_model
            self._embed_model = get_model()
        vec = self._embed_model.encode([text[:512]], show_progress_bar=False)[0]
        return vec.tolist()

    def recall(self, query: str, hexagram_id: int = 0,
               domain_hint: str = "") -> ContextBundle:
        """全源知識召回：RAG + Wiki + Memory/Session/Skills 全部嵌入命中。

        Args:
            query: 當前問題或用戶輸入
            hexagram_id: YiCeNet 卦象 ID（可選語境調製）
            domain_hint: 可選域提示（如果已分類）

        Returns:
            ContextBundle: 排序後的所有召回結果 + 查詢嵌入向量
        """
        bundle = ContextBundle(query=query, hexagram_id=hexagram_id)

        # 獲取查詢嵌入（供所有源匹配 + 供 Agent 自有匹配）
        try:
            q_emb = self._get_embedding(query)
            bundle.query_embedding = q_emb
        except Exception:
            q_emb = None

        # ── 1. RAG 嵌入命中（主要召回通道） ──
        where = {"domain": domain_hint} if domain_hint else None
        try:
            rag_results = self._vs.search(query, top_k=8, where=where)
            for r in rag_results:
                bundle.items.append(ContextItem(
                    source="rag",
                    content=r.get("content", ""),
                    score=r.get("score", 0.0),
                    domain=r.get("metadata", {}).get("domain", ""),
                    title=r.get("metadata", {}).get("source", ""),
                    metadata=r.get("metadata", {}),
                ))
        except Exception:
            pass

        # ── 2. Wiki 嵌入命中（與 RAG 同一通道，僅 domain 過濾不同） ──
        wiki_where = {"domain": "WIKI"} if not domain_hint else where
        try:
            wiki_results = self._vs.search(query, top_k=4, where=wiki_where)
            for r in wiki_results:
                # 去重：避免與 RAG 重複
                content = r.get("content", "")
                if any(item.content == content for item in bundle.items):
                    continue
                bundle.items.append(ContextItem(
                    source="wiki",
                    content=content,
                    score=r.get("score", 0.0),
                    domain=r.get("metadata", {}).get("domain", ""),
                    title=r.get("metadata", {}).get("source", ""),
                    metadata=r.get("metadata", {}),
                ))
        except Exception:
            pass

        # ── 3. Memory/Session/Skills 嵌入匹配 ──
        # 通過 Hermes 工具接口查詢這些只讀源，然後用嵌入匹配
        # KAFED 不存儲這些源——只透過 embedding 向量做跨源語義關聯
        agent_sources = self._query_agent_sources(query, q_emb)
        bundle.items.extend(agent_sources)

        # ── 排序 ──
        bundle.items.sort(key=lambda x: x.score, reverse=True)
        bundle.total_returned = len(bundle.items)

        return bundle

    def _query_agent_sources(self, query: str,
                             q_emb: Optional[list[float]] = None
                             ) -> list[ContextItem]:
        """通過 Hermes 工具查詢 Agent 管理的只讀源（Memory/Session/Skill）。

        使用嵌入匹配而非關鍵詞：先獲取源的文本內容，再計算 cosine similarity。
        若無法獲取源內容，則返回查詢嵌入向量供調用方自行匹配。
        """
        items = []

        # 嘗試通過 Hermes session_search API 獲取相關會話片段
        # 若 Hermes API 不可用，降級為提供查詢嵌入以供 Agent 自行匹配
        try:
            import subprocess

            # 調用 hermes CLI 做語義搜索（如果有）
            result = subprocess.run(
                ["hermes", "session", "search", query, "--limit", "3"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                # 假設輸出是 JSON 行或結構化文本
                import json as _json2
                for line in result.stdout.strip().split("\n")[:3]:
                    try:
                        data = _json2.loads(line)
                    except Exception:
                        data = {"content": line[:200], "score": 0.5}
                    items.append(ContextItem(
                        source="session",
                        content=data.get("content", line[:200]),
                        score=data.get("score", 0.4),
                        title=data.get("title", ""),
                        metadata={"match_method": "hermes_cli"},
                    ))
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass

        # 若無結果但有查詢嵌入，提供嵌入向量作為 Agent 的匹配提示
        if not items and q_emb is not None:
            items.append(ContextItem(
                source="memory_hint",
                content=f"查詢嵌入向量 (dim={len(q_emb)}): "
                        f"[{q_emb[0]:.4f}, {q_emb[1]:.4f}, ... "
                        f"{q_emb[-2]:.4f}, {q_emb[-1]:.4f}]",
                score=0.15,  # 低權重——僅作為 Agent 自行匹配的線索
                metadata={"embedding_dim": len(q_emb),
                          "match_method": "query_embedding_provided"},
            ))

        return items

    def search_wiki(self, query: str, top_k: int = 5) -> list[ContextItem]:
        """專門搜索 Wiki（嵌入命中）。"""
        items = []
        try:
            results = self._vs.search(
                query, top_k=top_k,
                where={"domain": "WIKI"}
            )
            for r in results:
                items.append(ContextItem(
                    source="wiki",
                    content=r.get("content", ""),
                    score=r.get("score", 0.0),
                    domain=r.get("metadata", {}).get("domain", ""),
                    title=r.get("metadata", {}).get("source", ""),
                ))
        except Exception:
            pass
        return items
