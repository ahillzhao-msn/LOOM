"""KM Ingest — 知識寫入統一入口。

將洞察/內容寫入 LOOM 向量庫（分塊 + 嵌入 + ChromaDB + 飛輪）。
支援單條文本（Agent solidify）和批量文本（離線掃描攝入）。
backlog 已委託給 Hermes 原生。
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("loom.knowledge.ingest")


def ingest(text: str, target: str = "loom", domain: str = "GENERAL",
           source: str = "", title: str = "") -> dict:
    """將知識寫入指定目標。

    Args:
        text: 知識內容（單條文本，或 Markdown 文檔）
        target: "loom" → 向量庫 | "event" → 飛輪事件
                "memory" → 返回建議（調用方決定）
        domain: 域名
        source: 來源標識
        title: 可選標題

    Returns:
        {"status": str, "target": str, "detail": str, "entries": int}
    """
    if target == "loom":
        return _ingest_to_loom(text, domain, source)
    elif target == "event":
        return _trigger_event(domain)
    elif target == "memory":
        return {"status": "ok", "target": "memory",
                "detail": f"建議寫入 memory: {text[:80]}...",
                "agent_action": "memory", "entries": 0}
    return {"status": "error", "target": target,
            "detail": f"未知目標: {target}", "entries": 0}


def batch_ingest(texts: list[str], domain: str = "GENERAL",
                 source: str = "batch") -> dict:
    """批量寫入——離線掃描場景。

    每條文本獨立分塊、嵌入、寫入。適合 cron 任務批量攝入。
    與 ingest() 使用相同的底層管道。

    Args:
        texts: 文本列表（每條可為一段洞察或一篇完整文檔）
        domain: 域名
        source: 來源標識

    Returns:
        {"status": str, "total_texts": int, "total_chunks": int,
         "failed": int, "detail": str}
    """
    total_chunks = 0
    failed = 0
    for i, text in enumerate(texts):
        result = _ingest_to_loom(text, domain, source)
        if result.get("status") == "ok":
            total_chunks += result.get("entries", 0)
        else:
            failed += 1
            logger.warning("batch_ingest[%d]: %s", i, result.get("detail", "?"))
    return {
        "status": "ok" if failed == 0 else "partial",
        "total_texts": len(texts),
        "total_chunks": total_chunks,
        "failed": failed,
        "detail": f"{len(texts)} 篇 → {total_chunks} chunks ({failed} failed)",
    }


def batch_ingest_files(file_paths: list[str], domain: str = "GENERAL",
                       source: str = "file_scan") -> dict:
    """批量攝入檔案——離線掃描場景。

    讀取檔案內容，每檔案作為一篇文檔攝入。
    支援 .md / .txt 格式。其他格式需先用 doc2md 轉換。

    Args:
        file_paths: 檔案路徑列表
        domain: 域名
        source: 來源標識

    Returns:
        同 batch_ingest()
    """
    texts = []
    failed_reads = 0
    for fp in file_paths:
        try:
            content = Path(fp).read_text(encoding="utf-8")
            if content.strip():
                # 附加檔名作為上下文
                fname = Path(fp).name
                texts.append(f"# {fname}\n\n{content}")
        except Exception as e:
            failed_reads += 1
            logger.warning("batch_ingest_files: 無法讀取 %s: %s", fp, e)

    result = batch_ingest(texts, domain=domain, source=source)
    result["files_read"] = len(file_paths) - failed_reads
    result["files_failed"] = failed_reads
    return result


# ══════════════════════════════════════════════════
# 內部
# ══════════════════════════════════════════════════

def _ingest_to_loom(text: str, domain: str = "GENERAL",
                     source: str = "") -> dict:
    """寫入 LOOM 向量庫（分塊 + 嵌入 + ChromaDB + 飛輪事件）。

    保留 chunk_document() 的全部結構化元數據：
    標題鏈 (heading_chain)、品質分數 (quality_score)、
    字元數 (chars)、分塊序號 (chunk_index)。
    """
    try:
        from loom.knowledge.rag.vector_store import VectorStore
        from loom.knowledge.rag.chunker import chunk_document
        from loom.knowledge.flywheel_events import EventChecker

        vs = VectorStore()
        chunks = chunk_document(text, domain=domain) or [text]

        texts = []
        metadatas = []
        ids = []

        for j, chunk in enumerate(chunks):
            if isinstance(chunk, str):
                # 降級：chunker 未產出結構化塊
                content = chunk
                meta = {"domain": domain, "source": source or "ingest"}
            else:
                # 結構化塊：保留 chunker 的所有元數據
                content = chunk.get("content", str(chunk))
                meta = {
                    "domain": domain,
                    "source": source or chunk.get("source", "ingest"),
                    "heading": chunk.get("heading", ""),
                    "heading_chain": ",".join(chunk.get("heading_chain", [])),
                    "quality_score": chunk.get("quality_score", 0.0),
                    "chars": chunk.get("chars", len(content)),
                    "chunk_index": chunk.get("chunk_index", j),
                }

            texts.append(content)
            metadatas.append(meta)
            _uid = hashlib.md5(content.encode()).hexdigest()[:12]
            ids.append(f"{domain}_ingest_{_uid}")

        vs.add(texts, metadatas=metadatas, ids=ids)

        # 飛輪事件
        ec = EventChecker(vs, None)
        ec.after_ingest(domain, vs.count_by_domain(domain))

        return {"status": "ok", "target": "loom",
                "detail": f"已寫入 {domain}: {len(chunks)} 條",
                "entries": len(chunks)}
    except Exception as e:
        logger.warning("LOOM 寫入失敗: %s", e)
        return {"status": "error", "target": "loom",
                "detail": str(e), "entries": 0}


def _trigger_event(domain: str) -> dict:
    """觸發飛輪事件檢查。"""
    try:
        from loom.knowledge.rag.vector_store import VectorStore
        from loom.knowledge.flywheel_events import EventChecker

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
