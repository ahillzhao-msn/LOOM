"""KAFED Finder — 模型匹配與路由核心數據結構。

三維聚合路由：任務描述 × 模型能力 × 實時狀態
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


@dataclass
class WorkerCandidate:
    """模型候選。

    新增字段:
        capability_tags — ["reasoning", "coding", "vision", "fast", "cheap", "local"]
        status_vector  — [online(0/1), tps_norm(0-1), load_norm(0-1)] 實時
        context_boost  — ContextSpace 調製增量（0-0.3）
        last_selected  — ISO timestamp
        embedding      — 自帶嵌入向量（可選，避免重複查詢）
    """
    name: str
    provider: str                # local / deepseek / openrouter / ...
    model_id: str                # 實際模型 ID

    # 匹配信息
    match_score: float = 0.5     # 0.0-1.0 最終聚合匹配度
    domain: str = ""

    # 能力標籤
    capability_tags: list[str] = field(default_factory=lambda: [])

    # 實時狀態
    is_online: bool = True
    estimated_tps: int = 0       # tokens per second
    status_vector: list[float] = field(default_factory=lambda: [1.0, 0.0, 0.0])

    # 語境調製
    context_boost: float = 0.0

    # 歷史
    total_calls: int = 0
    success_rate: float = 0.0
    last_selected: str = ""

    # 成本
    is_free: bool = True
    cost_per_token: float = 0.0  # USD

    # 嵌入（可選，避免重複查詢）
    embedding: Optional[np.ndarray] = None

    def describe(self) -> str:
        """人類可讀的描述（無 emoji、無 ANSI）。"""
        status = "online" if self.is_online else "offline"
        cost = "free" if self.is_free else f"${self.cost_per_token:.6f}/tok"
        caps = ",".join(self.capability_tags[:4]) if self.capability_tags else ""
        return (
            f"{'[+]' if self.is_online else '[-]'} {self.name:20s} | "
            f"{self.provider:12s} | score={self.match_score:.2f} | "
            f"{cost} | {caps}"
        )


@dataclass
class FindPartnersRequest:
    """find_partners 請求參數。"""
    task_brief: str               # 自然語言任務描述
    budget: str = "any"           # free / low / any
    prefer_local: bool = False
    top_k: int = 5
    domain: Optional[str] = None

    # ContextSpace 輸入（可選）
    context_vec: Optional[list[float]] = None  # 當前語境向量

    # 過濾條件
    min_match_score: float = 0.0
    require_online: bool = True


@dataclass
class FindPartnersResult:
    """find_partners 結果。"""
    request: FindPartnersRequest
    candidates: list[WorkerCandidate] = field(default_factory=list)
    total_candidates: int = 0
    match_method: str = "embedding"  # fast_route / embedding / hermes_cli

    # 路由路徑
    route_mode: str = "full"        # fast / full
    aggregation: dict[str, float] = field(default_factory=dict)  # 各維度得分

    def best(self) -> Optional[WorkerCandidate]:
        return self.candidates[0] if self.candidates else None

    def filter_by_budget(self, budget: str) -> list[WorkerCandidate]:
        if budget == "free":
            return [c for c in self.candidates if c.is_free]
        return self.candidates
