"""
LOOM Finder — 模型發現器（Explorer）。

掃描所有可用的模型配置源，解析完整元數據，生成多維向量空間。

設計哲學：
  - 單一發現入口：從 Hermes config.yaml 讀取所有 provider 配置
  - 本地/雲端由 base_url 自動判定（localhost → local, 否則 cloud）
  - 角色（role）從 Hermes config 各章節自動發現（auxiliary/tts/stt/fallback 等）
  - 每個模型標註所服務的全部角色，便於精確路由
  - 成本（cost_per_1M_input/output）使用真實 API 定價，單位為 $/1M tokens
  - 不再有獨立的 llama-server /v1/models 通道——llamacpp provider 的模型通過
    其 base_url 查詢 /v1/models 補全

成本策略：
  - 本地模型：cost=0
  - 雲端模型：從真實 API 定價表讀取精確值
  - 未知雲端模型：保守高估（$5/$15 per 1M tokens），確保路由不低估成本
"""

from __future__ import annotations

import json
import os
import pickle
import subprocess
from pathlib import Path
from typing import Any, Optional

import yaml

from loom.config import get_config
from loom.finder.matcher import (WorkerCandidate, MODEL_META_SCHEMA,
                                   meta_defaults, build_meta_description)


# ══════════════════════════════════════════════════
# 工具函數
# ══════════════════════════════════════════════════


def _is_local_url(url: str) -> bool:
    """從 base_url 判斷是否為本地模型。"""
    url_lower = url.lower()
    local_hosts = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
    return any(h in url_lower for h in local_hosts)


def _query_llama_models_list(base_url: str) -> list[str]:
    """向 llama-server /v1/models 查詢所有已加載的模型名列表。"""
    llm_url = f"{base_url.rstrip('/')}/v1/models"
    try:
        result = subprocess.run(
            ["curl", "-s", llm_url],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        data = json.loads(result.stdout) if result.stdout else {}
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except Exception:
        return []


def _parse_llama_args(args: list[str]) -> dict:
    """解析 llama-server 的 status.args → 元數據字典。"""
    meta = meta_defaults()
    key_map = {
        "ctx_size": "context_window",
        "alias": "name",
        "repeat_penalty": "repeat_penalty",
        "n_gpu_layers": None, "flash_attn": None,
        "model": None, "host": None, "port": None,
        "mmproj": None, "mmproj_auto": None,
        "jinja": None, "pooling": None,
    }
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            key = arg[2:].replace("-", "_")
            mapped = key_map.get(key, key)
            if mapped is None:
                i += 1
                continue
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                val = args[i + 1]
                i += 2
            else:
                val = "on"
                i += 1
            _set_schema_val(meta, mapped, val)
        else:
            i += 1
    return meta


def _set_schema_val(meta: dict, key: str, val: str):
    """按 schema 類型寫入 meta。"""
    schema_type = MODEL_META_SCHEMA.get(key, (None, None))[0]
    if schema_type is None:
        meta[key] = val
        return
    try:
        if schema_type == int:
            meta[key] = int(val)
        elif schema_type == float:
            meta[key] = float(val)
        elif schema_type == bool:
            meta[key] = val.lower() in ("on", "true", "yes", "1")
        else:
            meta[key] = val
    except (ValueError, TypeError):
        meta[key] = val


def _query_provider_models_api(base_url: str,
                                target_model: str = "") -> Optional[dict]:
    """查詢 provider 的 /v1/models 端點獲取模型元數據。"""
    if not base_url:
        return None
    api_url = base_url.rstrip("/") + "/models"
    try:
        result = subprocess.run(
            ["curl", "-s", "--connect-timeout", "5", "--max-time", "8", api_url],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        data = json.loads(result.stdout)
        models_data = data.get("data", []) if isinstance(data, dict) else []
        for m in models_data:
            mid = m.get("id", "")
            if target_model and mid != target_model:
                continue
            meta = {}
            for key in ("context_window", "max_tokens",
                        "supports_reasoning", "supports_vision",
                        "supports_functions", "supports_streaming"):
                val = m.get(key)
                if val is not None:
                    meta[key] = val
            desc = m.get("description", "") or m.get("metadata", {}).get("description", "")
            if desc:
                meta["description"] = desc
            if meta:
                return meta
        return None
    except Exception:
        return None


# ══════════════════════════════════════════════════
# 角色發現
# ══════════════════════════════════════════════════


def _discover_model_roles(hermes_data: dict) -> dict[str, list[dict]]:
    """掃描 Hermes config 各章節，發現每個模型所服務的角色。

    Returns: {model_name: [{"role": "vision", "provider": "...", ...}, ...]}
    """
    roles: dict[str, list[dict]] = {}

    def _add(model_name: str, provider: str, role_name: str,
             extra: Optional[dict] = None):
        if not model_name:
            return
        entry = {"role": role_name, "provider": provider}
        if extra:
            entry.update(extra)
        roles.setdefault(model_name, []).append(entry)

    # 1. model.default — 主代理模型
    model_sec = hermes_data.get("model", {})
    default_model = model_sec.get("default", "")
    model_provider = model_sec.get("provider", "")
    if default_model:
        _add(default_model, model_provider, "default")

    # 2. fallback_model
    fb = hermes_data.get("fallback_model", {})
    fb_model = fb.get("model", "")
    fb_provider = fb.get("provider", "")
    if fb_model:
        _add(fb_model, fb_provider, "fallback")

    # 3. auxiliary.* — 每個子章節是一個角色
    aux = hermes_data.get("auxiliary", {})
    if isinstance(aux, dict):
        for role_name, role_cfg in aux.items():
            if not isinstance(role_cfg, dict):
                continue
            m = role_cfg.get("model", "")
            p = role_cfg.get("provider", "")
            if m:
                _add(m, p, role_name, {
                    "base_url": role_cfg.get("base_url", ""),
                    "timeout": role_cfg.get("timeout", 30),
                })

    # 4. tts.* — 語音合成
    tts = hermes_data.get("tts", {})
    if isinstance(tts, dict):
        for prov_name, tts_cfg in tts.items():
            if not isinstance(tts_cfg, dict):
                continue
            m = tts_cfg.get("model", "") or tts_cfg.get("model_id", "")
            if m:
                _add(m, prov_name, "tts")

    # 5. stt.* — 語音識別
    stt = hermes_data.get("stt", {})
    if isinstance(stt, dict):
        for prov_name, stt_cfg in stt.items():
            if not isinstance(stt_cfg, dict):
                continue
            m = stt_cfg.get("model", "") or stt_cfg.get("model_id", "")
            if m:
                _add(m, prov_name, "stt")

    return roles


# ══════════════════════════════════════════════════
# Explorer
# ══════════════════════════════════════════════════


class Explorer:
    """模型發現器——讀取 Hermes config，發現全部模型與角色。

    定價策略：
      - 本地模型: cost=0（由 PricingTable 返回）
      - 雲端模型: 從 PricingTable 緩存讀取（可被外部更新）
      - 未知模型: 保守默認值（$5/$15 per 1M tokens）
      - PricingTable 每次 scan 時自動從緩存文件加載最新定價
    """

    # ── 內置定價默認值（代碼的備份，不是主數據源）────
    _BUILTIN_PRICING: dict[str, dict[str, dict[str, float]]] = {
        "deepseek": {
            "deepseek-v4-flash": {"input": 0.14, "output": 0.28},
            "deepseek-v4-pro":   {"input": 1.74, "output": 3.48},
            "deepseek-chat":     {"input": 0.27, "output": 1.10},
            "deepseek-v3":       {"input": 0.27, "output": 1.10},
            "deepseek-reasoner": {"input": 0.55, "output": 2.19},
            "deepseek-r1":       {"input": 0.55, "output": 2.19},
        },
        "openai": {
            "gpt-4o":          {"input": 2.50, "output": 10.00},
            "gpt-4o-mini":     {"input": 0.15, "output": 0.60},
            "gpt-4":           {"input": 30.00, "output": 60.00},
            "gpt-4-turbo":     {"input": 10.00, "output": 30.00},
            "o1":              {"input": 15.00, "output": 60.00},
            "o3":              {"input": 10.00, "output": 40.00},
            "o4-mini":         {"input": 1.10, "output": 4.40},
            "gpt-4.1":         {"input": 2.00, "output": 8.00},
            "gpt-4.1-mini":    {"input": 0.40, "output": 1.60},
            "gpt-4.1-nano":    {"input": 0.10, "output": 0.40},
        },
        "anthropic": {
            "claude-sonnet-4": {"input": 3.00, "output": 15.00},
            "claude-haiku-3":  {"input": 0.25, "output": 1.25},
            "claude-opus-4":   {"input": 15.00, "output": 75.00},
        },
        "google": {
            "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
            "gemini-2.5-pro":   {"input": 1.25, "output": 5.00},
            "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
        },
        "nvidia": {
            "deepseek-ai/deepseek-v4-pro": {"input": 1.74, "output": 3.48},
        },
    }

    _DEFAULT_CLOUD_COST = {"input": 5.00, "output": 15.00}

    class PricingTable:
        """模型定價表——每次 scan 時從緩存文件加載。

        定價緩存文件: ~/.loom/pricing_cache.json

        優先級: 緩存文件 > 內置默認值 > 全局默認值
        """

        def __init__(self):
            self._cache: dict[str, dict[str, dict[str, float]]] = {}
            self._defaults: dict[str, dict[str, float]] = {}
            self._timestamp: float = 0.0
            self._load()

        # ── 文件路徑 ──

        @property
        def _cache_path(self) -> Path:
            return Explorer._get_pricing_cache_path()

        @staticmethod
        def default_path() -> Path:
            """定價緩存文件的默認路徑。"""
            return Path.home() / ".loom" / "pricing_cache.json"

        # ── 加載 / 保存 ──

        def _load(self):
            """從緩存文件加載定價數據。"""
            path = self._cache_path
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    self._cache = data.get("pricing", {})
                    self._defaults = data.get("defaults", {})
                    self._timestamp = data.get("updated_at", 0.0)
                except Exception:
                    pass

        def save(self):
            """寫回定價緩存文件。"""
            path = self._cache_path
            path.parent.mkdir(parents=True, exist_ok=True)
            import time
            data = {
                "pricing": self._cache,
                "defaults": self._defaults,
                "updated_at": time.time(),
                "source": "loom-explorer",
            }
            path.write_text(json.dumps(data, indent=2))

        # ── 價格查詢 ──

        def resolve(self, provider: str, model_name: str,
                     is_local: bool = False) -> dict:
            """查找模型定價。

            Args:
                provider: provider 名（如 deepseek、openai）
                model_name: 模型名
                is_local: 是否本地模型

            Returns:
                {"input": $/1M, "output": $/1M}
            """
            if is_local:
                return {"input": 0.0, "output": 0.0}

            # 1. 緩存文件（最新數據）
            cost = self._lookup(self._cache, provider, model_name)
            if cost:
                return cost

            # 2. 提供商默認值（緩存）
            prov_default = self._defaults.get(provider)
            if prov_default:
                return prov_default

            # 3. 內置默認值（代碼備份）
            cost = self._lookup(Explorer._BUILTIN_PRICING, provider, model_name)
            if cost:
                return cost

            # 4. 全局默認
            return dict(Explorer._DEFAULT_CLOUD_COST)

        @staticmethod
        def _lookup(table: dict, provider: str, model_name: str) -> Optional[dict]:
            """從一個定價表中查找（最長前綴匹配）。"""
            provider_table = table.get(provider, {})
            if not provider_table:
                return None
            model_lower = model_name.lower()
            best_prefix = ""
            best_cost = None
            for prefix, cost in provider_table.items():
                if model_lower.startswith(prefix) and len(prefix) > len(best_prefix):
                    best_prefix = prefix
                    best_cost = cost
            return best_cost

        # ── 更新接口 ──

        def set(self, provider: str, model_name: str,
                 input_cost: float, output_cost: float):
            """設置一個模型的定價。"""
            self._cache.setdefault(provider, {})[model_name] = {
                "input": input_cost, "output": output_cost,
            }

        def set_provider_default(self, provider: str,
                                   input_cost: float, output_cost: float):
            """設置提供商默認定價（當找不到具體模型時用此值）。"""
            self._defaults[provider] = {"input": input_cost, "output": output_cost}

        def remove(self, provider: str, model_name: str):
            """移除一個模型的定價（回到默認值）。"""
            if provider in self._cache and model_name in self._cache[provider]:
                del self._cache[provider][model_name]

        def all_prices(self) -> dict:
            """返回完整定價視圖（用於調試）。"""
            return {
                "cache": self._cache,
                "defaults": self._defaults,
                "builtin": {k: list(v.keys()) for k, v in Explorer._BUILTIN_PRICING.items()},
                "updated_at": self._timestamp,
            }

    @staticmethod
    def _get_pricing_cache_path() -> Path:
        """定價緩存文件路徑（可被 LOOM_PRICING_CACHE 環境變量覆蓋）。"""
        env = os.getenv("LOOM_PRICING_CACHE")
        if env:
            return Path(env).expanduser()
        return Path.home() / ".loom" / "pricing_cache.json"

    def __init__(self):
        self._cfg = get_config()

    @staticmethod
    def scan_all() -> list[WorkerCandidate]:
        """讀取 Hermes config.yaml，發現所有可用的模型。

        數據流：
          1. 讀取 Hermes config.yaml（直接文件讀取）
          2. 遍歷所有 provider
          3. 對 llamacpp provider，額外查 /v1/models 補全模型列表
          4. 對所有模型，查其 provider 的 /v1/models API 補全元數據
          5. 掃描 Hermes config 各章節（auxiliary/tts/stt/fallback），
             發現每個模型服務的角色，寫入 meta.roles + role_tags
          6. 本地/雲端由 base_url 自動判定
          7. 成本從精確定價表讀取，找不到時用保守默認值
        """
        workers: list[WorkerCandidate] = []
        seen: set[str] = set()

        hermes_data = Explorer._load_hermes_config()
        providers = hermes_data.get("providers", {})
        role_map = _discover_model_roles(hermes_data)

        # 加載定價表（每次 scan 從緩存文件讀取）
        pricing = Explorer.PricingTable()

        for prov_name, prov_cfg in providers.items():
            if not isinstance(prov_cfg, dict):
                continue

            base_url = prov_cfg.get("base_url", "")
            is_local = _is_local_url(base_url) or prov_name == "llamacpp"

            model_names = Explorer._get_model_names(prov_cfg, prov_name,
                                                     base_url, is_local)

            for model_name in model_names:
                if model_name in seen:
                    _merge_roles(workers, model_name, role_map)
                    continue
                seen.add(model_name)

                meta = meta_defaults()
                meta["name"] = model_name
                meta["provider"] = prov_name
                meta["model_id"] = model_name
                meta["provider_type"] = "local" if is_local else "cloud"
                meta["is_online"] = True

                # 成本：從 PricingTable 讀取（緩存 > 內置 > 默認）
                cost = pricing.resolve(prov_name, model_name, is_local)
                meta["cost_per_input_token"] = cost["input"]
                meta["cost_per_output_token"] = cost["output"]

                # 從 /v1/models API 補全元數據
                api_meta = _query_provider_models_api(base_url, model_name)
                if api_meta:
                    meta.update(api_meta)

                # 角色標註
                model_roles = role_map.get(model_name, [])
                if model_roles:
                    meta["roles"] = model_roles
                    role_names = sorted(set(r["role"] for r in model_roles))
                    meta["role_tags"] = ",".join(role_names)

                wc = WorkerCandidate(
                    name=model_name,
                    provider=prov_name,
                    model_id=model_name,
                    meta=meta,
                    is_online=True,
                    is_free=is_local,
                    match_score=0.5,
                    cost_per_token=meta.get("cost_per_input_token", 0.0),
                    capability_tags=Explorer._derive_tags(meta),
                )
                workers.append(wc)

        # 補全：有角色引用但未在 providers 模型中出現的
        unused_roles = _find_unreferenced_roles(role_map, seen)
        if unused_roles:
            Explorer._add_unreferenced_models(workers, seen, unused_roles,
                                               hermes_data, pricing)

        # 寫回定價緩存（scan 過程中可能發現新模型）
        pricing.save()

        return workers

    @staticmethod
    def _load_hermes_config() -> dict:
        """讀取 Hermes config.yaml。"""
        hermes_home = os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))
        candidates = [
            Path(hermes_home) / "config.yaml",
            Path(hermes_home) / "config.yml",
            Path.cwd() / "hermes.yaml",
            Path.cwd() / "hermes.yml",
        ]
        for c in candidates:
            if c.exists():
                try:
                    return yaml.safe_load(c.read_text()) or {}
                except Exception:
                    continue
        return {}

    @staticmethod
    def _get_model_names(prov_cfg: dict, prov_name: str,
                          base_url: str, is_local: bool) -> list[str]:
        """從 provider 配置中獲取模型名列表。"""
        models = []

        models_list = prov_cfg.get("models", [])
        for m in models_list:
            if isinstance(m, str):
                models.append(m)
            elif isinstance(m, dict):
                models.append(m.get("model", m.get("name", "")))

        if not models:
            single = prov_cfg.get("model", "")
            if single:
                models.append(single)

        # llamacpp — 查 /v1/models 補全
        if is_local and base_url:
            discovered = _query_llama_models_list(base_url)
            for d in discovered:
                if d not in models:
                    models.append(d)

        return [m for m in models if m]

    @staticmethod
    def _add_unreferenced_models(workers: list, seen: set,
                                  model_roles: dict, hermes_data: dict,
                                  pricing: 'Explorer.PricingTable' = None):
        """添加被角色引用但未在 providers 中發現的模型。"""
        if pricing is None:
            pricing = Explorer.PricingTable()
        for model_name, roles in model_roles.items():
            if model_name in seen:
                continue
            seen.add(model_name)
            meta = meta_defaults()
            meta["name"] = model_name
            meta["model_id"] = model_name
            meta["roles"] = roles
            meta["role_tags"] = ",".join(sorted(set(r["role"] for r in roles)))

            providers_set = set(r.get("provider", "") for r in roles)
            meta["provider"] = next(iter(providers_set), "unknown")
            is_local = any(
                _is_local_url(r.get("base_url", ""))
                for r in roles
            )
            meta["provider_type"] = "local" if is_local else "cloud"

            # 成本
            cost = pricing.resolve(
                meta["provider"], model_name, is_local)
            meta["cost_per_input_token"] = cost["input"]
            meta["cost_per_output_token"] = cost["output"]

            wc = WorkerCandidate(
                name=model_name,
                provider=meta["provider"],
                model_id=model_name,
                meta=meta,
                is_online=True,
                is_free=is_local,
                capability_tags=Explorer._derive_tags(meta),
            )
            workers.append(wc)

    @staticmethod
    def _derive_tags(meta: dict) -> list[str]:
        """從元數據推導能力標籤。"""
        tags = []
        if meta.get("supports_reasoning"):
            tags.append("reasoning")
        if meta.get("supports_vision"):
            tags.append("vision")
        if meta.get("supports_functions"):
            tags.append("functions")
        if meta.get("supports_streaming"):
            tags.append("streaming")
        if meta.get("tps", 0) > 100:
            tags.append("fast")
        if meta.get("context_window", 0) >= 32000:
            tags.append("long_context")
        if meta.get("provider_type") == "local":
            tags.append("local")

        role_tags_val = meta.get("role_tags", "")
        if role_tags_val:
            for r in role_tags_val.split(","):
                r = r.strip()
                if r and r not in tags:
                    tags.append(r)

        name = str(meta.get("name", "")).lower()
        if any(k in name for k in ("flash", "v4", "sonnet", "opus")):
            tags.append("flagship")
        if "mini" in name or "haiku" in name:
            tags.append("lightweight")
        if "embed" in name or name.startswith("bge-"):
            tags.append("embedding")

        return tags or ["general"]

    @staticmethod
    def update_vector_space(workers: list[WorkerCandidate]) -> None:
        """生成每個模型的多維能力向量（嵌入空間）。"""
        import numpy as np
        from loom.knowledge.rag.embedding import get_model
        model = get_model()
        vectors = {}
        for w in workers:
            desc = build_meta_description(w.meta)
            vec = model.encode([desc[:512]], show_progress_bar=False)[0]
            vectors[w.name] = np.array(vec, dtype=np.float32)

        vp = get_config().vectors_path
        vp.parent.mkdir(parents=True, exist_ok=True)
        with open(vp, "wb") as f:
            pickle.dump(vectors, f)


def _merge_roles(workers: list[WorkerCandidate], model_name: str,
                  role_map: dict[str, list[dict]]):
    """為已發現的模型補充角色信息。"""
    new_roles = role_map.get(model_name, [])
    if not new_roles:
        return
    for w in workers:
        if w.name == model_name:
            existing = w.meta.get("roles", [])
            existing_role_names = {r.get("role") for r in existing}
            for nr in new_roles:
                if nr.get("role") not in existing_role_names:
                    existing.append(nr)
            w.meta["roles"] = existing
            w.meta["role_tags"] = ",".join(
                sorted(set(r["role"] for r in existing)))
            w.capability_tags = Explorer._derive_tags(w.meta)
            break


def _find_unreferenced_roles(role_map: dict,
                               known_names: set[str]) -> dict[str, list[dict]]:
    """找出角色映射中有但已知模型列表中沒有的。"""
    return {k: v for k, v in role_map.items() if k not in known_names}


def scan(update_roster: bool = False) -> list[WorkerCandidate]:
    """探索所有可用模型。"""
    from loom.manager.shuttle import Shuttle as _Shuttle
    workers = Explorer.scan_all()
    chain("find/scan", [
        ("src", "hermes_config", ""),
        ("hit", f"{len(workers)} workers", ""),
    ], end="discovery=auto")
    for w in workers[:5]:
        print(f"  {w.describe()}")
        roles = w.meta.get("roles", [])
        role_names = [r["role"] for r in roles] if roles else []
        cost = (w.meta.get("cost_per_input_token", 0),
                w.meta.get("cost_per_output_token", 0))
        print(f"       provider={w.provider} type={w.meta.get('provider_type','?')} "
              f"cost=(${cost[0]:.4f}/${cost[1]:.4f}/1M) roles={role_names}")
    if len(workers) > 5:
        print(f"  ... and {len(workers) - 5} more")

    if workers:
        Explorer.update_vector_space(workers)
        print(f"Vector space updated with {len(workers)} workers")

    return workers
