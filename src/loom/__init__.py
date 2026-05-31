"""LOOM — Knowledge Agent Framework for Embedded Data.  v4.0.1

核心入口：recommend() → solidify() 知識飛輪
三層會話管理：Turn → Session → Conversation（manager/）
展示層：Shuttle（manager/shuttle.py）"""


__version__ = "4.0.3"

# ── 公開 API ──
from loom.recommend import recommend, Recommendation
from loom.analyzer.solidifier import solidify, session_end_audit
from loom.finder.router import Router as _Router

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
