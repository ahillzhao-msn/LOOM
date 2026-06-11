"""LOOM — Knowledge Agent Framework for Embedded Data.  v4.2.0

核心入口：recommend() → solidify() 知識飛輪
三層會話管理：Turn → Session → Conversation（manager/）
展示層：Shuttle（manager/shuttle.py）

Install from PyPI-compatible release:
  uv pip install loom @ https://github.com/ahillzhao-msn/LOOM/releases/download/v4.2.0/loom-4.2.0-py3-none-any.whl
"""


__version__ = "4.2.0"

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
