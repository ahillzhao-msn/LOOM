"""
KAFED Finder — 模型發現器。

掃描 Hermes 所有模型配置源，探索可用模型並更新向量空間。
吸收 hermes_explorer.py 的核心邏輯。
"""

from __future__ import annotations

import json
import os
import pickle
import subprocess
from pathlib import Path
from typing import Any, Optional

import yaml

from kafed.finder.registry import Registry
from kafed.finder.matcher import WorkerCandidate

HOME = Path.home()
ROSTER_PATH = Path(os.getenv("KAFED_ROSTER_PATH", str(HOME / ".hermes" / "data" / "roster.yaml")))
VECTORS_PATH = Path(os.getenv("KAFED_VECTORS_PATH", str(HOME / ".hermes" / "data" / "worker_vectors.pkl")))
CONFIG_PATH = Path(os.getenv("KAFED_CONFIG_PATH", str(HOME / ".hermes" / "config.yaml")))


class Explorer:
    """模型發現器。
    
    掃描所有模型配置源，生成完整的模型清單和向量空間。
    """
    
    @staticmethod
    def scan_all() -> list[WorkerCandidate]:
        """掃描所有來源的模型。"""
        workers = []
        seen = set()
        
        # 1. config.yaml
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH) as f:
                    cfg = yaml.safe_load(f)
                models = cfg.get("models", []) if isinstance(cfg, dict) else []
                for m in models:
                    name = m.get("name", m.get("model", ""))
                    if name and name not in seen:
                        workers.append(WorkerCandidate(
                            name=name,
                            provider=m.get("provider", "local"),
                            model_id=m.get("model", name),
                            match_score=0.5,
                            is_free=m.get("provider") in ("local", "llama"),
                        ))
                        seen.add(name)
            except Exception:
                pass
        
        # 2. roster.yaml
        if ROSTER_PATH.exists():
            try:
                with open(ROSTER_PATH) as f:
                    data = yaml.safe_load(f) or {}
                roster_workers = data.get("workers", []) if isinstance(data, dict) else []
                for w in roster_workers:
                    name = w.get("name", w.get("id", ""))
                    if name and name not in seen:
                        workers.append(WorkerCandidate(
                            name=name,
                            provider=w.get("provider", "local"),
                            model_id=w.get("model", name),
                            match_score=w.get("match_score", 0.5),
                            domain=w.get("domain", ""),
                            is_online=w.get("is_online", True),
                            is_free=w.get("is_free", True),
                            total_calls=w.get("total_calls", 0),
                            success_rate=w.get("success_rate", 0.0),
                        ))
                        seen.add(name)
            except Exception:
                pass
        
        # 3. llama-server 實時槽位
        try:
            result = subprocess.run(
                ["curl", "-s", "http://localhost:8000/v1/models"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout) if result.stdout else {}
                for m in data.get("data", []):
                    name = m.get("id", "")
                    if name and name not in seen:
                        workers.append(WorkerCandidate(
                            name=name,
                            provider="local",
                            model_id=name,
                            match_score=0.6,
                            is_free=True,
                            is_online=True,
                        ))
                        seen.add(name)
        except Exception:
            pass
        
        return workers
    
    @staticmethod
    def update_vector_space(workers: list[WorkerCandidate]) -> None:
        """更新模型向量空間（佔位符——實際 embedding 需要 KAFED）。"""
        # 此處生成簡單的 mock 向量供後續匹配使用
        import numpy as np
        vectors = {}
        for i, w in enumerate(workers):
            # 簡單的基於 hash 的偽向量（實際應使用 embedding 模型）
            seed = hash(w.name + w.provider + w.domain) % 10000
            rng = np.random.RandomState(seed)
            vectors[w.name] = rng.randn(384).astype(np.float32)
        
        VECTORS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(VECTORS_PATH, "wb") as f:
            pickle.dump(vectors, f)
    
    @staticmethod
    def sync_roster(workers: list[WorkerCandidate]) -> None:
        """同步到 roster.yaml。"""
        registry = Registry()
        for w in workers:
            registry.register(
                worker_id=w.name,
                worker_type="expert" if w.domain else "general",
                domain=w.domain,
                provider=w.provider,
                model=w.model_id,
            )


def scan(update_roster: bool = False) -> list[WorkerCandidate]:
    """探索所有可用模型。"""
    workers = Explorer.scan_all()
    print(f"Found {len(workers)} workers")
    for w in workers[:10]:
        print(f"  {w.describe()}")
    if len(workers) > 10:
        print(f"  ... and {len(workers) - 10} more")
    
    if update_roster and workers:
        Explorer.sync_roster(workers)
        Explorer.update_vector_space(workers)
        print(f"Roster updated with {len(workers)} workers")
    
    return workers
