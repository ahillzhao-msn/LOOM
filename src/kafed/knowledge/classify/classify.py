"""
classify.py — Embedding-based domain classification for KAFED.

取代 discern-engine 中的獨立分類邏輯，統一使用 KAFED 的 embedding 模型與 centroid 數據。
雙路徑置信邏輯：共識路徑 (embedding + regex 一致) + 高置信路徑 (embedding 獨強)。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kafed.config import get_config
from kafed.knowledge.rag.embedding import get_model
from kafed.knowledge.classify.domain_registry import DomainRegistry

# ── 路徑工具（文件名統一從 config 獲取）──

def _cfg():
    return get_config()

def _labels_path() -> Path:
    return _cfg().data_dir / _cfg().labels_filename

def _centroids_path() -> Path:
    return _cfg().data_dir / _cfg().centroids_filename

# ── 領域 regex 模式（從 seed_patterns.yaml 載入） ──

def _load_seed_patterns() -> dict[str, Any]:
    """載入 seed_patterns.yaml，從 config 路徑。"""
    cfg = get_config()
    sp_path = cfg.seed_patterns_path
    if sp_path and sp_path.exists():
        return _load_yaml_patterns(sp_path)
    return {}


def _load_yaml_patterns(path: Path) -> dict[str, Any]:
    """從 YAML 文件載入領域 regex 模式。"""
    try:
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return data.get("domains", {}) or {} if data else {}
    except Exception:
        return {}

def _infer_domain_regex(text: str) -> str:
    """從文本推斷領域（regex fallback，從 seed_patterns.yaml 載入）。"""
    patterns = _load_seed_patterns()
    for domain, info in patterns.items():
        if any(re.search(p, text, re.I) for p in info.get("patterns", [])):
            return domain
    return "GENERAL"

# ── 數據驅動的 Level/Type 分類 ──
# Pattern data is in seed_patterns.yaml; code fallbacks are domain-agnostic.

_LEVEL_YAML: dict[str, list[str]] | None = None
_TYPE_YAML: dict[str, list[str]] | None = None


def _load_level_type_patterns() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Load level and type patterns from seed_patterns.yaml."""
    global _LEVEL_YAML, _TYPE_YAML
    if _LEVEL_YAML is not None and _TYPE_YAML is not None:
        return _LEVEL_YAML, _TYPE_YAML

    levels: dict[str, list[str]] = {}
    types: dict[str, list[str]] = {}

    cfg = get_config()
    sp_path = cfg.seed_patterns_path
    if sp_path and sp_path.exists():
        try:
            import yaml
            with open(sp_path) as f:
                data = yaml.safe_load(f)
            for entry in data.get("levels", []):
                levels[entry["name"]] = entry.get("patterns", [])
            for entry in data.get("types", []):
                types[entry["name"]] = entry.get("patterns", [])
        except Exception:
            pass

    _LEVEL_YAML = levels
    _TYPE_YAML = types
    return levels, types


def _infer_level_regex(text: str) -> str:
    """知識層級（regex fallback）。先試 seed_patterns.yaml，再試通用 fallback。"""
    levels, _ = _load_level_type_patterns()
    if levels:
        for lv_name in ("L4", "L3", "L2"):
            patterns = levels.get(lv_name, [])
            for pat in patterns:
                try:
                    if re.search(pat, text, re.I):
                        return lv_name
                except Exception:
                    continue

    # Generic fallback: domain-agnostic heuristics
    if re.search(r'\b(?:transaction|t\.code|tcode)\s+', text, re.I):
        return "L4"
    if re.search(r'(?:如何|步驟|step|how\s+to|流程|workflow|pipeline|序列|順序|配置)', text, re.I):
        return "L3"
    if re.search(r'(?:首先|然後|接著|finally|最後|第一步|第二步|step\s+\d)', text, re.I):
        return "L3"
    if re.search(r'(?:區別|difference|vs|versus|關係|relationship|between|結構|architecture|pattern|模式)', text, re.I):
        return "L2"
    if re.search(r'(?:概念|concept|overview|概述|什麼是|是什麼|what\s+is|定義|definition|設計)', text, re.I):
        return "L2"
    return "L1"


def _infer_type_regex(text: str) -> str:
    """知識類型（regex fallback）。先試 seed_patterns.yaml，再試通用 fallback。"""
    _, types = _load_level_type_patterns()
    if types:
        for type_name in ("EXPERIENTIAL", "REASONING", "PROCEDURAL"):
            patterns = types.get(type_name, [])
            for pat in patterns:
                try:
                    if re.search(pat, text, re.I):
                        return type_name
                except Exception:
                    continue

    # Generic fallback
    if re.search(r'(?:不要|避免|注意|小心|陷阱|教訓|pitfall|warning)', text, re.I):
        return "EXPERIENTIAL"
    if re.search(r'(?:實踐中|經驗|l(?:earn|esson).*(?:found|lesson))', text, re.I):
        return "EXPERIENTIAL"
    if re.search(r'(?:因為|所以|因此|導致|原因|原理|why|because|therefore)', text, re.I):
        return "REASONING"
    if re.search(r'(?:設計模式|權衡|trade.?off|設計決策|decision)', text, re.I):
        return "REASONING"
    if re.search(r'(?:step|步驟|流程|how\s+to|操作|執行|調用|配置|輸入|點擊)', text, re.I):
        return "PROCEDURAL"
    if re.search(r'(?:先|然後|接著|最後|首先|其次|第一步|第二步)', text, re.I):
        return "PROCEDURAL"
    return "DECLARATIVE"

# ── 設定載入 ──

_settings_cache: dict[str, float] | None = None

def _load_settings() -> dict[str, float]:
    """從 seed_patterns.yaml 載入分類設定。"""
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache

    defaults = {
        "embedding_only_confidence_threshold": 0.85,
        "embedding_score_threshold": 0.65,
        "embedding_margin_threshold": 0.08,
        "general_boost_threshold": 0.70,
    }

    cfg = get_config()
    sp_path = cfg.seed_patterns_path
    if sp_path and sp_path.exists():
        try:
            import yaml
            with open(sp_path) as f:
                data = yaml.safe_load(f)
            if data and "settings" in data:
                _settings_cache = {**defaults, **data["settings"]}
                return _settings_cache
        except Exception:
            pass

    _settings_cache = defaults
    return defaults

# ── Centroid 管理 ──

def load_centroids() -> dict[str, dict]:
    """載入 KAFED centroids.json。"""
    cp = _centroids_path()
    if cp.exists():
        with open(cp) as f:
            data = json.load(f)
        # 過濾出含 centroid 向量的條目
        return {k: v for k, v in data.items() if "centroid" in v}
    return {}

def build_centroids_from_labels() -> dict[str, dict]:
    """從 labels 計算 centroids，不寫檔。供 rebuild_centroids() 調用補充。"""
    model = get_model()
    labels = load_labels()
    if not labels:
        return {}

    groups: dict[str, list[str]] = {}
    for lb in labels:
        d = lb.get("domain", "GENERAL") or "GENERAL"
        if d not in groups:
            groups[d] = []
        groups[d].append(lb.get("text", "")[:512])

    centroids: dict[str, dict] = {}
    for domain, texts in groups.items():
        if not texts:
            continue
        embeddings = model.encode(texts, show_progress_bar=False)
        centroid_vec = embeddings.mean(axis=0)
        centroids[domain] = {
            "centroid": centroid_vec.tolist(),
            "count": len(texts),
        }
    return centroids

def build_centroids() -> dict[str, dict]:
    """從 classification_labels 重建 centroids，寫入 centroids.json。"""
    centroids = build_centroids_from_labels()

    # 寫入 KAFED centroids.json
    cp = _centroids_path()
    cp.parent.mkdir(parents=True, exist_ok=True)
    with open(cp, "w") as f:
        json.dump(centroids, f, ensure_ascii=False, indent=2)

    return centroids

# ── 標籤管理 ──

def load_labels() -> list[dict]:
    """載入 classification_labels.jsonl。"""
    lp = _labels_path()
    labels = []
    if lp.exists():
        with open(lp) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        labels.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return labels

def record_classification(text: str, result: dict) -> dict:
    """記錄分類結果到 labels 文件。"""
    entry = {
        "id": hashlib.md5(text.encode()).hexdigest()[:12],
        "text": text[:512],
        "domain": result.get("domain", "GENERAL"),
        "level": result.get("level", "L2"),
        "type": result.get("type", "DECLARATIVE"),
        "method": result.get("method", "regex_fallback"),
        "confidence": result.get("confidence", 0.0),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    lp = _labels_path()
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry

# ── 核心分類介面 ──

def classify(text: str) -> dict:
    """
    統一分類介面。

    使用 DomainRegistry 找最近 centroid，regex 作 fallback。
    雙路徑：
      Path A (共識): embedding 與 regex 一致，cosine > 0.50
      Path B (高置信): embedding 獨強，score > 0.65, conf > 0.85, margin > 0.08

    Returns:
        {"domain": str, "cluster_id": str, "centroid": list[float]|None,
         "level": str, "type": str,
         "method": "embedding"|"regex_fallback", "confidence": float}
    """
    registry = DomainRegistry.instance()
    best_entity, best_score, second_score = registry.classify_text(text)
    best_score_f = float(best_score)
    second_score_f = float(second_score)

    if best_entity:
        confidence = float(max(0, min(1, (best_score_f + 1) / 2)))
        margin = best_score_f - second_score_f if second_score_f > -1 else 1.0

        settings = _load_settings()
        regex_domain = _infer_domain_regex(text)

        # Path A: 共識路徑
        consensus = best_entity.name == regex_domain
        consensus_threshold = 0.50

        # Path B: 高置信路徑
        high_conf_threshold = settings.get("embedding_score_threshold", 0.65)
        high_margin = settings.get("embedding_margin_threshold", 0.08)
        high_conf_only = settings.get("embedding_only_confidence_threshold", 0.85)

        use_embedding = False
        if consensus and best_score_f > consensus_threshold:
            use_embedding = True
        elif (best_score_f > high_conf_threshold and
              confidence > high_conf_only and
              margin > high_margin):
            use_embedding = True

        if use_embedding:
            result = {
                "domain": best_entity.name,
                "cluster_id": best_entity.id,
                "centroid": best_entity.centroid,
                "old_domain": best_entity.aliases[0] if best_entity.aliases else None,
                "level": _infer_level_regex(text),
                "type": _infer_type_regex(text),
                "method": "embedding",
                "confidence": round(confidence, 4),
            }
            record_classification(text, result)
            return result

    # Fallback: regex
    domain = _infer_domain_regex(text)
    fallback_conf = best_score_f if best_score_f > 0.3 else 0.0

    # Try to find matching domain in registry by old name
    fallback_entity = registry.get_by_name(domain)
    result = {
        "domain": domain,
        "cluster_id": fallback_entity.id if fallback_entity else "",
        "centroid": fallback_entity.centroid if fallback_entity else None,
        "old_domain": domain,
        "level": _infer_level_regex(text),
        "type": _infer_type_regex(text),
        "method": "regex_fallback",
        "confidence": round(fallback_conf, 4),
    }
    record_classification(text, result)
    return result
