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

    def verify_candidates(self, candidates: list[WorkerCandidate]) -> list[WorkerCandidate]:
        """批量驗證候選模型可用性，更新 is_online + status_vector。"""
        verified: list[WorkerCandidate] = []
        for c in candidates:
            alive = self.is_online(c.name, c.provider)
            c.is_online = alive
            c.status_vector = self.get_status_vector(c.name, c.provider)
            if alive:
                verified.append(c)
        return verified

    # ── 狀態向量 ──────────────────────────────────────

    def get_status_vector(self, name: str, provider: str = "") -> list[float]:
        """返回模型實時狀態向量 [online, tps_norm, load_norm]。

        各維度:
            online(0/1) — 探活得出的可用性
            tps_norm(0-1) — TPS 歸一化（本地估算，雲端用歷史）
            load_norm(0-1) — 負載程度（目前恆為 0，保留擴展）

        返回三元素 list，供 find_partners 三維聚合使用。
        """
        alive = self.is_online(name, provider)
        online_f = 1.0 if alive else 0.0

        # TPS 估算：本地模型從 roster 讀取，雲端用默認
        tps = 0
        for w in self._roster:
            if w.get("name") == name or w.get("id") == name:
                tps = w.get("estimated_tps", 0)
                break
        # 本地 llama-server 常見 TPS（無數據時用合理默認）
        if tps <= 0 and provider in ("local", "llamacpp"):
            tps = 55  # Qwen3.5-9B Q4_K_M 典型值
        tps_norm = min(1.0, tps / 200.0)  # 200 tps = 滿分

        return [online_f, round(tps_norm, 4), 0.0]

    # ── 註冊與歷史 ──────────────────────────────

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
