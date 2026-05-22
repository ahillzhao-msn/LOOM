"""
KAFED Finder — 模型匹配與路由核心。

三維聚合路由：任務描述 × 模型能力 × 實時狀態
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class WorkerCandidate:
    """模型候選。"""
    name: str
    provider: str                # local / deepseek / openrouter / ...
    model_id: str                # 實際模型 ID
    
    # 匹配信息
    match_score: float           # 0.0-1.0 embedding 匹配度
    domain: str = ""
    
    # 狀態
    is_online: bool = True
    estimated_tps: int = 0       # tokens per second
    
    # 歷史
    total_calls: int = 0
    success_rate: float = 0.0
    
    # 成本
    is_free: bool = True
    cost_per_token: float = 0.0  # USD
    
    def describe(self) -> str:
        status = "🟢" if self.is_online else "🔴"
        cost = "free" if self.is_free else f"${self.cost_per_token:.6f}/tok"
        return (
            f"{status} {self.name:20s} | {self.provider:12s} | "
            f"match={self.match_score:.2f} | {cost} | "
            f"calls={self.total_calls} sr={self.success_rate:.0%}"
        )


@dataclass
class FindPartnersRequest:
    """find_partners 請求參數。"""
    task_brief: str               # 自然語言任務描述
    budget: str = "any"           # free / low / any
    prefer_local: bool = False
    top_k: int = 5
    domain: Optional[str] = None
    
    # 過濾條件
    min_match_score: float = 0.0
    require_online: bool = True


@dataclass
class FindPartnersResult:
    """find_partners 結果。"""
    request: FindPartnersRequest
    candidates: list[WorkerCandidate] = field(default_factory=list)
    total_candidates: int = 0
    match_method: str = "embedding"  # embedding / config / fallback
    
    def best(self) -> Optional[WorkerCandidate]:
        """返回最佳候選。"""
        return self.candidates[0] if self.candidates else None
    
    def filter_by_budget(self, budget: str) -> list[WorkerCandidate]:
        if budget == "free":
            return [c for c in self.candidates if c.is_free]
        return self.candidates
