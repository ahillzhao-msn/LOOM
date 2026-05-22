"""
KAFED Finder — 模型發現器。

掃描 Hermes 所有模型配置源，探索可用模型並更新向量空間。
吸收 hermes_explorer.py 的核心邏輯。
"""

from __future__ import annotations

import json
import pickle
import subprocess
from typing import Any, Optional

import yaml

from kafed.config import get_config
from kafed.finder.registry import Registry
from kafed.finder.matcher import WorkerCandidate


class Explorer:
    """模型發現器。"""

    def __init__(self):
        self._cfg = get_config()

    @staticmethod
    def scan_all() -> list[WorkerCandidate]:
        """掃描所有來源的模型。"""
        cfg = get_config()
        workers = []
        seen = set()

        # 1. config.yaml
        cp = cfg.config_path
        if cp.exists():
            try:
                with open(cp) as f:
                    cfg_yaml = yaml.safe_load(f)
                models = cfg_yaml.get("models", []) if isinstance(cfg_yaml, dict) else []
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
        rp = cfg.roster_path
        if rp.exists():
            try:
                with open(rp) as f:
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
        """使用 KAFED embedding 模型生成每个 worker 的多维能力向量。

        描述文本包含：模型名、提供商、領域、能力標籤、成本類型。
        這樣同類能力的模型（推理/編碼/視覺）在向量空間中自然聚類。
        """
        import numpy as np
        from kafed.knowledge.rag.embedding import get_model
        model = get_model()
        vectors = {}
        for w in workers:
            caps = ", ".join(w.capability_tags) if w.capability_tags else "general"
            cost_type = "free" if w.is_free else "paid"
            desc = (
                f"model: {w.name} | provider: {w.provider} | "
                f"domain: {w.domain} | capabilities: {caps} | "
                f"cost: {cost_type}"
            )
            vec = model.encode([desc[:512]], show_progress_bar=False)[0]
            vectors[w.name] = np.array(vec, dtype=np.float32)
        
        vp = get_config().vectors_path
        vp.parent.mkdir(parents=True, exist_ok=True)
        with open(vp, "wb") as f:
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
    from kafed.client.flow import chain
    workers = Explorer.scan_all()
    chain("find/scan", [
        ("src", f"config+roster+llama", ""),
        ("hit", f"{len(workers)} workers", ""),
    ], end=f"update={update_roster}")
    for w in workers[:5]:
        print(f"  {w.describe()}")
    if len(workers) > 5:
        print(f"  ... and {len(workers) - 5} more")

    if update_roster and workers:
        Explorer.sync_roster(workers)
        Explorer.update_vector_space(workers)
        print(f"Roster updated with {len(workers)} workers")

    return workers
