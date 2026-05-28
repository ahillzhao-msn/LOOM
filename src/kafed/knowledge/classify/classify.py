"""
classify.py — Pure embedding-based classification for KAFED.

Domain · Level · Type — all three tiers classified via embedding centroids.
No regex, no hardcoded patterns, no domain-specific heuristics.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kafed.config import get_config
from kafed.knowledge.rag.embedding import get_model
from kafed.knowledge.classify.domain_registry import DomainRegistry


def _cfg():
    return get_config()

def _labels_path() -> Path:
    return _cfg().data_dir / _cfg().labels_filename

def _centroids_path() -> Path:
    return _cfg().data_dir / _cfg().centroids_filename


# ── Centroid management ──

def load_labels() -> list[dict]:
    """Load classification_labels.jsonl."""
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


def load_centroids() -> dict[str, dict]:
    """Load centroids.json, returning entries with centroid vectors."""
    cp = _centroids_path()
    if cp.exists():
        with open(cp) as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if "centroid" in v}
    return {}


def build_centroids_from_labels() -> dict[str, dict]:
    """Compute centroids from labels (in-memory only, does not write)."""
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
    """Rebuild centroids from labels and write to centroids.json."""
    centroids = build_centroids_from_labels()
    cp = _centroids_path()
    cp.parent.mkdir(parents=True, exist_ok=True)
    with open(cp, "w") as f:
        json.dump(centroids, f, ensure_ascii=False, indent=2)
    return centroids


def rebuild_centroids() -> dict[str, dict]:
    """Alias for build_centroids — used by scheduler flywheel task."""
    return build_centroids()


# ── Embedding-only classification ──

def classify(text: str) -> dict[str, Any]:
    """Classify text by domain, level, and type — embedding only.

    Returns:
        {"domain": str, "cluster_id": str, "centroid": ndarray|None,
         "level": str, "type": str,
         "method": "embedding"|"default",
         "confidence": float}
    """
    registry = DomainRegistry.instance()
    best_entity, best_score, second_score = registry.classify_text(text)
    best_score_f = float(best_score)

    if best_entity and best_score_f > 0.3:
        confidence = float(max(0, min(1, (best_score_f + 1) / 2)))
        margin = float(second_score - best_score_f) if second_score is not None else 1.0

        if confidence > 0.55 or margin > 0.08:
            result = {
                "domain": best_entity.name,
                "cluster_id": best_entity.id,
                "centroid": best_entity.centroid,
                "old_domain": best_entity.aliases[0] if best_entity.aliases else None,
                "level": _classify_level(text),
                "type": _classify_type(text),
                "method": "embedding",
                "confidence": round(confidence, 4),
            }
            _record(text, result)
            return result

    # Fallback: sensible defaults, no regex
    result = {
        "domain": "GENERAL",
        "cluster_id": "",
        "centroid": None,
        "old_domain": None,
        "level": "L1",
        "type": "DECLARATIVE",
        "method": "default",
        "confidence": round(float(best_score_f) if best_score_f > 0 else 0.0, 4),
    }
    _record(text, result)
    return result


def _classify_level(text: str) -> str:
    """Classify level via embedding centroids (sub-registry). Falls back to L1."""
    try:
        from kafed.knowledge.classify.sub_registry import LevelRegistry as LR
        reg = LR.instance()
        best, score, _ = reg.classify_text(text)
        if best and score > 0.3:
            return best.name
    except Exception:
        pass
    return "L1"


def _classify_type(text: str) -> str:
    """Classify type via embedding centroids (sub-registry). Falls back to DECLARATIVE."""
    try:
        from kafed.knowledge.classify.sub_registry import TypeRegistry as TR
        reg = TR.instance()
        best, score, _ = reg.classify_text(text)
        if best and score > 0.3:
            return best.name
    except Exception:
        pass
    return "DECLARATIVE"


# ── Classification recording ──

def _record(text: str, result: dict[str, Any]) -> None:
    """Append classification result to labels JSONL (non-blocking)."""
    try:
        entry = {
            "text_hash": hashlib.md5(text.encode()).hexdigest(),
            "domain": result["domain"],
            "level": result["level"],
            "type": result["type"],
            "method": result["method"],
            "confidence": result["confidence"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        path = _labels_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
