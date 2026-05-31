"""LOOM Director — 決策建議（唯一入口）。

四步強制：問(5W1H) → 卦(YiCeNet) → 召(知識召回) → 評(EVAL)。
不拆子任務、不選模型——只提供 Agent 做決策所需的上下文素材。

Agent 每輪開始前調用 recommend()，將結果注入上下文後自由行動。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from loom.manager.shuttle import Shuttle, step
from loom.eval import EvalScorer, EvalScore
from loom.hexagram import (
    hexagram_display, hexagram_chain, hexagram_chain_compact,
    hexagram_symbol, hexagram_six_lines,
)



# ── 全域輔助 ────────────────────────────────────

# 來源類型映射：知識項 source → M/W/S/R/K
_SOURCE_MAP: dict[str, str] = {
    "memory": "memory", "honcho": "memory",
    "wiki": "wiki",
    "skill": "skills",
    "session": "recall",
    "rag": "rag", "loom": "rag",
}


def _count_sources(knowledge: list[dict]) -> dict:
    """統計知識項來源分佈 → {memory, wiki, skills, recall, rag} 計數。"""
    counts: dict[str, int] = {"memory": 0, "wiki": 0, "skills": 0, "recall": 0, "rag": 0}
    for item in knowledge:
        src = (item.get("source", "") or "").lower()
        key = _SOURCE_MAP.get(src)
        if key:
            counts[key] = counts.get(key, 0) + 1
        else:
            counts["rag"] = counts.get("rag", 0) + 1  # 未知來源歸入 rag
    return {k: v for k, v in counts.items() if v > 0}


@dataclass
class FiveWOneH:
    """5W1H 結構化問題分解。

    將使用者的自然語言輸入分解為六個維度，
    每個維度值是從輸入中提取的關鍵詞/短語（非 LLM 生成）。
    """

    what: str = ""    # 核心主題/動作
    why: str = ""     # 目的/動機
    who: str = ""     # 涉及角色/系統
    where: str = ""   # 領域/模組/環境
    when: str = ""    # 時間約束/緊急性
    how: str = ""     # 方法/約束條件

    def is_empty(self) -> bool:
        return not any([self.what, self.why, self.who, self.where, self.when, self.how])

    def describe(self) -> str:
        lines = []
        if self.what:
            lines.append(f"  What:  {self.what}")
        if self.why:
            lines.append(f"  Why:   {self.why}")
        if self.who:
            lines.append(f"  Who:   {self.who}")
        if self.where:
            lines.append(f"  Where: {self.where}")
        if self.when:
            lines.append(f"  When:  {self.when}")
        if self.how:
            lines.append(f"  How:   {self.how}")
        return "\n".join(lines) if lines else "  (無法分解)"


@dataclass
class Recommendation:
    """LOOM 對 Agent 的決策建議包裹。

    Agent 收到這個後自行決定：
    - 是否拆子任務
    - 是否調用 loom_find_partners 匹配模型
    - 用什麼工具
    """

    user_input: str
    five_w_one_h: FiveWOneH = field(default_factory=FiveWOneH)
    hexagram: dict = field(default_factory=dict)
    knowledge_items: list[dict] = field(default_factory=list)
    eval_score: Optional[EvalScore] = None

    def inject(self) -> str:
        """生成注入 Agent 上下文的結構化文字區塊。"""
        parts = ["══════ LOOM 決策素材 ══════", ""]

        # ── 5W1H ──
        if not self.five_w_one_h.is_empty():
            parts.append("▎5W1H 問題分解:")
            parts.append(self.five_w_one_h.describe())
            parts.append("")

        # ── 卦象 ──
        h = self.hexagram
        if h and h.get("id", 0) > 0:
            hid = h["id"]
            parts.append(f"▎卦: {hexagram_display(hid)}")
            # 卦鏈（若有）
            chain_ids = h.get("chain", [])
            if len(chain_ids) > 1:
                parts.append(f"  卦鏈: {hexagram_chain_compact(chain_ids)}")
            # 候選（若有）
            candidates = h.get("candidates", [])
            if candidates:
                cand_strs = []
                for c in candidates[:4]:
                    cid = c.get("id", c) if isinstance(c, dict) else c
                    cand_strs.append(hexagram_symbol(cid))
                if cand_strs:
                    parts.append(f"  候選: {' '.join(cand_strs)}")
            # 釋義
            if h.get("interpretation"):
                parts.append(f"  啟示: {h['interpretation']}")
            parts.append("")

        # ── 知識 ──
        if self.knowledge_items:
            parts.append(f"▎知識召回: {len(self.knowledge_items)} 條")
            for item in self.knowledge_items[:7]:
                src = item.get("source", "?")
                score = item.get("score", 0)
                content = item.get("content", "")[:200]
                parts.append(f"  [{src}] score={score:.3f}  {content}")
            parts.append("")

        # ── EVAL ──
        if self.eval_score:
            parts.append(f"▎難度: Tier {self.eval_score.tier}  Score={self.eval_score.score}")
            parts.append(f"  範圍={self.eval_score.f1_scope.name}  "
                         f"新鮮={self.eval_score.f3_freshness.name}  "
                         f"風險={self.eval_score.f4_risk.name}")
            parts.append("")

        parts.append("══════════════════════════════")
        return "\n".join(parts)


def recommend(user_input: str) -> Recommendation:
    """问(5W1H) → 卦 → 召 → 评。四步强制，为 Agent 提供决策素材。"""
    Shuttle.reset_steps()

    # Step 1-4: 步骤函数由 @step 装饰器自动注册到 Shuttle._steps
    w5 = _step_5w1h(user_input)
    hexagram = _step_hexagram(user_input)
    hex_id = hexagram.get("id", 0) if isinstance(hexagram, dict) else 0
    knowledge = _step_recall(user_input, hex_id)
    evaluation = _step_eval(user_input, knowledge, hexagram)

    # Step 5: Loom conversation 生命周期（透明）
    _auto_loom_lifecycle(
        query=user_input,
        hexagram=hexagram,
        knowledge_items=knowledge,
        eval_score=evaluation,
        flow_entries=Shuttle.steps_snapshot(),
        response_time=0.0,
    )

    # Step 6: Shuttle 流程链输出
    Shuttle.emit_flow(title="LOOM", end="done")

    return Recommendation(
        user_input=user_input,
        five_w_one_h=w5,
        hexagram=hexagram,
        knowledge_items=knowledge,
        eval_score=evaluation,
    )


# ══════════════════════════════════════════════════
# Loom Conversation 生命週期（透明模式）
# ══════════════════════════════════════════════════

def _compute_embedding(text: str) -> list[float]:
    """計算查詢向量的嵌入。與 ContextProvider 使用相同模型。"""
    try:
        from loom.knowledge.rag.embedding import get_model
        model = get_model()
        vec = model.encode([text[:512]], show_progress_bar=False)[0]
        return vec.tolist()
    except Exception:
        return []


def _auto_loom_lifecycle(
    query: str,
    hexagram: dict,
    knowledge_items: list[dict],
    eval_score: EvalScore | None,
    flow_entries: list,
    token_usage: dict | None = None,
    response_time: float = 0.0,
) -> None:
    """透明 Loom conversation 管理——在 recommend() 末尾自動調用。

    三層邊界判定（優先級由高到低）：
    1. 用戶顯式（/new 等）— 由 Hermes 調用 close_conversation，此處不處理
    2. 自然遺忘 — forgetting_score() < 閾值
    3. Embedding 漂移 — 語義不連續 < 閾值

    無活躍 conversation 時自動創建。
    """
    from loom.manager.client import manager as loom
    from loom.manager.factory import ConversationFactory

    embedding = _compute_embedding(query)

    # ── 檢查現有 conversation ──
    conv = loom.conversation

    if conv is None:
        # 無 conversation → 直接創建
        loom.get_or_create_conversation()
        if embedding:
            loom._conversation.topic_centroid = embedding
        _do_start_turn(loom, query, hexagram, knowledge_items,
                       eval_score, flow_entries, embedding,
                       token_usage, response_time)
        return

    # ── 有 conversation → 三層邊界判定 ──
    should_close = ConversationFactory.should_close(
        conv,
        new_query_embedding=embedding if embedding else None,
    )

    if should_close:
        reason = "forgotten"
        # 具體原因用於日誌
        loom.close_conversation(reason=reason)
        loom.get_or_create_conversation()
        if embedding:
            loom._conversation.topic_centroid = embedding
    elif embedding and conv.topic_centroid:
        # 同一 conversation → 更新 centroid（加權滾動平均）
        conv.update_centroid(embedding, weight=0.3)

    _do_start_turn(loom, query, hexagram, knowledge_items,
                   eval_score, flow_entries, embedding,
                   token_usage, response_time)


def _do_start_turn(
    loom, query: str,
    hexagram: dict,
    knowledge_items: list[dict],
    eval_score: EvalScore | None,
    flow_entries: list,
    embedding: list[float],
    token_usage: dict | None,
    response_time: float,
) -> None:
    """統一調用 start_turn_from_recommend（tuple/object 兼容）。"""
    counts = _count_sources(knowledge_items)
    loom.start_turn_from_recommend(
        query=query,
        hexagram={
            "id": hexagram.get("id", 0),
            "name": hexagram.get("name", ""),
            "q_value": hexagram.get("q_value", 0.5),
            "candidates": hexagram.get("candidates", []),
        } if hexagram else {},
        knowledge=counts,
        eval_score={
            "tier": eval_score.tier if eval_score else "",
            "score": eval_score.score if eval_score else 0,
            "f1_scope": eval_score.f1_scope.name if eval_score else "",
        } if eval_score else {},
        flow_entries=flow_entries,
        token_usage=token_usage or {"prompt": 0, "completion": 0, "total": 0},
        response_time=response_time,
    )


# ══════════════════════════════════════════════════
# Step 1: 問 — 5W1H 結構化分解
# ══════════════════════════════════════════════════

# 領域關鍵詞 → 提示 where 維度
_DOMAIN_HINTS: dict[str, str] = {
    "SAP": "SAP", "PM": "SAP PM", "VC": "SAP VC", "ABAP": "ABAP",
    "IW": "SAP PM 工單", "CSP": "CSP", "IID": "IID",
    "LOOM": "LOOM", "YiCeNet": "YiCeNet", "Hermes": "Hermes Agent",
    "Python": "Python", "Git": "Git", "GitHub": "GitHub",
    "WSL": "WSL", "Linux": "Linux", "Ubuntu": "Ubuntu",
    "CUDA": "CUDA", "GPU": "GPU", "llama": "llama.cpp",
    "Chroma": "ChromaDB", "RAG": "RAG", "embedding": "embedding",
    "模型": "模型", "訓練": "訓練", "SFT": "SFT",
}
# 動作關鍵詞 → 提示 what 維度
_ACTION_HINTS: dict[str, str] = {
    "分析": "分析", "審計": "審計", "修復": "修復", "重構": "重構",
    "創建": "創建", "新建": "新建", "刪除": "刪除", "移除": "移除",
    "部署": "部署", "安裝": "安裝", "配置": "配置",
    "查詢": "查詢", "搜索": "搜索", "找到": "查找",
    "解釋": "解釋", "說明": "說明", "什麼是": "概念解釋",
    "為什麼": "原因分析", "如何": "操作指南",
    "review": "審查", "audit": "審計", "fix": "修復", "build": "構建",
    "debug": "除錯", "test": "測試", "deploy": "部署",
}
# 時間關鍵詞 → 提示 when 維度
_TIME_HINTS: dict[str, str] = {
    "緊急": "緊急", "馬上": "立即", "今天": "今日",
    "urgent": "緊急", "ASAP": "立即",
}
# 方法約束 → 提示 how 維度
_METHOD_HINTS: dict[str, str] = {
    "安全": "安全優先", "不影響": "零影響", "謹慎": "謹慎",
    "快速": "快速", "最小": "最小改動", "一步一驗": "一步一驗",
    "測試": "含測試", "文檔": "含文檔",
}


@step(module="D", action="问")
def _step_5w1h(user_input: str) -> tuple:
    """从用户输入中提取 5W1H 结构。"""
    text = user_input.strip()
    text_lower = text.lower()

    # What: 第一個明顯的動作詞或核心主題
    what_parts = []
    for kw, label in _ACTION_HINTS.items():
        if kw in text:
            what_parts.append(label)
    what = " + ".join(what_parts[:3]) if what_parts else ""

    # Where: 領域/模組
    where_parts = []
    for kw, label in _DOMAIN_HINTS.items():
        if kw.lower() in text_lower:
            where_parts.append(label)
    # 去重（SAP PM 優於 SAP）
    where = _deduplicate_hints(where_parts)

    # Why: 從「為什麼/目的/為了」提取
    why = ""
    why_patterns = [
        r"為什麼(.+?)(?:[，。；]|$)", r"原因.*?(?:是|在於)(.+?)(?:[，。；]|$)",
        r"(?:為了|目的是|目標是)(.+?)(?:[，。；]|$)",
    ]
    for pat in why_patterns:
        m = re.search(pat, text)
        if m:
            why = m.group(1).strip()[:100]
            break

    # Who: 角色/系統
    who = ""
    who_patterns = [
        r"(?:我|用戶|客戶|Admin|Developer)(?:想|要|需要)",
        r"Agent|Director|Finder|Executor|Analyzer",
    ]
    for pat in who_patterns:
        if re.search(pat, text, re.IGNORECASE):
            who = "Agent/用戶交互"
            break

    # When: 時間約束
    when = ""
    for kw, label in _TIME_HINTS.items():
        if kw.lower() in text_lower:
            when = label
            break

    # How: 方法約束
    how_parts = []
    for kw, label in _METHOD_HINTS.items():
        if kw in text:
            how_parts.append(label)
    how = ", ".join(how_parts[:3]) if how_parts else ""

    _dim = sum(1 for v in [what, why, who, where, when, how] if v)
    _detail = what[:10] if what else f"{_dim}维度"
    return (FiveWOneH(what=what, why=why, who=who, where=where, when=when, how=how), _detail)


def _deduplicate_hints(hints: list[str]) -> str:
    """去重：SAP PM 優於 SAP，保留最具體的。"""
    if not hints:
        return ""
    # 排序：長的優先（更具體）
    hints_sorted = sorted(set(hints), key=len, reverse=True)
    result = []
    for h in hints_sorted:
        # 若已選的更長版本包含了短版本，跳過
        if not any(h in r for r in result):
            result.append(h)
    return ", ".join(result)


# ══════════════════════════════════════════════════
# Step 2: 卦 — YiCeNet 预判
# ══════════════════════════════════════════════════

@step(module="D", action="卦")
def _step_hexagram(user_input: str, chain_history: list[int] | None = None) -> tuple:
    """调用 YiCeNet 获取卦象预判。"""
    try:
        from yicenet.hermes_tool import yicenet_predict
        from yicenet.display import format_prediction
        result_raw = yicenet_predict(task_brief=user_input)
        import json
        result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw

        hid = result.get("hexagram_id", 0)
        candidates = result.get("candidates", [])

        # 卦链：历史 + 当前
        chain = (chain_history or []) + [hid] if hid > 0 else (chain_history or [])

        # 提取候选卦 ID 列表
        cand_ids = []
        if candidates:
            for c in candidates:
                cid = c.get("hexagram_id", c.get("id", 0)) if isinstance(c, dict) else c
                if cid and cid != hid:
                    cand_ids.append(cid)

        # YiCeNet 自持的格式化结果
        display_compact = format_prediction(result, mode="compact")

        return ({
            "id": hid,
            "symbol": hexagram_symbol(hid) if hid > 0 else "?",
            "name": hexagram_display(hid) if hid > 0 else "未占",
            "six_lines": hexagram_six_lines(hid) if hid > 0 else "",
            "q_value": result.get("q_value", 0.5),
            "interpretation": result.get("interpretation", ""),
            "candidates": cand_ids,
            "chain": chain,
            "display_compact": display_compact,
        }, display_compact or hexagram_display(hid) if hid > 0 else "✗")
    except Exception:
        return ({"id": 0, "name": "✗", "q_value": 0.5, "chain": chain_history or [],
                 "display_compact": "✗"}, "✗")


# ══════════════════════════════════════════════════
# Step 3: 召 — 全源知识召回
# ══════════════════════════════════════════════════

@step(module="D", action="召")
def _step_recall(user_input: str, hexagram_id: int = 0) -> tuple:
    """全源知识召回：RAG + Wiki + Memory/Session/Skills 扫描。"""
    try:
        from loom.knowledge.context.context_provider import ContextProvider
        cp = ContextProvider()
        bundle = cp.recall(query=user_input, hexagram_id=hexagram_id)
        items = []
        for item in bundle.top(10):
            items.append({
                "source": item.source,
                "content": item.content,
                "score": item.score,
                "domain": item.domain,
                "title": item.title,
            })
        # Build detail from source counts
        counts = _count_sources(items)
        src_parts = []
        for key, label in [("memory", "M"), ("wiki", "W"),
                           ("skills", "S"), ("recall", "R"), ("rag", "K")]:
            cnt = counts.get(key, 0)
            if cnt:
                src_parts.append(f"{label}[{cnt}]")
        detail = " ".join(src_parts) if src_parts else f"{len(items)}条"
        return (items, detail)
    except Exception:
        return ([], "✗")


# ══════════════════════════════════════════════════
# Step 4: 评 — EVAL 五维评估
# ══════════════════════════════════════════════════

@step(module="D", action="评")
def _step_eval(user_input: str, knowledge: list[dict],
               hexagram: dict) -> tuple:
    """EVAL 五维评估（带知识上下文 + 卦象调制）。"""
    scorer = EvalScorer()
    score = scorer.from_description(user_input)

    # 卦象调制：Q 值极端时调整风险评估
    q = hexagram.get("q_value", 0.5)
    if q > 0.8:
        mods = {"F4": 1}
    elif q < 0.3:
        mods = {"F4": -1}
    else:
        mods = {}

    if mods:
        score = score.apply_hexagram_mod(mods)

    detail = f"T{score.tier} S{score.score:.2f}"
    return (score, detail)
