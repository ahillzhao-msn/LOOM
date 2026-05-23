"""KAFED KM — ContextProvider: 知識召回層（嵌入命中，全源召回）。

在 Director 的「評」之前強制調用。將當前問題語境映射到全知識源，
找強關聯內容，讓 EVAL 帶著生命歷程做評估。

知識源：
  RAG (Chroma, 嵌入命中)  — KAFED 管理的向量庫
  Wiki (嵌入命中)          — KAFED 管理的文檔
  Memory (只讀, 關鍵詞匹配) — Agent 管理的短期記憶
  Sessions (只讀, 關鍵詞)  — Agent 管理的對話記錄
  Skills (只讀, 關鍵詞)    — Agent 管理的技能

評估不靠 hash 匹配——靠嵌入命中（語義相似度）。
"""

from __future__ import annotations

import json
import re
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
    score: float         # 0.0 ~ 1.0 關聯度
    domain: str = ""
    title: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class ContextBundle:
    """召回結果捆綁——排序後的全源知識上下文。"""
    items: list[ContextItem] = field(default_factory=list)
    query: str = ""
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
            # 截斷長內容
            if len(item.content) > 200:
                lines.append(f"    {item.content[:200]}...")
            else:
                lines.append(f"    {item.content}")
            lines.append("")
        return "\n".join(lines)


class ContextProvider:
    """知識召回提供者——Director 評之前的強制上下文構建。"""

    def __init__(self):
        self._cfg = get_config()
        self._vs = VectorStore()
        self._rag = RAGEngine(self._vs)

    def recall(self, query: str, hexagram_id: int = 0,
               domain_hint: str = "") -> ContextBundle:
        """全源知識召回：RAG + Wiki（嵌入命中）+ 只讀掃描。

        Args:
            query: 當前問題或用戶輸入
            hexagram_id: YiCeNet 卦象 ID（可選語境調製）
            domain_hint: 可選域提示（如果已分類）

        Returns:
            ContextBundle: 排序後的所有召回結果
        """
        bundle = ContextBundle(query=query, hexagram_id=hexagram_id)

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

        # ── 2. Wiki 嵌入命中（如果 RAG 結果不足） ──
        if len([i for i in bundle.items if i.score > 0.3]) < 3:
            try:
                wiki_results = self._vs.search(
                    query, top_k=4,
                    where={"domain": "WIKI"} if not domain_hint else where
                )
                for r in wiki_results:
                    bundle.items.append(ContextItem(
                        source="wiki",
                        content=r.get("content", ""),
                        score=r.get("score", 0.0) * 0.95,  # wiki 略低權重
                        domain=r.get("metadata", {}).get("domain", ""),
                        title=r.get("metadata", {}).get("source", ""),
                        metadata=r.get("metadata", {}),
                    ))
            except Exception:
                pass

        # ── 3. Memory/對話/Skills 只讀掃描（關鍵詞匹配） ──
        # 這些由 Agent 管理，KAFED 只能嵌入查詢匹配，不能存儲
        # 真正匹配由 Agent 在運行時提供；這裡只做域分析提示
        keywords = self._extract_keywords(query)
        if keywords:
            for kw in keywords[:5]:
                bundle.items.append(ContextItem(
                    source="memory_hint",
                    content=f"相關關鍵詞: {kw}",
                    score=0.2,  # 低權重，只提示方向
                    metadata={"keyword": kw},
                ))

        # ── 排序 ──
        bundle.items.sort(key=lambda x: x.score, reverse=True)
        bundle.total_returned = len(bundle.items)

        return bundle

    def _extract_keywords(self, text: str, max_kw: int = 8) -> list[str]:
        """從查詢文本中提取關鍵詞（用於只讀源的提示）。"""
        # 分詞：英文單詞 + 中文短語
        tokens = re.findall(r'[a-zA-Z_]+|[一-龥]{2,6}', text)
        # 過濾停用詞
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "this",
                     "that", "it", "to", "for", "of", "in", "on", "with",
                     "and", "or", "not", "be", "do", "did", "does", "has",
                     "have", "had", "能", "会", "是", "的", "了", "在",
                     "有", "不", "就", "也", "这", "那", "出", "去", "来"}
        keywords = [t for t in tokens if t.lower() not in stopwords]
        return keywords[:max_kw]

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
