"""
KAFED Finder — 心跳探測器（Heartbeat）。

單次探測邏輯，供 cron（每 30s）調用。

每次 tick：
  1. 載入 StatusCache
  2. 遍歷已註冊模型，篩出需 probe 的（need_probe）
  3. 對每個需 probe 的模型執行探測
  4. 更新 StatusCache + 寫入 pickle

探測方法：
  本地模型：curl /health + 短 completion 測 TPS + psutil CPU/Mem
  雲端模型：TCP 可達性 + 歷史 TPS 經驗值

Router 同步模式：
  verify_candidates 設 force_probe=True → heartbeat 下次 tick 強制 probe
"""

from __future__ import annotations

import json
import subprocess
import time
from typing import Optional

from kafed.finder.status_cache import StatusCache, StatusEntry, compute_freshness
from kafed.finder.registry import Registry


class Heartbeat:
    """心跳探測器。"""

    def __init__(self):
        self._cache = StatusCache()
        self._registry = Registry()

    # ══════════════════════════════════════════════
    # 主入口
    # ══════════════════════════════════════════════

    def tick(self, threshold: Optional[float] = None) -> int:
        """執行一次探測循環。

        Args:
            threshold: 新鮮度閾值（低於此值觸發 probe，None=用 config）

        Returns:
            實際 probe 的模型數
        """
        from kafed.config import get_config
        cfg = get_config()
        if threshold is None:
            threshold = cfg.heartbeat_freshness_threshold

        # 獲取所有已註冊模型
        workers = self._registry.load()
        worker_names = {w.name for w in workers}

        probed = 0
        for name in worker_names:
            if self._cache.need_probe(name, threshold=threshold):
                worker = next((w for w in workers if w.name == name), None)
                provider = worker.provider if worker else "local"
                entry = self._probe_one(name, provider)
                self._cache.mark_probe_done(name, entry)
                probed += 1

        self._cache.save()
        return probed

    # ══════════════════════════════════════════════
    # 單個模型探測
    # ══════════════════════════════════════════════

    def _probe_one(self, name: str, provider: str) -> StatusEntry:
        """探測一個模型並返回 StatusEntry。"""
        online = False
        tps = 0.0
        load = 0.0
        latency_ms = 0.0

        if provider in ("local", "llamacpp"):
            result = self._probe_local(name)
            online = result["online"]
            tps = result["tps"]
            latency_ms = result["latency_ms"]
            load = self._estimate_local_load()
        else:
            result = self._probe_cloud(provider)
            online = result["online"]
            latency_ms = result["latency_ms"]
            # 雲端 TPS 用歷史經驗值估算
            tps = self._estimate_cloud_tps(provider)

        decoy = 0.05 if provider in ("local", "llamacpp") else 0.01
        return StatusEntry(
            online=online, tps=tps, load=load,
            latency_ms=latency_ms,
            last_probe_at=time.time(),
            freshness=1.0,
            decay_rate=decoy,
            provider=provider,
            name=name, model_id=name,
        )

    # ══════════════════════════════════════════════
    # 本地模型探測
    # ══════════════════════════════════════════════

    def _probe_local(self, name: str) -> dict:
        """本地 llama-server 探測：health + TPS 抽樣。

        TPS 使用 /v1/completions 發一個短請求計時。
        失敗時返回 0。
        """
        start = time.time()
        online = False
        tps = 0.0

        # Step 1: health check
        try:
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "--connect-timeout", "2", "--max-time", "3",
                 "http://localhost:8000/health"],
                capture_output=True, text=True, timeout=5,
            )
            online = r.stdout.strip().startswith("2")
        except Exception:
            online = False

        if not online:
            elapsed = (time.time() - start) * 1000
            return {"online": False, "tps": 0.0, "latency_ms": elapsed}

        # Step 2: short TPS test (dummy completion)
        try:
            payload = json.dumps({
                "prompt": "Hello", "max_tokens": 10,
                "temperature": 0, "n_predict": 10,
                "stream": False,
            })
            r2 = subprocess.run(
                ["curl", "-s", "--connect-timeout", "3", "--max-time", "8",
                 "-X", "POST", "http://localhost:8000/v1/completions",
                 "-H", "Content-Type: application/json",
                 "-d", payload],
                capture_output=True, text=True, timeout=10,
            )
            if r2.returncode == 0:
                data = json.loads(r2.stdout) if r2.stdout else {}
                usage = data.get("usage", {}) or {}
                # llama.cpp returns: completion_tokens or tokens_generated
                tokens = usage.get("completion_tokens", 0) or data.get("tokens_generated", 0) or 10
                elapsed = (time.time() - start) * 1000
                elapsed_s = (time.time() - start) or 0.001
                tps = tokens / elapsed_s
        except Exception:
            pass

        elapsed = (time.time() - start) * 1000
        return {"online": True, "tps": round(tps, 1), "latency_ms": round(elapsed, 1)}

    @staticmethod
    def _estimate_local_load() -> float:
        """本地負載估算：CPU + Memory 佔用。

        使用 psutil（Hermes venv 已有），失敗時返回 0.0。
        """
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0) / 100.0
            mem = psutil.virtual_memory().percent / 100.0
            # 加權：CPU 0.6 + Mem 0.4
            return round(cpu * 0.6 + mem * 0.4, 4)
        except ImportError:
            return 0.0

    # ══════════════════════════════════════════════
    # 雲端模型探測
    # ══════════════════════════════════════════════

    def _probe_cloud(self, provider: str) -> dict:
        """雲端 provider 探測：TCP 可達性 + RTT。

        不發送認證請求（避免消耗計費 API call）。
        """
        start = time.time()
        try:
            endpoint = self._registry._health_endpoints().get(provider)
            if not endpoint:
                return {"online": True, "latency_ms": 0.0, "tps": 0.0}

            from urllib.parse import urlparse
            parsed = urlparse(endpoint)
            host = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme == "https" else 80)

            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((host, port))
            sock.close()
            online = True
        except Exception:
            online = False

        elapsed = (time.time() - start) * 1000
        return {"online": online, "latency_ms": round(elapsed, 1), "tps": 0.0}

    @staticmethod
    def _estimate_cloud_tps(provider: str) -> float:
        """雲端模型 TPS 經驗值。"""
        known = {
            "deepseek": 120,
            "anthropic": 80,
            "openai": 100,
            "openrouter": 60,
        }
        return float(known.get(provider, 50))


# ── Cron 入口 ──────────────────────────────────


def run_tick():
    """供 cron 調用的單次探測入口。"""
    hb = Heartbeat()
    n = hb.tick()
    print(f"heartbeat: {n} models probed")


def force_probe(name: str, provider: str = "local"):
    """Router 同步觸發：強制探測一個模型。"""
    hb = Heartbeat()
    entry = hb._probe_one(name, provider)
    hb._cache.update(name, entry)
    hb._cache.mark_probe_done(name, entry)
    hb._cache.save()
    vec = entry.status_vector
    print(f"force_probe {name}: online={entry.online} "
          f"tps={entry.tps} load={entry.load} latency={entry.latency_ms}ms "
          f"vector={vec}")
    return vec
