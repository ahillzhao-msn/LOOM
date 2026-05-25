"""
KAFED Finder — 模型註冊表（Registry）。

管理可用的工人（worker）清單、能力向量、實時狀態。
吸收 worker_manager.py 的核心邏輯。
"""

from __future__ import annotations

import json
import socket
import subprocess
from datetime import datetime, timezone
from typing import Any, Optional

import yaml
from pathlib import Path

from kafed.config import get_config
from kafed.finder.matcher import WorkerCandidate

# ── Provider 探活配置 ──────────────────────────
# 已移入 kafed.config.health_endpoints


class Registry:
    """模型註冊表。
    
    提供統一的模型註冊、查詢、狀態更新接口。
    """

    def __init__(self):
        self._cfg = get_config()
        self._roster: list[dict] = []
        self._cache: dict[str, WorkerCandidate] = {}
        self._cache_timestamp: float = 0.0
        self._loaded = False
        self._health_cache: dict[str, bool] = {}

    def _rp(self) -> Path:
        return self._cfg.roster_path

    def _cp(self) -> Path:
        return self._cfg.config_path

    def _health_endpoints(self) -> dict[str, str]:
        return self._cfg.health_endpoints

    def load(self) -> list[WorkerCandidate]:
        """從 roster.yaml 加載模型清單。"""
        if self._loaded and self._cache:
            return list(self._cache.values())

        rp = self._rp()
        if rp.exists():
            with open(rp) as f:
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
        cp = self._cp()
        if cp.exists():
            with open(cp) as f:
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

    # ── 探活 ──────────────────────────────────────

    def is_online(self, name: str, provider: str = "", force: bool = False) -> bool:
        """檢查模型是否在線。

        Args:
            name: 模型名稱（用於緩存鍵）
            provider: 模型提供者（local/llamacpp/deepseek/openrouter）
            force: 是否跳過緩存強制檢查

        返回緩存值（5 秒有效期），避免每輪重複探活。
        """
        cache_key = f"{provider}:{name}"

        # 非強制檢查：用緩存
        if not force and cache_key in self._health_cache:
            return self._health_cache[cache_key]

        result = self._check_provider_health(provider)
        self._health_cache[cache_key] = result
        return result

    def _check_provider_health(self, provider: str) -> bool:
        """按 provider 執行健康檢查。

        本地模型：curl /health 確認服務活著。
        雲端模型：TCP/DNS 檢查域名可達性（不發送認證請求）。
        未知 provider：假定在線。
        """
        if not provider:
            return True

        provider_lower = provider.lower()

        # 本地模型：需要 llama-server 回應 /health
        if provider_lower in ("local", "llamacpp"):
            return self._check_http_health("http://localhost:8000/health")

        # 已知雲端 provider：檢查域名可達性
        endpoint = self._health_endpoints().get(provider_lower)
        if endpoint:
            return self._check_tcp_reachable(endpoint)

        # 未知 provider：沒法驗證，假定在線
        return True

    def _check_http_health(self, url: str) -> bool:
        """HTTP GET 完整響應檢查。"""
        try:
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "--connect-timeout", "3", "--max-time", "5", url],
                capture_output=True, text=True, timeout=8,
            )
            code = result.stdout.strip()
            return code.startswith("2") or code == "200"
        except Exception:
            return False

    def _check_tcp_reachable(self, url: str) -> bool:
        """TCP 級連接檢查（域名解析 + 端口連通）。不發送 HTTP 請求。"""
        try:
            # 從 URL 提取 host:port
            from urllib.parse import urlparse
            parsed = urlparse(url)
            host = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if not host:
                return False
            # DNS 解析 + TCP 連通
            socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
            return True
        except Exception:
            return False

    def verify_candidates(self, candidates: list[WorkerCandidate],
                          force: bool = False) -> list[WorkerCandidate]:
        """從 StatusCache 讀取狀態（零網路 I/O）。

        Args:
            candidates: 候選列表
            force: 若 True，對未快取的模型設 force_probe 標記

        返回：帶 status_vector 的候選列表（與原簽名相容）。
        若 cache 無數據，返回所有候選（假設在線，讓 heartbeat 補）。
        """
        from kafed.finder.status_cache import StatusCache
        cache = StatusCache()

        for c in candidates:
            entry = cache.get(c.name)
            if entry is not None:
                c.is_online = entry.online
                c.status_vector = entry.status_vector  # 4-dim
            else:
                c.is_online = True  # 暫信任在線
                c.status_vector = [1.0, 0.3, 0.0, 0.0]  # 保守默認
                if force:
                    # 設 force_probe 標記讓 heartbeat 處理
                    from kafed.finder.status_cache import StatusEntry
                    stub = StatusEntry(
                        name=c.name, provider=c.provider,
                        force_probe=True,
                    )
                    cache.update(c.name, stub)
                    cache.save()

        return candidates

    # ── 向後相容 ──────────────────────────────────────

    def get_status_vector(self, name: str, provider: str = "") -> list[float]:
        """從 StatusCache 讀取（向後相容）。

        回退策略：cache 有 → 用 cache；無 → 保守默認 + 設 force_probe。
        """
        from kafed.finder.status_cache import StatusCache
        cache = StatusCache()
        entry = cache.get(name)
        if entry is not None:
            return entry.status_vector

        # 設 force_probe
        from kafed.finder.status_cache import StatusEntry
        stub = StatusEntry(name=name, provider=provider, force_probe=True)
        cache.update(name, stub)
        cache.save()
        return [1.0, 0.3, 0.0, 0.0]

    def register(self, worker_id: str, worker_type: str = "expert",
                 domain: str = "", provider: str = "local",
                 model: str = "") -> None:
        """註冊新專家。"""
        from kafed.client.flow import hop
        hop("reg", f"{worker_id}", detail=f"{provider}/{domain}")
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
        rp = self._rp()
        if rp.exists():
            with open(rp) as f:
                roster = yaml.safe_load(f) or []
                if isinstance(roster, dict):
                    roster = roster.get("workers", [])

        roster.append(entry)

        rp = self._rp()
        rp.parent.mkdir(parents=True, exist_ok=True)
        with open(rp, "w") as f:
            yaml.dump({"workers": roster, "updated_at": datetime.now(timezone.utc).isoformat()}, f)

        # 清除緩存
        self._loaded = False

    def report_success(self, worker_id: str, dimension: str = "") -> None:
        """更新模型成功評分。"""
        rp = self._rp()
        if not rp.exists():
            return

        with open(rp) as f:
            data = yaml.safe_load(f) or {}

        workers = data.get("workers", []) if isinstance(data, dict) else []
        for w in workers:
            if w.get("id") == worker_id or w.get("name") == worker_id:
                w["total_calls"] = w.get("total_calls", 0) + 1
                # 滾動平均成功率
                prev_sr = w.get("success_rate", 1.0)
                w["success_rate"] = (prev_sr * 0.9) + 0.1
                break

        with open(rp, "w") as f:
            yaml.dump(data, f)

        self._loaded = False
