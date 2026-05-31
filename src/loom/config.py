"""LOOM 全局統一配置。

設計原則：
  1. 所有路徑、文件名、閾值、權重集中於此——子模塊不自行定義
  2. 敏感信息（API Key、Token）由 LoomSecrets 管理，不出現在 show() 中
  3. 優先級：環境變量 > YAML 配置文件 > 代碼默認值
  4. 搜索路徑：$LOOM_CONFIG_FILE → ./loom.yaml → ~/.loom/loom.yaml → /etc/loom/loom.yaml
  5. 零硬編碼——所有默認路徑以 ~/.loom/ 為基線

使用：
    from loom.config import get_config, get_secrets
    cfg = get_config()
    secrets = get_secrets()
    print(cfg.show())        # 完整配置（密鑰顯示為 [REDACTED]）
    print(secrets.list_keys())  # 列出已設置的密鑰名（不顯示值）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── 路徑常數（均為默認值，可被環境變量/YAML 覆蓋） ───────
_HOME = Path.home()
_DEFAULT_DATA = _HOME / ".loom" / "data"


# ── 配置文件搜索 ────────────────────────────────

def _find_config_file() -> Path | None:
    """依優先級查找 loom.yaml。"""
    candidates = [
        os.getenv("LOOM_CONFIG_FILE"),
        str(Path.cwd() / "loom.yaml"),
        str(_HOME / ".loom" / "loom.yaml"),
        "/etc/loom/loom.yaml",
    ]
    for c in candidates:
        if c:
            p = Path(c)
            if p.exists():
                return p
    return None


def _load_yaml(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _yaml_val(data: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if isinstance(data, dict):
            data = data.get(k, {})
        else:
            return default
    return data if data != {} else default


# ══════════════════════════════════════════════════
# LoomSecrets — 敏感信息（密鑰/Token），不出現在 show() 中
# ══════════════════════════════════════════════════

class LoomSecrets:
    """LOOM 敏感信息訪問層。

    從 .env 或環境變量讀取 API Key、Token 等。
    永不寫入日誌、永不出現在 show() 中、永不作為配置值存儲。

    .env 文件搜索順序：
      1. $LOOM_ENV_FILE 環境變量
      2. 當前工作目錄下的 .env
      3. ~/.loom/.env
    """

    _REDACTED = "[REDACTED]"

    def __init__(self) -> None:
        self._loaded = False
        self._keys: dict[str, str] = {}

    def _lazy_load(self) -> None:
        if self._loaded:
            return
        # 手動加載 .env（不依賴 python-dotenv，減少依賴）
        env_paths = [
            os.getenv("LOOM_ENV_FILE"),
            str(Path.cwd() / ".env"),
            str(_HOME / ".loom" / ".env"),
        ]
        for ep in env_paths:
            if ep:
                p = Path(ep)
                if p.exists():
                    for line in p.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            self._keys[k.strip()] = v.strip().strip("\"'")
        self._loaded = True

    def _get_env(self, key: str) -> str | None:
        """先查環境變量，再查 .env。"""
        env_val = os.getenv(key)
        if env_val:
            return env_val
        self._lazy_load()
        return self._keys.get(key)

    # ── 公開密鑰接口 ──────────────────────────────
    # 每新增一個 API provider，在此添加對應的 property

    @property
    def deepseek_api_key(self) -> str | None:
        return self._get_env("DEEPSEEK_API_KEY")

    @property
    def openai_api_key(self) -> str | None:
        return self._get_env("OPENAI_API_KEY")

    @property
    def anthropic_api_key(self) -> str | None:
        return self._get_env("ANTHROPIC_API_KEY")

    def list_keys(self) -> list[str]:
        """列出所有已配置的密鑰名（不顯示值）。"""
        return [k for k in ["deepseek", "openai", "anthropic"]
                if getattr(self, f"{k}_api_key") is not None]


# ══════════════════════════════════════════════════
# LoomConfig — 非敏感配置
# ══════════════════════════════════════════════════


@dataclass
class LoomConfig:
    """LOOM 非敏感應用配置。

    敏感信息請用 LoomSecrets。
    """

    _yaml_data: dict[str, Any] = field(default_factory=lambda: _load_yaml(_find_config_file()))

    # ── 路徑輔助 ──────────────────────────────────

    def _env_or_yaml(self, env: str, yaml_keys: tuple[str, ...],
                     default: Any) -> Any:
        env_val = os.getenv(env)
        if env_val is not None:
            return env_val
        yml = _yaml_val(self._yaml_data, *yaml_keys)
        if yml is not None:
            return yml
        return default

    def _path(self, env: str, yaml_keys: tuple[str, ...], default: str) -> Path:
        val = self._env_or_yaml(env, yaml_keys, None)
        if val:
            return Path(str(val)).expanduser()
        return Path(default).expanduser()

    def _int(self, env: str, yaml_keys: tuple[str, ...], default: int) -> int:
        val = self._env_or_yaml(env, yaml_keys, None)
        if val is not None:
            return int(val)
        return default

    def _float(self, env: str, yaml_keys: tuple[str, ...], default: float) -> float:
        val = self._env_or_yaml(env, yaml_keys, None)
        if val is not None:
            return float(val)
        return default

    def _str(self, env: str, yaml_keys: tuple[str, ...], default: str) -> str:
        return str(self._env_or_yaml(env, yaml_keys, default))

    def _list(self, yaml_keys: tuple[str, ...], default: list) -> list:
        yml = _yaml_val(self._yaml_data, *yaml_keys)
        if yml and isinstance(yml, list):
            return yml
        return default

    def _dict(self, yaml_keys: tuple[str, ...], default: dict) -> dict:
        yml = _yaml_val(self._yaml_data, *yaml_keys)
        if yml and isinstance(yml, dict):
            return yml
        return default

    # ══════════════════════════════════════════════
    # 路徑屬性
    # ══════════════════════════════════════════════

    @property
    def data_dir(self) -> Path:
        return self._path("LOOM_DATA_DIR", ("data_dir",), str(_DEFAULT_DATA))

    @property
    def chroma_path(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def feedback_dir(self) -> Path:
        return self.data_dir / "feedback_logs"

    @property
    def kpak_dir(self) -> Path:
        return self.data_dir / "kpak"

    # Finder 路徑
    @property
    def roster_path(self) -> Path:
        """[已棄用] roster.yaml 已由向量空間取代。保留僅為向後兼容。"""
        return self._path("LOOM_ROSTER_PATH", ("finder", "roster_path"),
                          str(_HOME / ".loom" / "roster.yaml"))

    @property
    def vectors_path(self) -> Path:
        return self._path("LOOM_VECTORS_PATH", ("finder", "vectors_path"),
                          str(_HOME / ".loom" / "worker_vectors.pkl"))

    @property
    def context_dir(self) -> Path:
        return self._path("LOOM_CONTEXT_DIR", ("finder", "context_dir"),
                          str(_HOME / ".loom" / "finder_context"))

    @property
    def status_cache_path(self) -> Path:
        return self._path("LOOM_STATUS_CACHE", ("finder", "status_cache"),
                          str(_HOME / ".loom" / "status_cache.pkl"))

    @property
    def config_path(self) -> Path:
        return self._path("LOOM_CONFIG_PATH", ("config_path",),
                          str(_HOME / ".hermes" / "config.yaml"))

    # Backlog
    @property
    def backlog_data(self) -> Path:
        return self._path("LOOM_BACKLOG_DATA", ("backlog_data",),
                          str(_HOME / ".hermes" / "data" / "backlog.json"))

    @property
    def backlog_script(self) -> Path:
        return self._path("LOOM_BACKLOG_SCRIPT", ("backlog_script",),
                          str(Path(__file__).resolve().parent.parent.parent / "scripts" / "backlog.py"))

    # 文件名（集中管理，避免子模塊各自定義）
    @property
    def centroids_filename(self) -> str:
        return self._str("LOOM_CENTROIDS_FILENAME", ("filenames", "centroids"), "centroids.json")

    @property
    def labels_filename(self) -> str:
        return self._str("LOOM_LABELS_FILENAME", ("filenames", "labels"), "classification_labels.jsonl")

    @property
    def event_state_filename(self) -> str:
        return self._str("LOOM_EVENT_STATE_FILENAME", ("filenames", "event_state"), "event_state.json")

    @property
    def context_buffer_filename(self) -> str:
        return self._str("LOOM_CONTEXT_BUFFER_FILENAME", ("filenames", "context_buffer"), "context_buffer.jsonl")

    @property
    def seed_patterns_path(self) -> Path | None:
        val = self._env_or_yaml("LOOM_SEED_PATTERNS_PATH", ("classify", "seed_patterns_path"), None)
        if val:
            return Path(str(val)).expanduser()
        return None

    # ══════════════════════════════════════════════
    # 數值屬性
    # ══════════════════════════════════════════════

    # Embedding
    @property
    def embedding_model(self) -> str:
        return self._str("LOOM_EMBEDDING_MODEL", ("embedding", "model"), "BAAI/bge-small-en-v1.5")

    @property
    def embedding_dim(self) -> int:
        return self._int("LOOM_EMBEDDING_DIM", ("embedding", "dim"), 384)

    # Chroma
    @property
    def chroma_collection(self) -> str:
        return self._str("LOOM_CHROMA_COLLECTION", ("chroma", "collection"), "loom_knowledge")

    # Chunker
    @property
    def chunk_max_chars(self) -> int:
        return self._int("LOOM_CHUNK_MAX_CHARS", ("chunker", "max_chars"), 500)

    @property
    def chunk_overlap(self) -> int:
        return self._int("LOOM_CHUNK_OVERLAP", ("chunker", "overlap"), 50)

    # Retrieval
    @property
    def top_k_default(self) -> int:
        return self._int("LOOM_TOP_K_DEFAULT", ("retrieval", "top_k"), 5)

    # Flywheel
    @property
    def e1_thresholds(self) -> str:
        return self._str("LOOM_E1_THRESHOLDS", ("flywheel", "e1_thresholds"), "10,50,100,200,500,1000")

    @property
    def e2_drift_min(self) -> float:
        return self._float("LOOM_E2_DRIFT_MIN", ("flywheel", "e2_drift_min"), 0.05)

    @property
    def e3_min_entries(self) -> int:
        return self._int("LOOM_E3_MIN_ENTRIES", ("flywheel", "e3_min_entries"), 200)

    @property
    def e3_repack_growth_pct(self) -> float:
        return self._float("LOOM_E3_REPACK_GROWTH", ("flywheel", "e3_repack_growth"), 30.0)

    @property
    def e4_dedup_threshold(self) -> float:
        return self._float("LOOM_E4_DEDUP_THRESHOLD", ("flywheel", "e4_dedup_threshold"), 0.95)

    @property
    def e5_stale_days(self) -> int:
        return self._int("LOOM_E5_STALE_DAYS", ("flywheel", "e5_stale_days"), 90)

    # Finder
    @property
    def fast_route_max_workers(self) -> int:
        return self._int("LOOM_FAST_ROUTE_MAX_WORKERS", ("finder", "fast_route_max_workers"), 3)

    @property
    def finder_w_cap(self) -> float:
        return self._float("LOOM_FINDER_W_CAP", ("finder", "w_cap"), 0.5)

    @property
    def finder_w_ctx(self) -> float:
        return self._float("LOOM_FINDER_W_CTX", ("finder", "w_ctx"), 0.3)

    @property
    def finder_w_sta(self) -> float:
        return self._float("LOOM_FINDER_W_STA", ("finder", "w_sta"), 0.2)

    # Heartbeat
    @property
    def heartbeat_base_local(self) -> float:
        return self._float("LOOM_HEARTBEAT_BASE_LOCAL", ("finder", "heartbeat_base_local"), 10.0)

    @property
    def heartbeat_base_cloud(self) -> float:
        return self._float("LOOM_HEARTBEAT_BASE_CLOUD", ("finder", "heartbeat_base_cloud"), 60.0)

    @property
    def heartbeat_max_local(self) -> float:
        return self._float("LOOM_HEARTBEAT_MAX_LOCAL", ("finder", "heartbeat_max_local"), 120.0)

    @property
    def heartbeat_max_cloud(self) -> float:
        return self._float("LOOM_HEARTBEAT_MAX_CLOUD", ("finder", "heartbeat_max_cloud"), 600.0)

    @property
    def heartbeat_freshness_threshold(self) -> float:
        return self._float("LOOM_HEARTBEAT_FRESHNESS_THRESHOLD", ("finder", "freshness_threshold"), 0.3)

    @property
    def heartbeat_cron_name(self) -> str:
        return "loom-heartbeat"

    @property
    def llama_base_url(self) -> str:
        """llama-server 基礎 URL（可通過 LOOM_LLAMA_BASE_URL 或 YAML llama_server.base_url 覆寫）。"""
        return self._str("LOOM_LLAMA_BASE_URL", ("llama_server", "base_url"),
                         "http://localhost:8000")

    @property
    def context_buffer_size(self) -> int:
        return self._int("LOOM_CONTEXT_BUFFER_SIZE", ("finder", "context_buffer_size"), 500)

    @property
    def context_boost_amount(self) -> float:
        return self._float("LOOM_CONTEXT_BOOST", ("finder", "context_boost"), 0.15)

    # Server
    @property
    def host(self) -> str:
        return self._str("LOOM_HOST", ("server", "host"), "0.0.0.0")

    @property
    def port(self) -> int:
        return self._int("LOOM_PORT", ("server", "port"), 8765)

    # 雲端模型池 & 探活端點
    @property
    def cloud_models(self) -> list[dict]:
        return self._list(("cloud_models",), [
            {"name": "deepseek-v4-flash", "provider": "deepseek",
             "is_free": False, "cost": 0.00014, "cost_output": 0.00028,
             "context_window": 65536,
             "supports_reasoning": True, "supports_vision": False,
             "supports_functions": True, "temperature": 0.0,
             "tags": ["reasoning", "coding", "fast"]},
            {"name": "deepseek-v4-pro", "provider": "deepseek",
             "is_free": False, "cost": 0.00174, "cost_output": 0.00348,
             "context_window": 65536,
             "supports_reasoning": True, "supports_vision": False,
             "supports_functions": True, "temperature": 0.6,
             "tags": ["reasoning", "deep"]},
            {"name": "claude-sonnet-4", "provider": "anthropic",
             "is_free": False, "cost": 0.003, "cost_output": 0.015,
             "context_window": 200000,
             "supports_reasoning": True, "supports_vision": True,
             "supports_functions": True, "temperature": 0.6,
             "tags": ["reasoning", "analysis", "long_context"]},
            {"name": "gpt-4o", "provider": "openai",
             "is_free": False, "cost": 0.0025, "cost_output": 0.010,
             "context_window": 128000,
             "supports_reasoning": False, "supports_vision": True,
             "supports_functions": True, "temperature": 0.6,
             "tags": ["reasoning", "vision", "general"]},
        ])

    @property
    def health_endpoints(self) -> dict[str, str]:
        return self._dict(("health_endpoints",), {
            "local": "http://localhost:8000/health",
            "llamacpp": "http://localhost:8000/health",
            "deepseek": "https://api.deepseek.com/v1",
            "openrouter": "https://openrouter.ai/api/v1/models",
        })

    @property
    def pulse_check_script(self) -> Path:
        return self._path("LOOM_PULSE_CHECK_SCRIPT", ("pulse_check_script",),
                          str(_HOME / ".loom" / "bin" / "pulse-check.py"))

    # ══════════════════════════════════════════════
    # show()
    # ══════════════════════════════════════════════

    def show(self, show_secrets: bool = False) -> str:
        """返回完整配置。默認不顯示密鑰。"""
        lines = ["= LOOM 配置總覽 =", ""]
        lines.append("── 路徑 ──")
        lines.append(f"  data_dir:     {self.data_dir}")
        lines.append(f"  roster:       {self.roster_path}")
        lines.append(f"  vectors:      {self.vectors_path}")
        lines.append(f"  context:      {self.context_dir}")
        lines.append(f"  config:       {self.config_path}")
        lines.append(f"  backlog:      {self.backlog_data}")
        lines.append("")
        lines.append("── 文件名 ──")
        lines.append(f"  centroids:    {self.centroids_filename}")
        lines.append(f"  labels:       {self.labels_filename}")
        lines.append(f"  event_state:  {self.event_state_filename}")
        lines.append(f"  ctx_buffer:   {self.context_buffer_filename}")
        lines.append("")
        lines.append("── 嵌入 ──")
        lines.append(f"  model:        {self.embedding_model}")
        lines.append(f"  dim:          {self.embedding_dim}")
        lines.append("")
        lines.append("── Chroma/分塊/檢索 ──")
        lines.append(f"  collection:   {self.chroma_collection}")
        lines.append(f"  max_chars:    {self.chunk_max_chars}")
        lines.append(f"  overlap:      {self.chunk_overlap}")
        lines.append(f"  top_k:        {self.top_k_default}")
        lines.append("")
        lines.append("── Finder ──")
        lines.append(f"  fast_route:   <= {self.fast_route_max_workers} workers")
        lines.append(f"  w_cap/ctx/sta: {self.finder_w_cap} / {self.finder_w_ctx} / {self.finder_w_sta}")
        lines.append(f"  ctx_buffer:   {self.context_buffer_size}")
        lines.append(f"  ctx_boost:    {self.context_boost_amount}")
        lines.append(f"  cloud_models: {len(self.cloud_models)}")
        lines.append(f"  endpoints:    {len(self.health_endpoints)}")
        lines.append("")
        lines.append("── Heartbeat ──")
        lines.append(f"  local base:   {self.heartbeat_base_local}s")
        lines.append(f"  cloud base:   {self.heartbeat_base_cloud}s")
        lines.append(f"  local max:    {self.heartbeat_max_local}s")
        lines.append(f"  cloud max:    {self.heartbeat_max_cloud}s")
        lines.append(f"  freshness:    < {self.heartbeat_freshness_threshold}")
        lines.append("")
        lines.append("── 飛輪事件 ──")
        lines.append(f"  E1:           {self.e1_thresholds}")
        lines.append(f"  E2 drift:     >={self.e2_drift_min}")
        lines.append(f"  E3 growth:    >={self.e3_repack_growth_pct}%")
        lines.append(f"  E4 dedup:     >={self.e4_dedup_threshold}")
        lines.append(f"  E5 stale:     >={self.e5_stale_days}d")
        lines.append("")
        lines.append("── 服務 ──")
        lines.append(f"  host:port:    {self.host}:{self.port}")
        lines.append("")
        lines.append("── 密鑰 ──")
        secrets = get_secrets()
        keys = secrets.list_keys()
        if keys:
            for k in keys:
                v = secrets._get_env(f"{k.upper()}_API_KEY")
                masked = v[:4] + "****" + v[-4:] if v and len(v) > 12 else "[REDACTED]"
                lines.append(f"  {k:12s}  {masked}")
        else:
            lines.append("  (無已配置密鑰)")
        if not show_secrets:
            lines.append("  (使用 show_secrets=True 查看完整值)")
        return "\n".join(lines)


# ══════════════════════════════════════════════════
# 全局單例
# ══════════════════════════════════════════════════

_config: LoomConfig | None = None
_secrets: LoomSecrets | None = None


def get_config() -> LoomConfig:
    global _config
    if _config is None:
        _config = LoomConfig()
        cfg = _config
        for d in [cfg.chroma_path, cfg.feedback_dir, cfg.kpak_dir,
                  cfg.context_dir]:
            d.mkdir(parents=True, exist_ok=True)
    return _config


def get_secrets() -> LoomSecrets:
    global _secrets
    if _secrets is None:
        _secrets = LoomSecrets()
    return _secrets
