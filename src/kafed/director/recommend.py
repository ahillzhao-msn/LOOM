"""KAFED Director — 決策建議（唯一入口）。

四步強制：問(5W1H) → 卦(YiCeNet) → 召(知識召回) → 評(EVAL)。
不拆子任務、不選模型——只提供 Agent 做決策所需的上下文素材。

Agent 每輪開始前調用 recommend()，將結果注入上下文後自由行動。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from kafed.director.eval import EvalScorer, EvalScore
from kafed.director.hexagram import (
    hexagram_display, hexagram_chain, hexagram_chain_compact,
    hexagram_symbol, hexagram_six_lines,
)


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
    """KAFED 對 Agent 的決策建議包裹。

    Agent 收到這個後自行決定：
    - 是否拆子任務
    - 是否調用 kafed_find_partners 匹配模型
    - 用什麼工具
    """

    user_input: str
    five_w_one_h: FiveWOneH = field(default_factory=FiveWOneH)
    hexagram: dict = field(default_factory=dict)
    knowledge_items: list[dict] = field(default_factory=list)
    eval_score: Optional[EvalScore] = None

    def inject(self) -> str:
        """生成注入 Agent 上下文的結構化文字區塊。"""
        parts = ["══════ KAFED 決策素材 ══════", ""]

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
    """問(5W1H) → 卦 → 召 → 評。四步強制，為 Agent 提供決策素材。

    Args:
        user_input: 使用者原始輸入

    Returns:
        Recommendation: 5W1H + 卦象 + 知識片段 + EVAL 評分
    """
    # ── Step 1: 問 (5W1H 分解) ──
    w5 = _step_5w1h(user_input)

    # ── Step 2: 卦 ──
    hexagram = _step_hexagram(user_input)

    # ── Step 3: 召 ──
    knowledge = _step_recall(user_input, hexagram.get("id", 0))

    # ── Step 4: 評 ──
    evaluation = _step_eval(user_input, knowledge, hexagram)

    return Recommendation(
        user_input=user_input,
        five_w_one_h=w5,
        hexagram=hexagram,
        knowledge_items=knowledge,
        eval_score=evaluation,
    )


# ══════════════════════════════════════════════════
# Step 1: 問 — 5W1H 結構化分解
# ══════════════════════════════════════════════════

# 領域關鍵詞 → 提示 where 維度
_DOMAIN_HINTS: dict[str, str] = {
    "SAP": "SAP", "PM": "SAP PM", "VC": "SAP VC", "ABAP": "ABAP",
    "IW": "SAP PM 工單", "CSP": "CSP", "IID": "IID",
    "KAFED": "KAFED", "YiCeNet": "YiCeNet", "Hermes": "Hermes Agent",
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


def _step_5w1h(user_input: str) -> FiveWOneH:
    """從使用者輸入中提取 5W1H 結構。

    使用啟發式規則（非 LLM）做快速分解。
    模糊無法確定的維度留空——不猜。
    """
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

    return FiveWOneH(what=what, why=why, who=who, where=where, when=when, how=how)


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
# Step 2: 卦 — YiCeNet 預判
# ══════════════════════════════════════════════════

def _step_hexagram(user_input: str, chain_history: list[int] | None = None) -> dict:
    """調用 YiCeNet 獲取卦象預判。

    返回含 Unicode 符號、六爻、候選卦鏈等顯示資訊。
    若提供了 chain_history（前幾輪的卦 ID），自動組合卦鏈。
    """
    try:
        from yicenet.hermes_tool import yicenet_predict
        result_raw = yicenet_predict(task_brief=user_input)
        import json
        result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw

        hid = result.get("hexagram_id", 0)
        candidates = result.get("candidates", [])

        # 卦鏈：歷史 + 當前
        chain = (chain_history or []) + [hid] if hid > 0 else (chain_history or [])

        # 提取候選卦 ID 列表
        cand_ids = []
        if candidates:
            for c in candidates:
                cid = c.get("hexagram_id", c.get("id", 0)) if isinstance(c, dict) else c
                if cid and cid != hid:
                    cand_ids.append(cid)

        return {
            "id": hid,
            "symbol": hexagram_symbol(hid) if hid > 0 else "?",
            "name": hexagram_display(hid) if hid > 0 else "未占",
            "six_lines": hexagram_six_lines(hid) if hid > 0 else "",
            "q_value": result.get("q_value", 0.5),
            "interpretation": result.get("interpretation", ""),
            "candidates": cand_ids,
            "chain": chain,
        }
    except Exception:
        return {"id": 0, "name": "未占", "q_value": 0.5, "chain": chain_history or []}


# ══════════════════════════════════════════════════
# Step 3: 召 — 全源知識召回
# ══════════════════════════════════════════════════

def _step_recall(user_input: str, hexagram_id: int = 0) -> list[dict]:
    """全源知識召回：RAG + Wiki + Memory/Session/Skills 掃描。"""
    try:
        from kafed.knowledge.context.context_provider import ContextProvider
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
        return items
    except Exception:
        return []


# ══════════════════════════════════════════════════
# Step 4: 評 — EVAL 五維評估
# ══════════════════════════════════════════════════

def _step_eval(user_input: str, knowledge: list[dict],
               hexagram: dict) -> EvalScore:
    """EVAL 五維評估（帶知識上下文 + 卦象調製）。"""
    scorer = EvalScorer()
    score = scorer.from_description(user_input)

    # 卦象調製：Q 值極端時調整風險評估
    q = hexagram.get("q_value", 0.5)
    if q > 0.8:
        mods = {"F4": 1}  # 高 Q → 卦說安全，降風險
    elif q < 0.3:
        mods = {"F4": -1}  # 低 Q → 卦說謹慎，升風險
    else:
        mods = {}

    if mods:
        score = score.apply_hexagram_mod(mods)

    return score
