"""
KAFED Finder — 模型發現、三維聚合路由、能力匹配。

F 層是 KAFED 飛輪的「資源總管」：
  Director/Executor 說「需要什麼能力」→ Finder 說「誰能幹這個活」
"""

from kafed.finder.router import Router, find_partners, FindPartnersRequest, FindPartnersResult
from kafed.finder.registry import Registry
from kafed.finder.explorer import Explorer, scan
from kafed.finder.matcher import WorkerCandidate

__all__ = [
    "Router", "find_partners", "FindPartnersRequest", "FindPartnersResult",
    "Registry",
    "Explorer", "scan",
    "WorkerCandidate",
]
