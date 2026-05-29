"""KAFED — Knowledge Agent Framework for Embedded Data.  v3.0

五層智能飛輪：Director → Finder → Knowledge → Analyzer → Scheduler

前段（決策支援）：director.recommend() — 卦→召→評 三步注入 Agent 上下文
後段（學習閉環）：analyzer.solidifier + knowledge 飛輪

Executors 已移除——委託給 Hermes delegate_task。
Backlog 已移除——使用 Hermes 原生 backlog。
ActionRegistry 已移除——過度設計，未被實際驅動。
"""

__version__ = "4.0.0"

# ── 公開 API ──
from kafed.director.recommend import recommend, Recommendation
from kafed.analyzer.solidifier import solidify, session_end_audit
from kafed.finder.router import Router as _Router

# 便利工廠
def find_partners(briefs: list[str]):
    """快捷調用 Finder 匹配模型。"""
    return _Router().find_partners(briefs)

__all__ = [
    "recommend",
    "Recommendation",
    "solidify",
    "session_end_audit",
    "find_partners",
]
