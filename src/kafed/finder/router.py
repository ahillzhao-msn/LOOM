"""KAFED Finder — 路由協議（find_partners）。

雙模式路由：
  fast_route — 模型池 < fast_route_max_workers（默認 3）時走快速路
              直接用 Hermes 默認模型 + 本地探活 + config.yaml
  full_route — 多模型場景走完整三維聚合：
              能力匹配 (w_cap) + 語境調製 (w_ctx) + 實時狀態 (w_sta)

唯一入口：find_partners(task_brief) → FindPartnersResult
Router 不自己選模型——只返回候選列表 + 匹配度。
最終選擇由 Director 的決策樹完成。

所有超參數從 config.py 讀取，零硬編碼。
"""

from __future__ import annotations

import json
import pickle
import subprocess
from typing import Any, Optional

import numpy as np
from numpy import dot
from numpy.linalg import norm
import yaml

from kafed.config import get_config
from kafed.finder.matcher import WorkerCandidate, FindPartnersRequest, FindPartnersResult
from kafed.finder.registry import Registry
from kafed.finder.context_space import ContextSpace


class Router:
    """路由協議。

    雙模式：
      - fast_route: 可用模型 < 3 時，跳過 embedding 匹配，用 Hermes 配置+探活
      - full_route: 完整三維聚合
    """

    def __init__(self):
        self.registry = Registry()
        self._vectors: dict[str, np.ndarray] = {}
        self._context_space: Optional[ContextSpace] = None
        self._cfg = get_config()
        self._load_vectors()

    def _lazy_context(self) -> ContextSpace:
        if self._context_space is None:
            self._context_space = ContextSpace()
        return self._context_space

    def _load_vectors(self):
        vp = self._cfg.vectors_path
        if vp.exists():
            try:
                with open(vp, "rb") as f:
                    self._vectors = pickle.load(f)
            except Exception:
                self._vectors = {}

    # ══════════════════════════════════════════════════
    # 唯一入口
    # ══════════════════════════════════════════════════

    def find_partners(self, brief: str, budget: str = "any",
                       prefer_local: bool = False, top_k: int = 5,
                       domain: Optional[str] = None,
                       context_vec: Optional[list[float]] = None) -> FindPartnersResult:
        """自然語言任務描述 → 候選列表。

        自動選擇 fast_route 或 full_route，調用方無需感知。
        """
        request = FindPartnersRequest(
            task_brief=brief, budget=budget,
            prefer_local=prefer_local, top_k=top_k,
            domain=domain, context_vec=context_vec,
        )

        # 判斷模式
        candidates = self.registry.load()
        online_count = sum(1 for c in candidates if c.is_online)

        if online_count < self._cfg.fast_route_max_workers:
            return self._fast_route(request, candidates)
        else:
            return self._full_route(request, candidates)

    # ══════════════════════════════════════════════════
    # 快速路由
    # ══════════════════════════════════════════════════

    def _fast_route(self, request: FindPartnersRequest,
                    candidates: list[WorkerCandidate]) -> FindPartnersResult:
        """模型池 < 3 時：直接從 Hermes 配置 + 本地探活獲取模型。"""
        from kafed.client.flow import chain
        chain("find/route", [
            ("mod", "fast", f"workers={len(candidates)}"),
        ], end="config+local")

        workers: list[WorkerCandidate] = []

        # 1. hermes model current（如果 hermes CLI 可用）
        try:
            result = subprocess.run(
                ["hermes", "config", "get", "default_model"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                name = result.stdout.strip()
                if name:
                    workers.append(WorkerCandidate(
                        name=name, provider="hermes", model_id=name,
                        match_score=0.9, is_free=False, is_online=True,
                    ))
        except Exception:
            pass

        # 2. llama-server /v1/models 即時發現
        try:
            r = subprocess.run(
                ["curl", "-s", "--connect-timeout", "3",
                 "http://localhost:8000/v1/models"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                data = json.loads(r.stdout) if r.stdout else {}
                for m in data.get("data", []):
                    name = m.get("id", "")
                    if name and name not in {w.name for w in workers}:
                        workers.append(WorkerCandidate(
                            name=name, provider="local", model_id=name,
                            match_score=0.7, is_free=True, is_online=True,
                            estimated_tps=55,
                        ))
        except Exception:
            pass

        # 3. config.yaml models 節
        cp = self._cfg.config_path
        if cp.exists():
            try:
                with open(cp) as f:
                    cfg = yaml.safe_load(f)
                for m in (cfg.get("models", []) if isinstance(cfg, dict) else []):
                    name = m.get("name", m.get("model", ""))
                    if name and name not in {w.name for w in workers}:
                        workers.append(WorkerCandidate(
                            name=name, provider=m.get("provider", "local"),
                            model_id=m.get("model", name),
                            match_score=0.6, is_free=m.get("provider") in ("local", "llama"),
                        ))
            except Exception:
                pass

        # 4. 探活 + 排序
        live = self.registry.verify_candidates(workers)
        live.sort(key=lambda c: c.match_score, reverse=True)

        chain("find/done", [
            ("", f"{len(live)} candidates", ""),
        ], end="fast_route")

        return FindPartnersResult(
            request=request, candidates=live[:request.top_k],
            total_candidates=len(live),
            match_method="hermes_cli", route_mode="fast",
        )

    # ══════════════════════════════════════════════════
    # 完整路由（三維聚合）
    # ══════════════════════════════════════════════════

    def _full_route(self, request: FindPartnersRequest,
                    candidates: list[WorkerCandidate]) -> FindPartnersResult:
        """三維聚合路由：能力匹配 × 語境調製 × 實時狀態。"""
        from kafed.client.flow import chain
        chain("find/route", [
            ("mod", "full", f"workers={len(candidates)}"),
        ], end="embed+ctx+status")

        cands = list(candidates)

        # Step 1: 預算過濾
        if request.budget == "free":
            cands = [c for c in cands if c.is_free]

        # Step 2: 本地優先
        if request.prefer_local:
            local = [c for c in cands if c.provider == "local"]
            if local:
                cands = local + [c for c in cands if c.provider != "local"]

        # Step 3: 能力匹配 (w_cap)
        if self._vectors and request.task_brief:
            self._match_capability(request.task_brief, cands)

        # Step 4: 語境調製 (w_ctx)
        ctx_boosts: dict[str, float] = {}
        if request.context_vec is not None:
            cs = self._lazy_context()
            ctx_boosts = cs.modulate(request.context_vec, cands)
            for c in cands:
                c.context_boost = ctx_boosts.get(c.name, 0.0)

        # Step 5: 實時狀態 (w_sta) — 探活 + 狀態向量
        live = self.registry.verify_candidates(cands[:20])
        offline_names = {c.name for c in cands[:20] if not c.is_online}
        cands = live + [c for c in cands[20:] if c.name not in offline_names]

        # Step 6: 三維聚合評分
        w_cap = self._cfg.finder_w_cap
        w_ctx = self._cfg.finder_w_ctx
        w_sta = self._cfg.finder_w_sta

        for c in cands:
            cap_score = c.match_score  # 來自 embedding
            ctx_score = c.context_boost
            # 狀態維度：online + tps
            sv = c.status_vector if len(c.status_vector) >= 2 else [1.0, 0.0, 0.0]
            sta_score = sv[0] * 0.6 + sv[1] * 0.4
            c.match_score = round(
                w_cap * cap_score + w_ctx * ctx_score + w_sta * sta_score,
                4,
            )

        # Step 7: 排序
        cands.sort(key=lambda c: (c.is_online, c.match_score, c.success_rate), reverse=True)

        # Step 8: 補充（在線不足時）
        top = cands[:request.top_k]
        if len(top) < 3:
            config_workers = self._discover_config_workers()
            for w in config_workers:
                if w not in top:
                    top.append(w)
            top = top[:request.top_k]

        agg = {
            "w_cap": w_cap, "w_ctx": w_ctx, "w_sta": w_sta,
            "n_candidates": len(cands),
            "n_live": len(live),
        }

        chain("find/done", [
            ("cap", f"{w_cap}", ""),
            ("ctx", f"{w_ctx}", ""),
            ("sta", f"{w_sta}", ""),
        ], end=f"{len(top)}/{len(cands)}")

        return FindPartnersResult(
            request=request, candidates=top,
            total_candidates=len(cands),
            match_method="embedding", route_mode="full",
            aggregation=agg,
        )

    # ══════════════════════════════════════════════════
    # 能力匹配
    # ══════════════════════════════════════════════════

    def _match_capability(self, brief: str, candidates: list[WorkerCandidate]) -> None:
        """對候選列表進行 embedding 能力匹配。"""
        from kafed.knowledge.rag.embedding import embed_texts
        brief_vec = embed_texts([brief])[0]
        for c in candidates[:50]:
            vec = self._vectors.get(c.name) or self._vectors.get(c.model_id)
            if vec is not None:
                sim = float(dot(brief_vec, vec) / (norm(brief_vec) * norm(vec) + 1e-10))
                c.match_score = max(0.0, min(1.0, (sim + 1) / 2))
            else:
                # 無向量 → keyword 啟發式
                brief_lower = brief.lower()
                c.match_score = max(0.0, self._keyword_match(
                    brief_lower, c.name.lower(), c.domain.lower()))

    def _keyword_match(self, brief: str, name: str, domain: str) -> float:
        score = 0.0
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

    # ══════════════════════════════════════════════════
    # 日誌記錄（供 Director 每輪結束時調用）
    # ══════════════════════════════════════════════════

    def record_context(self, context_vec: list[float],
                       model_name: str, success: bool = True,
                       user_input: str = "", eval_info: str = "",
                       hexagram_info: str = "") -> None:
        """記錄交互語境到 ContextSpace。由 Director 每輪結束時調用。"""
        cs = self._lazy_context()
        cs.record(context_vec, model_name, success=success,
                  user_input=user_input, eval_info=eval_info,
                  hexagram_info=hexagram_info)

    # ══════════════════════════════════════════════════
    # 補充發現
    # ══════════════════════════════════════════════════

    def _discover_config_workers(self) -> list[WorkerCandidate]:
        workers = []
        cp = self._cfg.config_path
        if cp.exists():
            try:
                with open(cp) as f:
                    cfg = yaml.safe_load(f)
                for m in (cfg.get("models", []) if isinstance(cfg, dict) else []):
                    workers.append(WorkerCandidate(
                        name=m.get("name", m.get("model", "unknown")),
                        provider=m.get("provider", "local"),
                        model_id=m.get("model", ""),
                        match_score=0.5,
                        is_free=m.get("provider") in ("local", "llama"),
                    ))
            except Exception:
                pass

        known_names = {w.name for w in workers}
        for m in self._cfg.cloud_models:
            if m["name"] not in known_names:
                workers.append(WorkerCandidate(
                    name=m["name"], provider=m["provider"],
                    model_id=m["name"], match_score=0.4,
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
                   domain: Optional[str] = None,
                   context_vec: Optional[list[float]] = None) -> FindPartnersResult:
    """便利函數：直接調用 find_partners。"""
    return get_router().find_partners(
        brief, budget, prefer_local, top_k, domain,
        context_vec=context_vec,
    )
