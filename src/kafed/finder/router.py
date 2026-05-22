"""
KAFED Finder — 路由協議（find_partners）。

唯一入口：find_partners(task_brief)
三維聚合：任務描述 × 模型能力 × 實時狀態

吸收 discern-engine/scripts/router.py 的核心邏輯。
"""

from __future__ import annotations

import json
import os
import pickle
import re
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import yaml

from kafed.finder.matcher import WorkerCandidate, FindPartnersRequest, FindPartnersResult
from kafed.finder.registry import Registry

HOME = Path.home()
ROSTER_PATH = Path(os.getenv("KAFED_ROSTER_PATH", str(HOME / ".hermes" / "data" / "roster.yaml")))
VECTORS_PATH = Path(os.getenv("KAFED_VECTORS_PATH", str(HOME / ".hermes" / "data" / "worker_vectors.pkl")))

# 內置雲端模型（config.yaml 無效時兜底）
CLOUD_MODELS = [
    {"name": "deepseek-v4-flash", "provider": "deepseek", "is_free": False, "cost": 0.00015, "tags": ["reasoning", "coding"]},
    {"name": "claude-sonnet-4", "provider": "anthropic", "is_free": False, "cost": 0.003, "tags": ["reasoning", "analysis"]},
    {"name": "gpt-4o", "provider": "openai", "is_free": False, "cost": 0.0025, "tags": ["reasoning", "vision"]},
]


class Router:
    """路由協議。
    
    唯一入口：find_partners(task_brief) → FindPartnersResult
    
    Router 不自己選模型——它只返回候選列表 + 匹配度。
    最終選擇由 Director 的決策樹完成。
    """
    
    def __init__(self):
        self.registry = Registry()
        self._vectors: dict[str, np.ndarray] = {}
        self._load_vectors()
    
    def _load_vectors(self):
        """加載預計算的模型特徵向量。"""
        if VECTORS_PATH.exists():
            try:
                with open(VECTORS_PATH, "rb") as f:
                    self._vectors = pickle.load(f)
            except Exception:
                self._vectors = {}
    
    def find_partners(self, brief: str, budget: str = "any",
                       prefer_local: bool = False, top_k: int = 5,
                       domain: Optional[str] = None) -> FindPartnersResult:
        """核心方法：自然語言任務描述 → 候選列表。"""
        request = FindPartnersRequest(
            task_brief=brief,
            budget=budget,
            prefer_local=prefer_local,
            top_k=top_k,
            domain=domain,
        )
        
        # Step 1: 從註冊表加載候選
        candidates = self.registry.load()
        
        # Step 2: 預算過濾
        if budget == "free":
            candidates = [c for c in candidates if c.is_free]
        
        # Step 3: 本地優先
        if prefer_local:
            local = [c for c in candidates if c.provider == "local"]
            if local:
                candidates = local + [c for c in candidates if c.provider != "local"]
        
        # Step 4: 領域匹配（embedding based / keyword fallback）
        if domain:
            domain_candidates = [c for c in candidates if c.domain.lower() == domain.lower()]
            if domain_candidates:
                for c in domain_candidates:
                    c.match_score = 0.8
                candidates = domain_candidates + [c for c in candidates if c not in domain_candidates]
        
        # Step 5: Embedding 匹配（如果有 vectors）
        if self._vectors and brief:
            brief_lower = brief.lower()
            for c in candidates[:20]:
                vec = self._vectors.get(c.name) or self._vectors.get(c.model_id)
                if vec is not None:
                    # 向量已預計算，直接使用存儲的匹配度
                    pass  # match_score 已在 load() 中設置
            
            # 無向量時的 keyword 啟發式匹配
            for c in candidates[:10]:
                kw_score = self._keyword_match(brief_lower, c.name.lower(), c.domain.lower())
                c.match_score = max(c.match_score, kw_score)
        
        # Step 6: 排序
        candidates.sort(key=lambda c: (c.is_online, c.match_score, c.success_rate), reverse=True)
        
        # Step 7: Top-K
        top = candidates[:top_k]
        
        # Step 8: 如果在線模型不足，補充 config.yaml 發現
        if len(top) < 3:
            config_workers = self._discover_config_workers()
            for w in config_workers:
                if w not in top:
                    top.append(w)
            top = top[:top_k]
        
        return FindPartnersResult(
            request=request,
            candidates=top,
            total_candidates=len(candidates),
            match_method="embedding" if self._vectors else "config",
        )
    
    def _keyword_match(self, brief: str, name: str, domain: str) -> float:
        """關鍵字啟發式匹配。"""
        score = 0.0
        
        # 領域 vs 任務關鍵詞
        domain_keywords = {
            "sap": ["sap", "abap", "pm", "vc", "cspo", "iw31", "iw33"],
            "python": ["python", "script", "pytest", "flask", "fastapi"],
            "data": ["data", "analytics", "pandas", "sql", "query"],
        }
        
        for kw_domain, keywords in domain_keywords.items():
            if domain.startswith(kw_domain) or domain in kw_domain:
                for kw in keywords:
                    if kw in brief:
                        score += 0.15
        
        return min(score, 0.5)
    
    def _discover_config_workers(self) -> list[WorkerCandidate]:
        """從 config.yaml / 內置發現模型。"""
        workers = []
        
        # 嘗試 config.yaml
        config_path = Path(os.getenv("KAFED_CONFIG_PATH", str(HOME / ".hermes" / "config.yaml")))
        if config_path.exists():
            try:
                with open(config_path) as f:
                    cfg = yaml.safe_load(f)
                models = cfg.get("models", []) if isinstance(cfg, dict) else []
                for m in models:
                    workers.append(WorkerCandidate(
                        name=m.get("name", m.get("model", "unknown")),
                        provider=m.get("provider", "local"),
                        model_id=m.get("model", ""),
                        match_score=0.5,
                        is_free=m.get("provider") in ("local", "llama"),
                    ))
            except Exception:
                pass
        
        # 補充內置雲端模型
        known_names = {w.name for w in workers}
        for m in CLOUD_MODELS:
            if m["name"] not in known_names:
                workers.append(WorkerCandidate(
                    name=m["name"],
                    provider=m["provider"],
                    model_id=m["name"],
                    match_score=0.4,
                    is_free=m.get("is_free", False),
                    cost_per_token=m.get("cost", 0),
                ))
        
        return workers


# ── 全局 Router 實例 ──────────────────────────────
_router: Optional[Router] = None


def get_router() -> Router:
    global _router
    if _router is None:
        _router = Router()
    return _router


def find_partners(brief: str, budget: str = "any",
                   prefer_local: bool = False, top_k: int = 5,
                   domain: Optional[str] = None) -> FindPartnersResult:
    """便利函數：直接調用 find_partners。"""
    return get_router().find_partners(brief, budget, prefer_local, top_k, domain)
