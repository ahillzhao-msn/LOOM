"""
KAFED Finder — 模型即時狀態快取（StatusCache）。

設計原則：
  - Pickle 持久，與 worker_vectors.pkl 同層
  - 無歷史累積——每次探測覆寫，只保留最新結果 + 時間戳
  - 自然指數衰減排程：freshness = exp(-decay_rate * elapsed_s)
    穩定模型 probe 間隔自然延長，變動模型 probe 間隔縮短
  - Router 同步讀取零阻塞（無網路 I/O）
  - verify_candidates 設 force_probe_flag → heartbeat 下次 tick 處理
"""

from __future__ import annotations

import math
import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class StatusEntry:
    """單個模型的即時狀態。"""

    # ── 狀態向量（4 維）──
    online: bool = False          # 可達性
    tps: float = 0.0              # tokens/sec（實測）
    load: float = 0.0             # 負載 0.0-1.0（CPU/Mem 或 帶寬推斷）
    latency_ms: float = 0.0       # 探測延遲（ms）

    # ── 新鮮度管理（自然指數衰減）──
    last_probe_at: float = 0.0    # time.time()
    freshness: float = 0.0        # 1.0 (just probed) → 0.0 (stale)
    decay_rate: float = 0.05      # 衰減係數 (/s)

    # ── 探測排程（backoff）──
    next_probe_at: float = 0.0    # 未到此時不 probe
    force_probe: bool = False     # Router 設此標記 → 下次 tick 強制 probe
    backoff_level: int = 0        # 0=base, N=base*2^N (cap at max)
    stable_count: int = 0         # 連續未變化的 probe 次數

    # ── 元資訊 ──
    provider: str = "local"
    name: str = ""
    model_id: str = ""

    @property
    def status_vector(self) -> list[float]:
        """4 維向量 [online, tps_norm, load_norm, latency_ms]。
        
        與 find_partners 三維聚合相容（前 3 維 + latency 擴充）。
        """
        tps_norm = min(1.0, self.tps / 200.0) if self.tps > 0 else 0.0
        return [1.0 if self.online else 0.0,
                round(tps_norm, 4),
                round(self.load, 4),
                round(self.latency_ms, 2)]


def compute_freshness(decay_rate: float, elapsed_s: float) -> float:
    """自然指數衰減：freshness = exp(-decay_rate * elapsed_s)。"""
    return math.exp(-decay_rate * elapsed_s)


def next_backoff_delay(backoff_level: int, base: float, max_delay: float) -> float:
    """指數退避：base * 2^level, capped at max_delay。"""
    delay = base * (2 ** backoff_level)
    return min(delay, max_delay)


# ── 批次快取 ─────────────────────────────────────


class StatusCache:
    """所有模型的即時狀態快取。
    
    使用方式：
      cache = StatusCache()
      entry = cache.get("leader")
      if entry is None or entry.need_probe(threshold=0.3):
          entry = probe_model("leader")
          cache.update("leader", entry)
      cache.save()
    """

    def __init__(self, path: Optional[Path] = None):
        from kafed.config import get_config
        self._path = path or get_config().status_cache_path
        self._data: dict[str, StatusEntry] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                with open(self._path, "rb") as f:
                    self._data = pickle.load(f)
            except Exception:
                self._data = {}
        # 清理過期（> 1h 無 probe）
        now = time.time()
        stale_keys = [k for k, v in self._data.items()
                      if now - v.last_probe_at > 3600]
        for k in stale_keys:
            del self._data[k]

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "wb") as f:
            pickle.dump(self._data, f)

    def get(self, key: str) -> Optional[StatusEntry]:
        return self._data.get(key)

    def update(self, key: str, entry: StatusEntry):
        self._data[key] = entry

    def remove(self, key: str):
        self._data.pop(key, None)

    def all(self) -> dict[str, StatusEntry]:
        return dict(self._data)

    def keys(self) -> list[str]:
        return list(self._data.keys())

    def need_probe(self, key: str, threshold: Optional[float] = None) -> bool:
        """是否需要探測此模型？

        觸發條件：
          - force_probe 被設為 True（Router 同步觸發）
          - now >= next_probe_at（自然排程到期）
          - freshness < threshold（衰減至閾值以下）
        """
        entry = self._data.get(key)
        if entry is None:
            return True
        if entry.force_probe:
            return True
        now = time.time()
        if now >= entry.next_probe_at:
            return True
        if threshold is not None:
            elapsed = now - entry.last_probe_at
            fresh = compute_freshness(entry.decay_rate, elapsed)
            if fresh < threshold:
                return True
        return False

    def mark_probe_done(self, key: str, entry: StatusEntry):
        """探測完成後更新排程資訊。"""
        now = time.time()
        entry.last_probe_at = now
        entry.force_probe = False

        # 新鮮度重置
        elapsed = 0.0
        entry.freshness = 1.0

        # backoff：狀態未變則增，變則重置
        old = self._data.get(key)
        if old is not None:
            changed = (old.online != entry.online or
                       abs(old.tps - entry.tps) / max(old.tps, 1) > 0.2)
            if changed:
                entry.backoff_level = 0
                entry.stable_count = 0
            else:
                entry.backoff_level += 1
                entry.stable_count += 1

        # 計算下次探測時間
        base = (60.0 if entry.provider in ("deepseek", "anthropic", "openai", "openrouter")
                else 10.0)
        max_d = (600.0 if entry.provider in ("deepseek", "anthropic", "openai", "openrouter")
                 else 120.0)
        delay = next_backoff_delay(entry.backoff_level, base, max_d)
        entry.next_probe_at = now + delay

        self._data[key] = entry
