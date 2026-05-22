"""
KAFED Finder — 模型註冊表（Registry）。

管理可用的工人（worker）清單、能力向量、實時狀態。
吸收 worker_manager.py 的核心邏輯。
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from kafed.finder.matcher import WorkerCandidate

HOME = Path.home()
ROSTER_PATH = Path(os.getenv("KAFED_ROSTER_PATH", str(HOME / ".hermes" / "data" / "roster.yaml")))
CONFIG_PATH = Path(os.getenv("KAFED_CONFIG_PATH", str(HOME / ".hermes" / "config.yaml")))
WORKER_VECTORS_PATH = Path(os.getenv("KAFED_VECTORS_PATH", str(HOME / ".hermes" / "data" / "worker_vectors.pkl")))


class Registry:
    """模型註冊表。
    
    提供統一的模型註冊、查詢、狀態更新接口。
    """
    
    def __init__(self):
        self._roster: list[dict] = []
        self._cache: dict[str, WorkerCandidate] = {}
        self._loaded = False
    
    def load(self) -> list[WorkerCandidate]:
        """從 roster.yaml 加載模型清單。"""
        if self._loaded and self._cache:
            return list(self._cache.values())
        
        if ROSTER_PATH.exists():
            with open(ROSTER_PATH) as f:
                data = yaml.safe_load(f)
                workers = data.get("workers", []) if isinstance(data, dict) else []
        else:
            workers = self._discover_from_config()
        
        candidates = []
        for w in workers:
            candidates.append(WorkerCandidate(
                name=w.get("name", w.get("id", "unknown")),
                provider=w.get("provider", "local"),
                model_id=w.get("model", w.get("id", "")),
                match_score=w.get("match_score", 0.5),
                domain=w.get("domain", ""),
                is_online=w.get("is_online", True),
                is_free=w.get("is_free", True),
                total_calls=w.get("total_calls", 0),
                success_rate=w.get("success_rate", 0.0),
                cost_per_token=w.get("cost_per_token", 0.0),
            ))
            self._cache[w.get("name", w.get("id", ""))] = candidates[-1]
        
        self._roster = workers
        self._loaded = True
        return candidates
    
    def _discover_from_config(self) -> list[dict]:
        """從 config.yaml 發現模型。"""
        workers = []
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                cfg = yaml.safe_load(f)
            
            models = cfg.get("models", []) if isinstance(cfg, dict) else []
            for m in models:
                workers.append({
                    "name": m.get("name", m.get("model", "unknown")),
                    "provider": m.get("provider", "local"),
                    "model": m.get("model", ""),
                    "is_free": m.get("provider") in ("local", "llama"),
                })
        
        return workers
    
    def is_online(self, name: str) -> bool:
        """檢查模型是否在線。"""
        # 本地 llama-server 檢查
        try:
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "http://localhost:8000/health"],
                capture_output=True, text=True, timeout=3,
            )
            return result.stdout.strip() == "200"
        except Exception:
            return False
    
    def register(self, worker_id: str, worker_type: str = "expert",
                 domain: str = "", provider: str = "local",
                 model: str = "") -> None:
        """註冊新專家。"""
        entry = {
            "id": worker_id,
            "name": worker_id,
            "type": worker_type,
            "domain": domain,
            "provider": provider,
            "model": model or worker_id,
            "is_free": provider in ("local", "llama"),
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "total_calls": 0,
            "success_rate": 1.0,
        }
        
        roster = []
        if ROSTER_PATH.exists():
            with open(ROSTER_PATH) as f:
                roster = yaml.safe_load(f) or []
                if isinstance(roster, dict):
                    roster = roster.get("workers", [])
        
        roster.append(entry)
        
        ROSTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ROSTER_PATH, "w") as f:
            yaml.dump({"workers": roster, "updated_at": datetime.now(timezone.utc).isoformat()}, f)
        
        # 清除緩存
        self._loaded = False
    
    def report_success(self, worker_id: str, dimension: str = "") -> None:
        """更新模型成功評分。"""
        if not ROSTER_PATH.exists():
            return
        
        with open(ROSTER_PATH) as f:
            data = yaml.safe_load(f) or {}
        
        workers = data.get("workers", []) if isinstance(data, dict) else []
        for w in workers:
            if w.get("id") == worker_id or w.get("name") == worker_id:
                w["total_calls"] = w.get("total_calls", 0) + 1
                # 滾動平均成功率
                prev_sr = w.get("success_rate", 1.0)
                w["success_rate"] = (prev_sr * 0.9) + 0.1
                break
        
        with open(ROSTER_PATH, "w") as f:
            yaml.dump(data, f)
        
        self._loaded = False
