"""
KAFED Finder — 路由協議（find_partners）。

三向量聚合架構（核心邏輯）：
  find_partners 接收 three 輸入向量流，輸出 N 個匹配結果（N = 子任務數）：

  輸入 1: 子任務向量組  — Director 分解後的 N 個任務自然語言描述 → N 個 embedding
  輸入 2: 模型向量池    — Explorer 定期掃描全量可用模型 → 按公共 schema 生成嵌入
  輸入 3: 實時狀態向量  — 心跳/即時查詢獲取（可達性、響應速度、在線狀態）

  聚合：每個子任務獨立做 cosine similarity（子任務 ⊗ 模型向量） + 語境調製 + 狀態加權
  輸出：每個子任務 → 匹配度排序的模型候選列表 → Director 做最終選擇

  所有模型維度（context_window / 能力標籤 / 成本 / 溫控等）統一由 schema
  生成嵌入描述，不單獨做 field-by-field 硬編碼過濾。

雙模式路由：
  fast_route  — 模型池 < 閾值：跳過 embedding，走 Hermes CLI 即時發現
  full_route  — 完整三向量聚合

唯一入口：find_partners(briefs) → list[FindPartnersResult]
Router 不選模型——只返回每個子任務的匹配度排序候選列表。
最終選擇由 Director 決策樹 + 三省完成。
"""

from __future__ import annotations

import json
import pickle
import subprocess
from typing import Optional

import numpy as np
import yaml

from kafed.config import get_config
from kafed.finder.matcher import WorkerCandidate, FindPartnersRequest, FindPartnersResult
from kafed.finder.registry import Registry
from kafed.finder.context_space import ContextSpace


class Router:
    """路由協議。

    雙模式（自動切換）：
      - fast_route: 可用模型 < 閾值 → 直連 Hermes 配置 + 本地探活
      - full_route: 三向量聚合（任務 ⊗ 模型 ⊗ 狀態）
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

        # 冷啟動：向量不存在或為空時自動掃描生成
        if not self._vectors:
            try:
                from kafed.finder.explorer import Explorer
                workers = Explorer.scan_all()
                Explorer.update_vector_space(workers)
                # 重新載入
                if vp.exists():
                    with open(vp, "rb") as f:
                        self._vectors = pickle.load(f)
            except Exception as exc:
                pass  # 生成失敗時保持空向量，走 keyword fallback

    # ══════════════════════════════════════════════════
    # 唯一入口
    # ══════════════════════════════════════════════════

    def find_partners(self, briefs: list[str], budget: str = "any",
                       prefer_local: bool = False, top_k: int = 5,
                       domain: Optional[str] = None,
                       context_vec: Optional[list[float]] = None) -> list[FindPartnersResult]:
        """N 個子任務描述 → N 個匹配結果（每個含候選列表）。

        Director 分解後有 N 個子任務，就返回 N 個結果。

        Args:
            briefs:        子任務描述列表（每個 → embedding）
            budget:        free / low / any
            prefer_local:  偏愛本地
            top_k:         每個子任務返回 top-k 候選
            domain:        領域過濾
            context_vec:   當前語境向量（ContextSpace 調製用）
        """
        if not briefs:
            return []

        # ── 判斷模式 + 共享模型發現 ──
        candidates = self.registry.load()
        online_count = sum(1 for c in candidates if c.is_online)
        is_fast = online_count < self._cfg.fast_route_max_workers

        if is_fast:
            workers = self._discover_fast_workers()
        else:
            workers = list(candidates)

        # ── 共享預處理（所有子任務共用同一模型池的過濾+狀態）──
        workers = self._prepare_candidate_pool(workers, budget, prefer_local)

        # ── 每個子任務獨立做匹配 ──
        results: list[FindPartnersResult] = []
        for i, brief in enumerate(briefs):
            req = FindPartnersRequest(
                task_brief=brief, budget=budget,
                prefer_local=prefer_local, top_k=top_k,
                domain=domain, context_vec=context_vec,
            )

            # 每個子任務獨立拷貝候選列表（匹配分數是 per-brief 的）
            cands = [self._copy_candidate(c) for c in workers]

            if is_fast:
                # fast route: 用靜態分數排序（無 embedding 匹配）
                cands.sort(key=lambda c: c.match_score, reverse=True)
                result_kwargs: dict = dict(match_method="hermes_cli", route_mode="fast")
            else:
                # full route: 三向量聚合
                result_kwargs: dict = self._match_one(brief, cands, context_vec)

            top = cands[:top_k]
            # 補充不足
            if len(top) < 3:
                extra = self._discover_config_workers()
                for w in extra:
                    if w not in top:
                        top.append(w)
                top = top[:top_k]

            results.append(FindPartnersResult(
                request=req, candidates=top,
                total_candidates=len(cands),
                task_index=i,
                **result_kwargs,
            ))

        return results

    # ══════════════════════════════════════════════════
    # 共享：模型池準備
    # ══════════════════════════════════════════════════

    def _prepare_candidate_pool(self, workers: list[WorkerCandidate],
                                 budget: str, prefer_local: bool) -> list[WorkerCandidate]:
        """模型池預處理（過濾 + 探活），所有子任務共用。"""
        # 預算過濾
        if budget == "free":
            workers = [c for c in workers if c.is_free]

        # 本地優先
        if prefer_local:
            local = [c for c in workers if c.provider == "local"]
            if local:
                workers = local + [c for c in workers if c.provider != "local"]

        # 從 StatusCache 讀取狀態（零網路 I/O），未快取者設 force_probe
        workers = self.registry.verify_candidates(workers, force=True)

        return workers

    @staticmethod
    def _copy_candidate(c: WorkerCandidate) -> WorkerCandidate:
        """輕量拷貝，保留身份和狀態但重置 match_score。"""
        nc = WorkerCandidate(
            name=c.name, provider=c.provider, model_id=c.model_id,
            meta=dict(c.meta), is_online=c.is_online,
            is_free=c.is_free, cost_per_token=c.cost_per_token,
            capability_tags=list(c.capability_tags),
            estimated_tps=c.estimated_tps,
            status_vector=list(c.status_vector),
            match_score=0.5,  # 每個子任務重新計算
        )
        nc.total_calls = c.total_calls
        nc.success_rate = c.success_rate
        return nc

    # ══════════════════════════════════════════════════
    # 單個子任務的三向量聚合
    # ══════════════════════════════════════════════════

    def _match_one(self, brief: str, cands: list[WorkerCandidate],
                   context_vec: Optional[list[float]]) -> dict:
        """一個子任務的完整三向量聚合。

        返回 Result 構建參數字典（match_method, route_mode, aggregation）。
        """
        from kafed.client.flow import chain
        chain("find/route", [
            ("mod", "full", f"cands={len(cands)}"),
        ], end=f"brief={brief[:30]}")

        # ── 輸入 1 ⊗ 輸入 2: 子任務向量 × 模型向量（cosine similarity）──
        if self._vectors and brief:
            self._match_capability(brief, cands)

        # ── 語境調製（ContextSpace 近期歷史偏向）──
        ctx_boosts: dict[str, float] = {}
        if context_vec is not None:
            cs = self._lazy_context()
            ctx_boosts = cs.modulate(context_vec, cands)
            for c in cands:
                c.context_boost = ctx_boosts.get(c.name, 0.0)

        # ── 三維聚合評分 ──
        w_cap = self._cfg.finder_w_cap
        w_ctx = self._cfg.finder_w_ctx
        w_sta = self._cfg.finder_w_sta

        for c in cands:
            cap_score = c.match_score
            ctx_score = c.context_boost
            sv = c.status_vector if len(c.status_vector) >= 3 else [1.0, 0.0, 0.0, 0.0]
            # 線上 + TPS + 負載（latency 保留未來用）
            sta_score = sv[0] * 0.5 + sv[1] * 0.3 + (1.0 - sv[2]) * 0.2
            c.match_score = round(
                w_cap * cap_score + w_ctx * ctx_score + w_sta * sta_score,
                4,
            )

        # ── 排序 ──
        cands.sort(key=lambda c: (c.is_online, c.match_score, c.success_rate), reverse=True)

        agg = {
            "w_cap": w_cap, "w_ctx": w_ctx, "w_sta": w_sta,
            "n_candidates": len(cands),
        }

        chain("find/done", [
            ("cap", f"{w_cap}", ""),
            ("ctx", f"{w_ctx}", ""),
            ("sta", f"{w_sta}", ""),
        ], end=f"best={cands[0].name if cands else 'none'}")

        return dict(match_method="embedding", route_mode="full", aggregation=agg)

    # ══════════════════════════════════════════════════
    # 快速發現（fast route 專用）
    # ══════════════════════════════════════════════════

    def _discover_fast_workers(self) -> list[WorkerCandidate]:
        """模型池 < 閾值時：跳過嵌入匹配，走 CLI + 即時探活。"""
        from kafed.client.flow import chain
        chain("find/route", [("mod", "fast", "")], end="local+config")

        workers: list[WorkerCandidate] = []

        # 1. hermes CLI default model
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

        # 2. llama-server /v1/models
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

        # 3. config.yaml
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

        # 探活
        live = self.registry.verify_candidates(workers)
        chain("find/done", [("", f"{len(live)} fast workers", "")], end="")
        return live

    # ══════════════════════════════════════════════════
    # 能力匹配（輸入 1 ⊗ 輸入 2 的 cosine similarity）
    # ══════════════════════════════════════════════════

    def _match_capability(self, brief: str, candidates: list[WorkerCandidate]) -> None:
        """任務描述 embedding × 模型向量矩陣 = cosine similarity（向量化）。"""
        if not self._vectors:
            return
        from kafed.knowledge.rag.embedding import embed_texts
        brief_vec = np.array(embed_texts([brief])[0], dtype=np.float32)

        # 收集有向量的候選 → 矩陣
        vec_indices: list[int] = []
        vec_rows: list[np.ndarray] = []
        novec_indices: list[int] = []
        for idx, c in enumerate(candidates[:100]):
            v = (self._vectors.get(c.name) if c.name else None)
            if v is None:
                v = self._vectors.get(c.model_id) if c.model_id else None
            if v is not None:
                vec_indices.append(idx)
                vec_rows.append(np.asarray(v, dtype=np.float32))
            else:
                novec_indices.append(idx)

        # 向量化 cosine similarity（矩陣運算 O(1) 而非 O(N)）
        if vec_rows:
            mat = np.stack(vec_rows, axis=0)            # (M, D)
            b_norm = np.linalg.norm(brief_vec)
            m_norm = np.linalg.norm(mat, axis=1)         # (M,)
            sims = (mat @ brief_vec) / (m_norm * b_norm + 1e-10)
            sims = np.clip((sims + 1) / 2, 0.0, 1.0)     # [-1,1] → [0,1]
            for pos, idx in enumerate(vec_indices):
                candidates[idx].match_score = round(float(sims[pos]), 4)

        # keyword fallback（無向量的候選）
        if novec_indices:
            brief_lower = brief.lower()
            for idx in novec_indices:
                c = candidates[idx]
                candidates[idx].match_score = max(0.0, self._keyword_match(
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
        """記錄交互語境到 ContextSpace。"""
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


def find_partners(brief: str | list[str], budget: str = "any",
                   prefer_local: bool = False, top_k: int = 5,
                   domain: Optional[str] = None,
                   context_vec: Optional[list[float]] = None) -> list[FindPartnersResult]:
    """便利函數：單任務自動包裝，多任務直接傳。

    Args:
        brief: 單個任務描述（str）或多個（list[str]）。單個時自動轉為 [brief]。
        其餘參數同 Router.find_partners。

    Returns:
        list[FindPartnersResult] — 長度 = 子任務數。
    """
    if isinstance(brief, str):
        briefs = [brief]
    else:
        briefs = brief
    return get_router().find_partners(
        briefs, budget, prefer_local, top_k, domain,
        context_vec=context_vec,
    )
