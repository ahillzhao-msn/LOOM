"""
KAFED Finder — 模型註冊表（Registry）。

管理可用的模型清單、能力向量、實時狀態。
數據源不再是 roster.yaml——所有模型數據由 Explorer 掃描後存入向量空間。
Registry 是 Explorer 結果的緩存層 + StatusCache 橋接。

不再包含：
  - roster.yaml 讀寫（已由 Explorer 的向量空間取代）
  - 冗餘健康檢查（統一由 StatusCache + Heartbeat 管理）
  - 向後相容的舊 register()/report_success() 方法
"""

from __future__ import annotations

import pickle
from typing import Any, Optional

from kafed.config import get_config
from kafed.finder.matcher import WorkerCandidate


class Registry:
    """模型註冊表——純查詢層，數據源是 Explorer 的向量空間。"""

    def __init__(self):
        self._cfg = get_config()
        self._cache: dict[str, WorkerCandidate] = {}
        self._cache_timestamp: float = 0.0
        self._loaded = False

    def load(self) -> list[WorkerCandidate]:
        """從 Explorer 向量空間加載模型清單。

        優先使用緩存；緩存過期或空時從 worker_vectors.pkl 重建。
        若向量空間也不存在，返回空（由 Explorer 在首次使用時自動掃描）。
        """
        if self._loaded and self._cache:
            return list(self._cache.values())

        # 從向量空間的鍵列表重建 WorkerCandidate 元數據
        vp = self._cfg.vectors_path
        if not vp.exists():
            # 首次使用——觸發自動掃描
            try:
                from kafed.finder.explorer import Explorer
                workers = Explorer.scan_all()
                Explorer.update_vector_space(workers)
                for w in workers:
                    self._cache[w.name] = w
                self._loaded = True
                return list(self._cache.values())
            except Exception:
                return []

        try:
            with open(vp, "rb") as f:
                vectors = pickle.load(f)
        except Exception:
            return []

        # 從向量鍵重建輕量 WorkerCandidate 對象
        candidates = []
        for name in vectors:
            candidates.append(WorkerCandidate(
                name=name,
                provider="unknown",
                model_id=name,
                match_score=0.5,
                is_online=True,
            ))
            self._cache[name] = candidates[-1]

        self._loaded = True
        return candidates

    def verify_candidates(self, candidates: list[WorkerCandidate],
                          force: bool = False) -> list[WorkerCandidate]:
        """從 StatusCache 讀取狀態。零網路 I/O。"""
        from kafed.finder.status_cache import StatusCache
        cache = StatusCache()

        for c in candidates:
            entry = cache.get(c.name)
            if entry is not None:
                c.is_online = entry.online
                c.status_vector = entry.status_vector
            else:
                c.is_online = True
                c.status_vector = [0.5, 0.0, 0.5, 1000.0]  # 不確定默認（無緩存時）
                if force:
                    from kafed.finder.status_cache import StatusEntry
                    stub = StatusEntry(
                        name=c.name, provider=c.provider,
                        force_probe=True,
                    )
                    cache.update(c.name, stub)
                    cache.save()

        return candidates

    def get_status_vector(self, name: str, provider: str = "") -> list[float]:
        """從 StatusCache 讀取狀態向量。"""
        from kafed.finder.status_cache import StatusCache
        cache = StatusCache()
        entry = cache.get(name)
        if entry is not None:
            return entry.status_vector

        from kafed.finder.status_cache import StatusEntry
        stub = StatusEntry(name=name, provider=provider, force_probe=True)
        cache.update(name, stub)
        cache.save()
        # 用 stub 的 status_vector（內建 freshness 衰減）
        return stub.status_vector
