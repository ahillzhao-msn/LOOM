"""LOOM Hermes Tools — Agent 可調用的工具函數。

每個函數都可在 Hermes 工具層註冊，也可直接 import 使用。
函數不依賴 Hermes——純 Python import，零進程開銷。

注意：FlowVisualizer 不再是 Hermes 工具。
流程可視化已整合進 LOOM 內部 logging（loom.flow），
由 recommend() / solidify() 自動調用。
"""

from __future__ import annotations

import json
from typing import Optional

# ── Hermes Registry ───────────────────────────────────────────
# 注意：此文件同時作為 LOOM 包模塊（pip install）和 Hermes 工具（symlink）部署。
#
# 當在 Hermes 上下文中：from tools.registry 可正常解析 → 真實註冊生效。
# 當從 LOOM 包導入時：tools.registry 不可用 → _DummyRegistry 使所有
# registry.register() 調用安全降級為 no-op，不中斷模塊導入。
#
# 所有函數（loom_recommend, loom_solidify 等）在兩種上下文中皆可直接導入使用。
try:
    from tools.registry import registry, tool_error
except ModuleNotFoundError:
    class _DummyRegistry:
        """Hermes 不可用時的安全降級——registry.register() 為 no-op。"""
        def register(self, **kw):
            pass
    registry = _DummyRegistry()


def _safe_json(data, error_prefix="LOOM error") -> str:
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

def loom_loom_close() -> str:
    """關閉當前 Loom conversation（用戶顯式開新 conversation 時調用）。

    不阻塞——如無活躍 conversation，直接返回 success。
    recommend() 下一次被調用時自動創建新 conversation。
    """
    try:
        from loom.manager.client import manager as loom
        reward = loom.close_conversation(reason="user_explicit")
        return _safe_json({
            "status": "closed" if reward else "no_conversation",
            "reward": reward or {},
        })
    except Exception as e:
        return _safe_json({"error": str(e)})


def loom_recommend(user_input: str) -> str:
    """卦 → 召 → 評：為 Agent 生成決策素材。

    在每次 Agent turn 開始前強制調用。
    返回結構化 JSON，含 inject_text 欄位可直接注入 prompt。

    Args:
        user_input: 使用者原始輸入
    """
    try:
        from loom.recommend import recommend

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


def loom_find_partners(briefs: str) -> str:
    """為多個子任務匹配最佳模型。

    在 Agent 決定拆子任務後、調用 delegate_task 之前使用。
    每個子任務返回模型候選列表，按匹配度排序。

    Args:
        briefs: JSON 字符串陣列，如 '["工單分析", "代碼審計"]'
    """
    try:
        from loom.finder.router import Router

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


def loom_solidify(insight: str, domain: str = "GENERAL",
                    source: str = "agent_turn") -> str:
    """將本輪洞察寫入 LOOM 知識庫。

    在 Agent 生成回應後調用。非同步——不阻塞回應。

    Args:
        insight: 洞察內容（教訓、發現、模式）
        domain: 域標籤
        source: 來源標識
    """
    try:
        from loom.analyzer.solidifier import solidify

        result = solidify(insight=insight, domain=domain, source=source)
        return _safe_json(result)
    except Exception as e:
        return _safe_json({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════════════
# 知識工具
# ═══════════════════════════════════════════════════════════════════════════

def loom_query(query: str, domain: str = "", k: int = 5,
                soft: bool = True) -> str:
    """查詢 LOOM 知識庫（RAG）。

    Args:
        query: 查詢文本
        domain: 可選域過濾
        k: 返回數量 (1-20)
        soft: 啟用軟分類
    """
    try:
        from loom.knowledge.rag.vector_store import VectorStore
        from loom.knowledge.rag.rag_engine import RAGEngine

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


def loom_ingest(text: str, domain: str = "GENERAL",
                 source: str = "hermes_tool") -> str:
    """寫入知識到 LOOM 知識庫。

    Args:
        text: 文字內容
        domain: 目標域
        source: 來源標識
    """
    try:
        from loom.knowledge.ingest import ingest

        result = ingest(text=text, domain=domain, source=source)
        return _safe_json(result)
    except Exception as e:
        return _safe_json({"error": str(e)})


def loom_status() -> str:
    """LOOM 系統狀態：chunk 數、域分佈、引擎健康。"""
    try:
        from loom.knowledge.rag.vector_store import VectorStore
        from loom.config import get_config

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


def loom_classify(text: str) -> str:
    """分類文本到 LOOM 域。"""
    try:
        from loom.knowledge.classify.classify import classify

        result = classify(text)
        return _safe_json(result)
    except Exception as e:
        return _safe_json({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════════════
# Hermes Registry Registration
# ═══════════════════════════════════════════════════════════════════════════

# ── Schema 定義 ──

LOOM_CLOSE_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
}

LOOM_RECOMMEND_SCHEMA = {
    "type": "object",
    "properties": {
        "user_input": {
            "type": "string",
            "description": "使用者原始輸入，LOOM 將執行 5W1H 分解 → 卦象預判 → 知識召回 → EVAL 評分",
        },
    },
    "required": ["user_input"],
}

LOOM_FIND_PARTNERS_SCHEMA = {
    "type": "object",
    "properties": {
        "briefs": {
            "type": "string",
            "description": "JSON 字符串陣列，如 '[\"工單分析\", \"代碼審計\"]'。為每個子任務匹配最佳模型",
        },
    },
    "required": ["briefs"],
}

LOOM_SOLIDIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "insight": {
            "type": "string",
            "description": "洞察內容（教訓、發現、模式）",
        },
        "domain": {
            "type": "string",
            "description": "域標籤（預設 GENERAL）",
            "default": "GENERAL",
        },
        "source": {
            "type": "string",
            "description": "來源標識（預設 agent_turn）",
            "default": "agent_turn",
        },
    },
    "required": ["insight"],
}

LOOM_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "查詢文本",
        },
        "domain": {
            "type": "string",
            "description": "可選域過濾（空字符串=不限制）",
            "default": "",
        },
        "k": {
            "type": "integer",
            "description": "返回結果數量 (1-20)",
            "default": 5,
        },
        "soft": {
            "type": "boolean",
            "description": "啟用軟分類（多域候選）",
            "default": True,
        },
    },
    "required": ["query"],
}

LOOM_INGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "文字內容",
        },
        "domain": {
            "type": "string",
            "description": "目標域標籤",
            "default": "GENERAL",
        },
        "source": {
            "type": "string",
            "description": "來源標識",
            "default": "hermes_tool",
        },
    },
    "required": ["text"],
}

LOOM_STATUS_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
}

LOOM_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "分類文本",
        },
    },
    "required": ["text"],
}


def _check_loom_requirements() -> Optional[str]:
    """檢查 LOOM 環境是否可用。"""
    try:
        import loom  # noqa: F401
        return None  # 可用
    except ImportError:
        return "LOOM package not installed (pip install -e ~/LOOM)"


# ── 註冊工具（Hermes AST auto-discovery 檢測目標） ────────────
# 所有 registry.register() 調用位於模塊頂層，供 Hermes 工具發現機制
# （_module_registers_tools()）透過 AST 掃描檢測。
# 當 Hermes 不可用時，_DummyRegistry 使這些調用安全降級為 no-op。

registry.register(
    name="loom_recommend",
    toolset="loom",
    schema=LOOM_RECOMMEND_SCHEMA,
    handler=lambda args, **kw: loom_recommend(args.get("user_input", "")),
    check_fn=_check_loom_requirements,
    emoji="🔮",
    description="LOOM 決策素材生成：5W1H 分解 → YiCeNet 卦象預判 → 知識召回 → EVAL 評分",
)

registry.register(
    name="loom_solidify",
    toolset="loom",
    schema=LOOM_SOLIDIFY_SCHEMA,
    handler=lambda args, **kw: loom_solidify(
        insight=args.get("insight", ""),
        domain=args.get("domain", "GENERAL"),
        source=args.get("source", "agent_turn"),
    ),
    check_fn=_check_loom_requirements,
    emoji="💾",
    description="將本輪洞察寫入 LOOM 知識庫（回應後調用）",
)

registry.register(
    name="loom_find_partners",
    toolset="loom",
    schema=LOOM_FIND_PARTNERS_SCHEMA,
    handler=lambda args, **kw: loom_find_partners(args.get("briefs", "[]")),
    check_fn=_check_loom_requirements,
    emoji="🤝",
    description="為子任務列表匹配最佳模型（三向量聚合）",
)

registry.register(
    name="loom_query",
    toolset="loom",
    schema=LOOM_QUERY_SCHEMA,
    handler=lambda args, **kw: loom_query(
        query=args.get("query", ""),
        domain=args.get("domain", ""),
        k=args.get("k", 5),
        soft=args.get("soft", True),
    ),
    check_fn=_check_loom_requirements,
    emoji="📖",
    description="查詢 LOOM 知識庫（RAG 檢索）",
)

registry.register(
    name="loom_ingest",
    toolset="loom",
    schema=LOOM_INGEST_SCHEMA,
    handler=lambda args, **kw: loom_ingest(
        text=args.get("text", ""),
        domain=args.get("domain", "GENERAL"),
        source=args.get("source", "hermes_tool"),
    ),
    check_fn=_check_loom_requirements,
    emoji="📥",
    description="寫入知識到 LOOM 知識庫",
)

registry.register(
    name="loom_status",
    toolset="loom",
    schema=LOOM_STATUS_SCHEMA,
    handler=lambda args, **kw: loom_status(),
    check_fn=_check_loom_requirements,
    emoji="📊",
    description="LOOM 系統狀態：chunk 數、域分佈、引擎健康",
)

registry.register(
    name="loom_classify",
    toolset="loom",
    schema=LOOM_CLASSIFY_SCHEMA,
    handler=lambda args, **kw: loom_classify(args.get("text", "")),
    check_fn=_check_loom_requirements,
    emoji="🏷️",
    description="分類文本到 LOOM 域（純嵌入分類）",
)

registry.register(
    name="loom_loom_close",
    toolset="loom",
    schema=LOOM_CLOSE_SCHEMA,
    handler=lambda args, **kw: loom_loom_close(),
    check_fn=_check_loom_requirements,
    emoji="🚪",
    description="關閉當前 LOOM conversation（開新 conversation 前調用）",
)
