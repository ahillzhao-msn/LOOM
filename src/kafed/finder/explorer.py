"""
KAFED Finder — 模型發現器（Explorer）。

掃描所有模型配置源，解析完整元數據，生成多維向量空間。

數據來源（按優先級）：
  1. llama-server /v1/models  — 本地模型，含 status.args 全部參數
  2. config.yaml              — Hermes 主配置
  3. roster.yaml / cloud_models — 已註冊 / 雲端模型

所有來源的元數據統一用 MODEL_META_SCHEMA 承載。
新增屬性只需在 matcher.py 的 schema 加一行，嵌入描述自動生成。
"""

from __future__ import annotations

import json
import pickle
import re
import subprocess
from typing import Any, Optional

import yaml

from kafed.config import get_config
from kafed.finder.registry import Registry
from kafed.finder.matcher import (WorkerCandidate, MODEL_META_SCHEMA,
                                   meta_defaults, build_meta_description)


# ── llama.cpp status.args 解析器 ──────────────────


def _parse_llama_args(args: list[str]) -> dict:
    """解析 llama-server 的 status.args 列表 → 元數據字典。

    args 格式: ["--flag", "value", "--bool-flag", ...]
    返回 MODEL_META_SCHEMA 兼容的字典。
    """
    meta = meta_defaults()
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            key = arg[2:].replace("-", "_")
            # 看下一個是否為值（非 -- 開頭）
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                val = args[i + 1]
                i += 2
                # 映射到 schema 字段
                _set_meta(meta, key, val)
            else:
                # 布爾標誌
                _set_meta(meta, key, "on")
                i += 1
        else:
            i += 1
    return meta


def _set_meta(meta: dict, key: str, val: str):
    """將 key=val 按 schema 類型寫入 meta。"""
    # 字段名映射（llama.cpp 參數名 → schema 字段名）
    key_map = {
        "ctx_size": "context_window",
        "n_gpu_layers": None,  # 硬體信息，不入 schema
        "flash_attn": None,
        "model": None,         # 模型文件路徑，不入 schema
        "alias": "name",
        "host": None,
        "port": None,
        "mmproj": None,
        "mmproj_auto": None,
        "jinja": None,
        "pooling": None,
        "repeat_penalty": "repeat_penalty",
    }
    mapped = key_map.get(key, key)

    # 跳過不入 schema 的字段
    if mapped is None:
        return

    # 按 schema 類型轉換
    schema_type = MODEL_META_SCHEMA.get(mapped, (None, None))[0]
    if schema_type is None:
        # 不在 schema 中但可能是自定義字段 → 按字符串保留
        meta[mapped] = val
        return

    try:
        if schema_type == int:
            meta[mapped] = int(val)
        elif schema_type == float:
            meta[mapped] = float(val)
        elif schema_type == bool:
            meta[mapped] = val.lower() in ("on", "true", "yes", "1")
        else:
            meta[mapped] = val
    except (ValueError, TypeError):
        meta[mapped] = val


# ── Explorer ──────────────────────────────────────


class Explorer:
    """模型發現器。"""

    def __init__(self):
        self._cfg = get_config()

    @staticmethod
    def scan_all() -> list[WorkerCandidate]:
        """掃描所有來源的模型，返回完整 WorkerCandidate 列表。"""
        cfg = get_config()
        workers: list[WorkerCandidate] = []
        seen: set[str] = set()

        # 1. llama-server /v1/models（本地模型，最完整信息）
        try:
            result = subprocess.run(
                ["curl", "-s", "http://localhost:8000/v1/models"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout) if result.stdout else {}
                for m in data.get("data", []):
                    name = m.get("id", "")
                    if not name or name in seen:
                        continue
                    # 從 status.args 解析完整元數據
                    args = m.get("status", {}).get("args", [])
                    meta = _parse_llama_args(args)
                    meta["name"] = name
                    meta["provider"] = "local"
                    meta["model_id"] = name
                    meta["is_online"] = True

                    wc = WorkerCandidate(
                        name=name,
                        provider="local",
                        model_id=name,
                        meta=meta,
                        is_online=True,
                        is_free=True,
                        match_score=0.6,
                        # 從元數據推導能力標籤
                        capability_tags=Explorer._derive_tags(meta),
                    )
                    wc.estimated_tps = Explorer._estimate_tps(name, meta)
                    workers.append(wc)
                    seen.add(name)
        except Exception:
            pass

        # 2. Hermes config.yaml
        cp = cfg.config_path
        if cp.exists():
            try:
                with open(cp) as f:
                    cfg_yaml = yaml.safe_load(f)
                providers = cfg_yaml.get("providers", {})
                for prov_name, prov_cfg in providers.items():
                    if prov_name == "llamacpp":
                        continue  # 已從 llama-server 發現
                    for m in prov_cfg.get("models", []):
                        model_name = m if isinstance(m, str) else m.get("model", m.get("name", ""))
                        if not model_name or model_name in seen:
                            continue
                        meta = meta_defaults()
                        meta["name"] = model_name
                        meta["provider"] = prov_name
                        meta["model_id"] = model_name
                        meta["is_online"] = True
                        meta["context_window"] = 128000  # 雲端模型默認
                        meta["supports_functions"] = True

                        wc = WorkerCandidate(
                            name=model_name,
                            provider=prov_name,
                            model_id=model_name,
                            meta=meta,
                            is_online=True,
                            is_free=False,
                            match_score=0.5,
                            cost_per_token=prov_cfg.get("cost", 0) if isinstance(prov_cfg, dict) else 0,
                            capability_tags=Explorer._derive_tags(meta),
                        )
                        workers.append(wc)
                        seen.add(model_name)
            except Exception:
                pass

        # 3. Cloud models（從 config 補充）
        for cm in cfg.cloud_models:
            name = cm.get("name", "")
            if not name or name in seen:
                continue
            meta = meta_defaults()
            meta.update({
                "name": name,
                "provider": cm.get("provider", "cloud"),
                "model_id": name,
                "context_window": cm.get("context_window", 128000),
                "temperature": cm.get("temperature", 0.6),
                "supports_reasoning": cm.get("supports_reasoning", False),
                "supports_vision": cm.get("supports_vision", False),
                "supports_functions": cm.get("supports_functions", True),
                "is_online": True,
            })
            wc = WorkerCandidate(
                name=name,
                provider=cm.get("provider", "cloud"),
                model_id=name,
                meta=meta,
                is_online=True,
                is_free=cm.get("is_free", False),
                match_score=0.4,
                cost_per_token=cm.get("cost", 0),
                capability_tags=Explorer._derive_tags(meta),
            )
            workers.append(wc)
            seen.add(name)

        return workers

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
        if meta.get("tps", 0) > 100:
            tags.append("fast")
        if meta.get("context_window", 0) >= 32000:
            tags.append("long_context")
        if meta.get("provider") in ("local", "llamacpp"):
            tags.append("local")
        if not tags:
            tags.append("general")
        return tags

    @staticmethod
    def _estimate_tps(name: str, meta: dict) -> int:
        """估算模型 TPS。"""
        # 已知模型
        known_tps = {
            "leader": 55,
            "worker_md1": 164,
            "worker_sm1": 310,
            "worker_sm2": 310,
            "expert_abap": 120,
            "expert_abap_pm": 120,
            "vision": 80,
        }
        if name in known_tps:
            return known_tps[name]
        # 上下文越小通常越快
        ctx = meta.get("context_window", 16384)
        if ctx <= 8192:
            return 200
        if ctx <= 16384:
            return 100
        return 50

    @staticmethod
    def update_vector_space(workers: list[WorkerCandidate]) -> None:
        """用 KAFED embedding 生成每個模型的多維能力向量。

        使用 build_meta_description() 自動生成描述文本，
        新增 schema 字段後不需改此函數。
        """
        import numpy as np
        from kafed.knowledge.rag.embedding import get_model
        model = get_model()
        vectors = {}
        for w in workers:
            desc = build_meta_description(w.meta)
            # 截斷避免過長
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
        ("src", "llama+config+cloud", ""),
        ("hit", f"{len(workers)} workers", ""),
    ], end=f"update={update_roster}")
    for w in workers[:5]:
        print(f"  {w.describe()}")
        # 顯示元數據關鍵值
        ctx = w.context_window
        meta_preview = {k: w.meta.get(k) for k in ("temperature", "top_p", "top_k", "supports_reasoning")}
        print(f"       ctx={ctx} {meta_preview}")
    if len(workers) > 5:
        print(f"  ... and {len(workers) - 5} more")

    if update_roster and workers:
        Explorer.sync_roster(workers)
        Explorer.update_vector_space(workers)
        print(f"Vector space updated with {len(workers)} workers")

    return workers
