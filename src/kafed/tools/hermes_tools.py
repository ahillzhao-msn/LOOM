"""KAFED Hermes Tools — Agent 可調用的工具函數。

每個函數都可在 Hermes 工具層註冊，也可直接 import 使用。
函數不依賴 Hermes——純 Python import，零進程開銷。
"""

from __future__ import annotations

import json
from typing import Optional


def _safe_json(data, error_prefix="KAFED error") -> str:
    """安全序列化為 JSON。"""
    try:
        if isinstance(data, dict) and "error" in data:
            return json.dumps(data, ensure_ascii=False)
        return json.dumps(data, default=str, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"{error_prefix}: {e}"}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════
# 核心工具
# ═══════════════════════════════════════════════════════════════════════════

def kafed_recommend(user_input: str) -> str:
    """卦 → 召 → 評：為 Agent 生成決策素材。

    在每次 Agent turn 開始前強制調用。
    返回結構化 JSON，含 inject_text 欄位可直接注入 prompt。

    Args:
        user_input: 使用者原始輸入
    """
    try:
        from kafed.director.recommend import recommend

        rec = recommend(user_input=user_input)
        eval_dict = {}
        if rec.eval_score:
            eval_dict = {
                "f1_scope": rec.eval_score.f1_scope.name,
                "f3_freshness": rec.eval_score.f3_freshness.name,
                "f4_risk": rec.eval_score.f4_risk.name,
                "tier": rec.eval_score.tier,
                "score": rec.eval_score.score,
            }

        return _safe_json({
            "hexagram": rec.hexagram,
            "knowledge_count": len(rec.knowledge_items),
            "knowledge_top3": [
                {"source": i["source"], "score": round(i["score"], 3),
                 "content": i["content"][:150]}
                for i in rec.knowledge_items[:3]
            ],
            "eval": eval_dict,
            "inject_text": rec.inject(),
        })
    except Exception as e:
        return _safe_json({"error": str(e)})


def kafed_find_partners(briefs: str) -> str:
    """為多個子任務匹配最佳模型。

    在 Agent 決定拆子任務後、調用 delegate_task 之前使用。
    每個子任務返回模型候選列表，按匹配度排序。

    Args:
        briefs: JSON 字符串陣列，如 '["工單分析", "代碼審計"]'
    """
    try:
        from kafed.finder.router import Router

        parsed = json.loads(briefs) if isinstance(briefs, str) else briefs
        if not isinstance(parsed, list):
            return _safe_json({"error": "briefs must be a JSON array of strings"})

        router = Router()
        results = router.find_partners(parsed)

        output = []
        for r in results:
            candidates = []
            for c in r.candidates[:5]:
                candidates.append({
                    "name": c.name,
                    "provider": c.provider,
                    "score": round(c.match_score, 3),
                    "domain": c.domain,
                    "cost_per_mtok": getattr(c, "cost_per_mtok", "?"),
                    "online": c.is_online if hasattr(c, "is_online") else True,
                })
            output.append({
                "task_index": r.task_index,
                "task_brief": r.request.task_brief if hasattr(r, "request") else "",
                "candidates": candidates,
            })

        return _safe_json({"results": output})
    except Exception as e:
        return _safe_json({"error": str(e)})


def kafed_solidify(insight: str, domain: str = "GENERAL",
                    source: str = "agent_turn") -> str:
    """將本輪洞察寫入 KAFED 知識庫。

    在 Agent 生成回應後調用。非同步——不阻塞回應。

    Args:
        insight: 洞察內容（教訓、發現、模式）
        domain: 域標籤
        source: 來源標識
    """
    try:
        from kafed.analyzer.solidifier import solidify

        result = solidify(insight=insight, domain=domain, source=source)
        return _safe_json(result)
    except Exception as e:
        return _safe_json({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════════════
# 知識工具（保留）
# ═══════════════════════════════════════════════════════════════════════════

def kafed_query(query: str, domain: str = "", k: int = 5,
                soft: bool = True) -> str:
    """查詢 KAFED 知識庫（RAG）。

    Args:
        query: 查詢文本
        domain: 可選域過濾
        k: 返回數量 (1-20)
        soft: 啟用軟分類
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
        return _safe_json(results)
    except Exception as e:
        return _safe_json({"error": str(e)})


def kafed_ingest(text: str, domain: str = "GENERAL",
                 source: str = "hermes_tool") -> str:
    """寫入知識到 KAFED 知識庫。

    Args:
        text: 文字內容
        domain: 目標域
        source: 來源標識
    """
    try:
        from kafed.knowledge.ingest import ingest

        result = ingest(text=text, domain=domain, source=source)
        return _safe_json(result)
    except Exception as e:
        return _safe_json({"error": str(e)})


def kafed_status() -> str:
    """KAFED 系統狀態：chunk 數、域分佈、引擎健康。"""
    try:
        from kafed.knowledge.rag.vector_store import VectorStore
        from kafed.config import get_config

        cfg = get_config()
        vs = VectorStore()
        collection = vs._collection
        count = collection.count()

        results = collection.get(include=["metadatas"])
        domains = {}
        for meta in results.get("metadatas", []):
            d = meta.get("domain", "UNKNOWN") if meta else "UNKNOWN"
            domains[d] = domains.get(d, 0) + 1

        return _safe_json({
            "chunks": count,
            "domains": len(domains),
            "domain_distribution": domains,
            "chroma_path": str(cfg.chroma_path),
            "engine": "ready",
        })
    except Exception as e:
        return _safe_json({
            "chunks": 0, "domains": 0, "engine": "error", "error": str(e),
        })


def kafed_classify(text: str) -> str:
    """分類文本到 KAFED 域。"""
    try:
        from kafed.knowledge.classify.classify import classify

        result = classify(text)
        return _safe_json(result)
    except Exception as e:
        return _safe_json({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════════════
# FlowVisualizer
# ═══════════════════════════════════════════════════════════════════════════

def kafed_flow(title: str = "KAFED Flow", mode: str = "compact",
               stations: str = "[]", end: str = "done") -> str:
    """可視化 KAFED 流程（stderr 輸出）。

    Args:
        title: 流程標題
        mode: 'compact' (箭頭鏈) 或 'detailed' (公交站牌)
        stations: JSON [[code, action, detail], ...]
        end: 終點標記
    """
    try:
        from kafed.flow import chain, divider
        sts = json.loads(stations) if isinstance(stations, str) else stations

        if mode == "detailed":
            divider(title)
            station_tuples = [
                (s[0], s[1], s[2] if len(s) > 2 else "") for s in sts
            ]
            chain(title, station_tuples, end=end)
        else:
            parts = []
            for s in sts:
                m, a = s[0], s[1]
                d = s[2] if len(s) > 2 else ""
                parts.append(f"{m}{a}({d})" if d else f"{m}{a}")
            import sys
            text = f"[ {title} ]  {' -> '.join(parts)} -> {end}"
            print(text, file=sys.stderr)
        return ""
    except Exception as e:
        return _safe_json({"error": str(e)})


def kafed_flow_chain(steps: str, title: str = "Flow", end: str = "done") -> str:
    """簡化流程鏈（JSON 步驟 → compact 模式）。

    Args:
        steps: JSON [{"m": module, "a": action, "d": description}, ...]
        title: 流程標題
        end: 終點標記
    """
    try:
        parsed = json.loads(steps) if isinstance(steps, str) else steps
        sts = [[s["m"], s["a"], s.get("d", "")] for s in parsed]
        return kafed_flow(title=title, mode="compact",
                          stations=json.dumps(sts), end=end)
    except Exception as e:
        return _safe_json({"error": str(e)})
