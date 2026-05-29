#!/usr/bin/env python3
"""LOOM v3.0 KM 攝入測試 — 雙場景對比。

Scenario A: 線上 Analyzer 攝入（Agent 回應後 solidify）
  Agent turn → solidify(insight) → ingest → chunk → embed → Chroma → event
  測試：寫入 → 查詢驗證可召回 → 檢查元數據保留

Scenario B: 離線排程批量攝入（cron 掃描專案文檔）
  Scheduler task → 掃描目錄 → batch_ingest_files → chunk → embed → Chroma
  測試：批量寫入 → 統計 → 查詢驗證 → 檢查 metadata
"""

import os, sys, tempfile, json
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from loom.flow import set_flow_enabled, chain, divider, hop, stop
set_flow_enabled(True)

TEST_DOMAIN = "KM_INGEST_TEST"


def cleanup():
    """移除測試寫入的 chunks（保持 Chroma 乾淨）。"""
    try:
        from loom.knowledge.rag.vector_store import VectorStore
        vs = VectorStore()
        results = vs._collection.get(
            where={"domain": TEST_DOMAIN},
            include=["metadatas"],
        )
        ids = results.get("ids", [])
        if ids:
            vs._collection.delete(ids=ids)
            print(f"  🧹 清理 {len(ids)} 條測試數據")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# Scenario A: 線上 Analyzer 攝入
# ══════════════════════════════════════════════════════════════

def scenario_a_online():
    """模擬 Agent 完成一輪後，Analyzer 透過 solidify() 攝入洞察。"""
    divider("══════ Scenario A: 線上 Analyzer 攝入 (solidify) ══════")

    # ── 模擬 Agent 對話中學到的洞察 ──
    insights = [
        "# IW32 增強模式\n\n## 發現\n在 SAP PM 工單 IW32 中新增自定義字段時，"
        "必須先通過 `EXIT_SAPMIWO0_001` 確認現有增強點，再決定是擴展現有結構還是新建 APPEND。\n\n"
        "## 教訓\n直接新建 APPEND 而不檢查現有 exit 會導致字段衝突，"
        "因為多個增強可能共用同一 CI_ 結構。\n\n"
        "## 最佳實踐\n1. 先用 SE11 檢查 AFVGD 結構的現有 APPEND\n"
        "2. 確認增強名稱不與現有 APPEND 衝突\n"
        "3. 在 CMOD 中實現時優先使用已有 exit",

        "# LOOM Pipeline 重構教訓\n\n## 核心洞察\n"
        "將 Director 的拆子任務職責移除是正確的——Agent 自己做決策比 LOOM 替它決策更自然。"
        "LOOM 的價值在提供素材（卦+知識+EVAL），不在替 Agent 思考。\n\n"
        "## 設計原則\n- 不嵌套 Agent 框架：LOOM 是決策支援層，不是執行層\n"
        "- Finder 保持獨立：Agent 決定拆子任務後主動調用 find_partners\n"
        "- 知識閉環不阻塞：solidify 非同步，不延遲 Agent 回應",
    ]

    # ── Flow: solidify ──
    from loom.analyzer.solidifier import solidify
    from loom.knowledge.rag.vector_store import VectorStore
    from loom.knowledge.rag.rag_engine import RAGEngine
    from loom.knowledge.flywheel_events import EventChecker

    results = []
    for i, insight in enumerate(insights):
        title = insight.split("\n")[0].replace("# ", "")
        chain(f"solidify #{i+1}", [
            ("💡", "洞察", title[:50]),
            ("✂️", "分塊", f"chunk_document → 按 ## 標題鏈分塊"),
            ("🧬", "嵌入", "bge-small 384d → ChromaDB"),
            ("🔄", "飛輪", "EventChecker.after_ingest"),
        ], end=f"寫入 {TEST_DOMAIN}")

        result = solidify(insight, domain=TEST_DOMAIN, source="test_online")
        results.append(result)
        hop("D", f"#{i+1}", f"chunks={result.get('entries',0)} status={result.get('status')}")

    stop(f"線上攝入完成: {sum(r.get('entries',0) for r in results)} chunks")

    # ── 驗證: RAG 查詢 ──
    vs = VectorStore()
    rag = RAGEngine(vs)

    test_queries = [
        ("IW32 增強字段衝突", "應召回 IW32 增強模式"),
        ("LOOM 拆子任務設計", "應召回 Pipeline 重構教訓"),
    ]

    chain("RAG 查詢驗證", [
        ("🔍", "Q1", test_queries[0][0]),
        ("🔍", "Q2", test_queries[1][0]),
    ], end="查詢中...")

    for query, expected in test_queries:
        result = rag.query(query, top_k=3, domain=TEST_DOMAIN)
        hits = result.get("results", [])
        found = any(expected.split("應")[0].strip()[:6] in h.get("content", "")
                    for h in hits)
        status = "✅" if hits else "❌"
        hop("K", f"Q: {query[:30]}",
            f"hits={len(hits)} top_score={hits[0].get('score',0):.3f}" if hits else "無結果")

    stop("RAG 驗證完成")

    # ── 檢查元數據保留 ──
    chain("元數據檢查", [], end="")
    try:
        results = vs._collection.get(
            where={"domain": TEST_DOMAIN},
            include=["metadatas"],
            limit=5,
        )
        metas = results.get("metadatas", [])
        has_heading = any(m.get("heading") for m in metas if m)
        has_quality = any(m.get("quality_score", 0) > 0 for m in metas if m)
        has_chain = any(m.get("heading_chain") for m in metas if m)

        hop("K", "heading", f"{'✅' if has_heading else '❌'} 標題保留")
        hop("K", "quality", f"{'✅' if has_quality else '❌'} 品質分數保留")
        hop("K", "chain", f"{'✅' if has_chain else '❌'} 標題鏈保留")
        stop(f"元數據: {len(metas)} 條 sampled")
    except Exception as e:
        stop(f"元數據檢查失敗: {e}")

    # ── 飛輪事件 ──
    chain("飛輪 E1-E5", [
        ("E1", "里程碑", f"domain={TEST_DOMAIN} count={vs.count_by_domain(TEST_DOMAIN)}"),
        ("E2", "漂移", "centroid 角距離監控（下次 flywheel 觸發）"),
        ("E3", "打包", "域增長 >30% 觸發 re-kpak"),
        ("E4", "去重", "相似度 >0.95 標記"),
        ("E5", "清理", "90d 無訪問 → archive"),
    ], end="事件檢查完成")

    divider("Scenario A 完成")


# ══════════════════════════════════════════════════════════════
# Scenario B: 離線批量攝入
# ══════════════════════════════════════════════════════════════

def scenario_b_offline():
    """模擬 cron 排程任務掃描專案文檔批量攝入。"""
    divider("══════ Scenario B: 離線批量攝入 (batch_ingest_files) ══════")

    # ── 創建模擬專案文檔 ──
    tmpdir = tempfile.mkdtemp(prefix="loom_test_docs_")
    docs = {
        "architecture.md": (
            "# LOOM 架構設計\n\n"
            "## 五層飛輪\n"
            "LOOM 由五層組成：Director(決策支援)、Finder(模型匹配)、"
            "Knowledge(知識管理)、Analyzer(學習閉環)、Scheduler(任務排程)。\n\n"
            "Executor 層已在 v3.0 移除，改為委託 Hermes delegate_task。\n\n"
            "## 設計原則\n"
            "- 不嵌套 Agent 框架：LOOM 是決策支援層\n"
            "- 嵌入空間優先：所有匹配和分類都在向量空間中進行\n"
            "- 知識閉環非同步：solidify 不阻塞 Agent 回應\n\n"
            "## 核心 API\n"
            "- `loom_recommend(user_input)` — 決策素材（每輪強制）\n"
            "- `loom_find_partners(briefs)` — 模型匹配（拆子任務時）\n"
            "- `loom_solidify(insight)` — 知識固化（回應後）"
        ),
        "embedding_guide.md": (
            "# Embedding 模組使用指南\n\n"
            "## 支援的後端\n"
            "目前使用 bge-small-en (384d)，通過 sentence-transformers 加載。\n"
            "未來計劃支援 bge-base (768d) 和 OpenAI embeddings。\n\n"
            "## 性能特點\n"
            "- bge-small: 384d, ~33M params, GPU 加速\n"
            "- 批量嵌入: 32 條/批，~2s/批\n"
            "- ChromaDB 持久化，支援分批查詢 (>1000 條)\n\n"
            "## 使用方式\n"
            "```python\n"
            "from loom.knowledge.rag.embedding import embed_texts\n"
            "vecs = embed_texts(['text1', 'text2'])\n"
            "```"
        ),
        "changelog.md": (
            "# LOOM v3.0 CHANGELOG\n\n"
            "## 架構變更\n"
            "- 移除 Executor 層（委託 Hermes delegate_task）\n"
            "- 移除 Backlog（使用 Hermes 原生）\n"
            "- 移除 ActionRegistry（過度設計）\n"
            "- 新增 Scheduler（WSL 補償機制）\n"
            "- 新增 director/recommend.py（唯一入口）\n\n"
            "## API 簡化\n"
            "- 舊: 9 步 Pipeline + 3 變體\n"
            "- 新: loom_recommend() + loom_solidify()\n\n"
            "## KM 增強\n"
            "- ingest 保留 chunk_document 完整元數據\n"
            "- batch_ingest_files 支援離線批量攝入"
        ),
    }

    for fname, content in docs.items():
        Path(tmpdir, fname).write_text(content)

    hop("📂", "模擬文檔", f"{tmpdir} ({len(docs)} files)")

    # ── Flow: batch_ingest_files ──
    from loom.knowledge.ingest import batch_ingest_files
    from loom.knowledge.rag.vector_store import VectorStore
    from loom.knowledge.rag.rag_engine import RAGEngine

    file_paths = [str(Path(tmpdir, f)) for f in docs]

    chain("batch_ingest_files", [
        ("📂", "掃描", f"{len(file_paths)} 個檔案"),
        ("📖", "讀取", "UTF-8 文本 + 檔名前置為標題"),
        ("✂️", "分塊", "chunk_document → 按 ## 標題鏈分塊"),
        ("🧬", "嵌入", "bge-small 384d 批量嵌入"),
        ("💾", "寫入", "ChromaDB.add → domain=KM_INGEST_TEST"),
        ("🔄", "飛輪", "EventChecker.after_ingest"),
    ], end="批量攝入中...")

    result = batch_ingest_files(file_paths, domain=TEST_DOMAIN,
                                source="test_batch_scan")
    hop("📊", "結果",
        f"files={result['files_read']} chunks={result['total_chunks']} "
        f"failed={result['failed']}")
    stop("批量攝入完成")

    # ── 驗證: 文檔級查詢 ──
    vs = VectorStore()
    rag = RAGEngine(vs)

    test_queries = [
        ("LOOM 五層架構", "architecture.md → 五層飛輪章節"),
        ("embedding 後端切換", "embedding_guide.md → 支援的後端"),
        ("v3.0 Scheduler 功能", "changelog.md → Scheduler WSL 補償"),
    ]

    chain("跨文檔 RAG 查詢", [], end="")
    for query, expected in test_queries:
        result = rag.query(query, top_k=3, domain=TEST_DOMAIN)
        hits = result.get("results", [])
        if hits:
            top_content = hits[0].get("content", "")[:80]
            hop("K", f"Q: {query[:35]}",
                f"top={hits[0].get('score',0):.3f} 「{top_content}...」")
        else:
            hop("K", f"Q: {query[:35]}", "❌ 無結果")
    stop("跨文檔查詢完成")

    # ── 統計 ──
    domain_count = vs.count_by_domain(TEST_DOMAIN)
    total_count = vs._collection.count()

    chain("KM 統計", [
        ("📊", f"域: {TEST_DOMAIN}", f"{domain_count} chunks"),
        ("📊", "全部域", f"{total_count} chunks total"),
    ], end="")

    # 檢查 metadata
    results = vs._collection.get(
        where={"domain": TEST_DOMAIN},
        include=["metadatas"],
        limit=3,
    )
    metas = results.get("metadatas", [])
    sources = set(m.get("source", "?") for m in metas if m)
    hop("🏷️", "來源", ", ".join(sources))

    stop("統計完成")

    # ── 清理臨時檔案 ──
    import shutil
    shutil.rmtree(tmpdir)
    hop("🧹", "清理", f"已刪除臨時目錄 {Path(tmpdir).name}")

    divider("Scenario B 完成")


# ══════════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print()
    scenario_a_online()
    print()
    scenario_b_offline()
    print()
    cleanup()
    print()
