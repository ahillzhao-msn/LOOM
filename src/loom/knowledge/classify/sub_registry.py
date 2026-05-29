"""
LevelRegistry & TypeRegistry — 二/三級子聚類註冊。

繼承 Registry 抽象，與 DomainRegistry 同構。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from loom.config import get_config
from loom.knowledge.rag.embedding import get_model
from loom.knowledge.classify.embedding_space import (
    Entity, Registry, name_to_uuid,
)


def _level_path() -> Path:
    return get_config().data_dir / "levels.json"


def _type_path() -> Path:
    return get_config().data_dir / "types.json"


class _SubRegistry(Registry):
    """子註冊表的通用實現（Level / Type 共用）。"""

    def __init__(self, name: str, save_path: Path,
                 parent_key: str = "domain_id"):
        self._name = name
        self._save_path = save_path
        self._parent_key = parent_key
        self._entities: dict[str, Entity] = {}
        self._names: dict[str, str] = {}
        self._dirty = False
        self._load()

    # ── Registry 實現 ─────────────────────────

    def classify(self, embedding: np.ndarray
                 ) -> tuple[Entity | None, float, float]:
        if not self._entities:
            return None, -1.0, -1.0
        best_score = -1.0
        second_score = -1.0
        best_entity: Entity | None = None
        for entity in self._entities.values():
            cv = entity.centroid_array
            score = float(np.dot(embedding, cv) /
                          (np.linalg.norm(embedding) * np.linalg.norm(cv)))
            if score > best_score:
                second_score = best_score
                best_score = score
                best_entity = entity
            elif score > second_score:
                second_score = score
        return best_entity, best_score, second_score

    def classify_text(self, text: str) -> tuple[Entity | None, float, float]:
        model = get_model()
        vec = model.encode([text[:512]], show_progress_bar=False)[0]
        return self.classify(vec)

    def get(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def get_by_name(self, name: str) -> Entity | None:
        eid = self._names.get(name)
        if eid:
            return self._entities.get(eid)
        return None

    def register(self, entity: Entity) -> Entity:
        eid = self._names.get(entity.name)
        if eid:
            existing = self._entities[eid]
            existing.centroid = entity.centroid
            existing.count = entity.count
            existing.metadata.update(entity.metadata)
            self._dirty = True
            return existing

        if not entity.id:
            entity.id = name_to_uuid(entity.name)
        self._entities[entity.id] = entity
        self._names[entity.name] = entity.id
        self._dirty = True
        self._save()
        return entity

    # classify 由外層 soft_classify 調用（此處已有實現，見上方 classify）

    @property
    def entities(self) -> list[Entity]:
        return list(self._entities.values())

    @property
    def count(self) -> int:
        return len(self._entities)

    # ── 快取查詢 ─────────────────────────────

    def get_by_parent(self, parent_id: str) -> list[Entity]:
        """按父 ID 查詢子實體。"""
        return [
            e for e in self._entities.values()
            if e.metadata.get(self._parent_key) == parent_id
        ]

    # ── 持久化 ──────────────────────────────

    def _load(self) -> None:
        if not self._save_path.exists():
            return
        try:
            with open(self._save_path) as f:
                data = json.load(f)
            for item in data.get("entries", []):
                entity = Entity.from_dict(item)
                self._entities[entity.id] = entity
                self._names[entity.name] = entity.id
        except Exception:
            pass

    def _save(self) -> None:
        if not self._dirty:
            return
        self._save_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "name": self._name,
            "entries": [e.to_dict() for e in self._entities.values()],
        }
        with open(self._save_path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._dirty = False


# ── 單例訪問 ────────────────────────────────

_LEVEL_INSTANCE: _SubRegistry | None = None
_TYPE_INSTANCE: _SubRegistry | None = None


def get_level_registry() -> _SubRegistry:
    global _LEVEL_INSTANCE
    if _LEVEL_INSTANCE is None:
        _LEVEL_INSTANCE = _SubRegistry("level", _level_path(), parent_key="domain_id")
    return _LEVEL_INSTANCE


def get_type_registry() -> _SubRegistry:
    global _TYPE_INSTANCE
    if _TYPE_INSTANCE is None:
        _TYPE_INSTANCE = _SubRegistry("type", _type_path(), parent_key="level_id")
    return _TYPE_INSTANCE


def reset_level_registry() -> _SubRegistry:
    global _LEVEL_INSTANCE
    _LEVEL_INSTANCE = _SubRegistry("level", _level_path(), parent_key="domain_id")
    return _LEVEL_INSTANCE


def reset_type_registry() -> _SubRegistry:
    global _TYPE_INSTANCE
    _TYPE_INSTANCE = _SubRegistry("type", _type_path(), parent_key="level_id")
    return _TYPE_INSTANCE
