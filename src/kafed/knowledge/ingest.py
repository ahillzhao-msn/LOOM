"""KM Ingest — 知識寫入統一入口。

取代原來散落在 hub.absorb() 和 hub.solidify() 的重複 RAG 寫入邏輯。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger("kafed.knowledge.ingest")


def ingest(text: str, target: str = "kafed", domain: str = "GENERAL",
           source: str = "", title: str = "") -> dict:
    """將知識寫入指定目標。

    Args:
        text: 知識內容
        target: "kafed" → KAFED 向量庫 | "backlog" → backlog 待辦
                "event" → 觸發飛輪事件 | "memory" → 返回建議（由調用方決定）
        domain: 域名（kafed/event 目標使用）
        source: 來源標識
        title: 可選標題（backlog 目標使用）

    Returns:
        {"status": str, "target": str, "detail": str, "entries": int}
    """
    if target == "kafed":
        return _ingest_to_kafed(text, domain, source)
    elif target == "backlog":
        return _ingest_to_backlog(title or text[:80], text[:200])
    elif target == "event":
        return _trigger_event(domain)
    elif target == "memory":
        return {"status": "ok", "target": "memory",
                "detail": f"建議寫入 memory: {text[:80]}...",
                "agent_action": "memory", "entries": 0}
    return {"status": "error", "target": target,
            "detail": f"未知目標: {target}", "entries": 0}


def _ingest_to_kafed(text: str, domain: str = "GENERAL",
                     source: str = "") -> dict:
    """寫入 KAFED 向量庫（分塊 + 嵌入 + ChromaDB + 飛輪事件）。"""
    try:
        from kafed.knowledge.rag.vector_store import VectorStore
        from kafed.knowledge.rag.chunker import chunk_document
        from kafed.knowledge.flywheel.event_checker import EventChecker

        vs = VectorStore()
        chunks = chunk_document(text) or [text]

        texts = []
        metadatas = []
        ids = []
        for j, chunk in enumerate(chunks):
            texts.append(chunk if isinstance(chunk, str) else chunk.get("content", str(chunk)))
            metadatas.append({
                "domain": domain,
                "source": source or "ingest",
            })
            _uid = hashlib.md5(texts[-1].encode()).hexdigest()[:12]
            ids.append(f"{domain}_ingest_{_uid}")

        vs.add(texts, metadatas=metadatas, ids=ids)

        ec = EventChecker(vs, None)
        ec.after_ingest(domain, vs.count_by_domain(domain))

        return {"status": "ok", "target": "kafed",
                "detail": f"已寫入 {domain}: {len(chunks)} 條",
                "entries": len(chunks)}
    except Exception as e:
        logger.warning("KAFED 寫入失敗: %s", e)
        return {"status": "error", "target": "kafed",
                "detail": str(e), "entries": 0}


def _ingest_to_backlog(title: str, description: str = "") -> dict:
    """推入 backlog（委託 knowledge/backlog.py）。"""
    try:
        from kafed.backlog import push as bp
        ok = bp(title, value=0.7, description=description)
        return {"status": "ok" if ok else "error", "target": "backlog",
                "detail": f"已推入 backlog: {title[:60]}", "entries": 1}
    except Exception as e:
        return {"status": "error", "target": "backlog",
                "detail": str(e), "entries": 0}


def _trigger_event(domain: str) -> dict:
    """觸發飛輪事件檢查。"""
    try:
        from kafed.knowledge.rag.vector_store import VectorStore
        from kafed.knowledge.flywheel.event_checker import EventChecker

        vs = VectorStore()
        ec = EventChecker(vs, None)
        count = vs.count_by_domain(domain)
        events = ec.after_ingest(domain, count)
        return {"status": "ok", "target": "event",
                "detail": f"E1-E5 檢查 {domain}: {len(events)} 事件",
                "entries": len(events)}
    except Exception as e:
        return {"status": "error", "target": "event",
                "detail": str(e), "entries": 0}


def backlog_check() -> list[dict]:
    """檢查 backlog 待辦（委託 knowledge/backlog.py）。"""
    try:
        from kafed.backlog import check
        return check()
    except Exception:
        return []


def backlog_push(title: str, value: float = 0.7) -> bool:
    """推入 backlog（委託 knowledge/backlog.py）。"""
    try:
        from kafed.backlog import push
        return push(title, value=value)
    except Exception:
        return False
