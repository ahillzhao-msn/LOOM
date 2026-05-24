"""
DomainRegistry — 一級聚類：語義域。

繼承 Registry 抽象基類，管理域 Entity。
所有下游引用使用 domain.id，永不依賴 domain.name。

初始化：首次運行時從 centroids.json 導入舊域。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from numpy import dot
from numpy.linalg import norm

from kafed.config import get_config
from kafed.knowledge.rag.embedding import get_model
from kafed.knowledge.classify.embedding_space import (
    Entity, Registry, name_to_uuid,
)


def _registry_path() -> Path:
    return get_config().data_dir / "domains.json"


class DomainRegistry(Registry):
    """域註冊服務。單例，全系統只一個。"""

    _instance: DomainRegistry | None = None

    def __init__(self):
        self._entities: dict[str, Entity] = {}   # id → Entity
        self._names: dict[str, str] = {}          # name → id
        self._dirty = False

    # ── 單例 ────────────────────────────────

    @classmethod
    def instance(cls) -> DomainRegistry:
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._load()
        return cls._instance

    @classmethod
    def reset(cls) -> DomainRegistry:
        cls._instance = cls()
        cls._instance._load()
        return cls._instance

    # ── Registry 抽象實現 ───────────────────

    def classify(self, embedding: np.ndarray) -> tuple[Entity | None, float, float]:
        if not self._entities:
            return None, -1.0, -1.0

        best_score = -1.0
        second_score = -1.0
        best_entity: Entity | None = None

        for entity in self._entities.values():
            cv = entity.centroid_array
            score = float(dot(embedding, cv) / (norm(embedding) * norm(cv)))
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
            if entity.name not in existing.aliases:
                existing.aliases.append(entity.name)
            self._dirty = True
            return existing

        if not entity.id:
            entity.id = name_to_uuid(entity.name)

        self._entities[entity.id] = entity
        self._names[entity.name] = entity.id
        self._dirty = True
        self._save()
        return entity

    @property
    def entities(self) -> list[Entity]:
        return list(self._entities.values())

    @property
    def count(self) -> int:
        return len(self._entities)

    # ── 便捷方法 ────────────────────────────

    def register_from_centroid(self, name: str, centroid: list[float],
                               count: int = 0, aliases: list[str] | None = None) -> Entity:
        """從 centroid 向量註冊域。"""
        eid = name_to_uuid(name)
        entity = Entity(
            id=eid,
            centroid=centroid,
            name=name,
            aliases=aliases or [name],
            count=count,
        )
        return self.register(entity)

    def import_from_centroids(self, centroids_path: Path) -> int:
        """從舊 centroids.json 導入。冪等。"""
        if not centroids_path.exists():
            return 0
        with open(centroids_path) as f:
            centroids = json.load(f)
        registered = 0
        for name, info in centroids.items():
            centroid = info.get("centroid")
            count = info.get("count", 0)
            if centroid:
                self.register_from_centroid(name, centroid, count=count)
                registered += 1
        self._save()
        return registered

    # ── 持久化 ──────────────────────────────

    def _load(self) -> None:
        rp = _registry_path()
        if not rp.exists():
            cp = get_config().data_dir / get_config().centroids_filename
            if cp.exists():
                imported = self.import_from_centroids(cp)
                if imported > 0:
                    self._save()
            return
        try:
            with open(rp) as f:
                data = json.load(f)
            for item in data.get("domains", []):
                entity = Entity.from_dict(item)
                self._entities[entity.id] = entity
                self._names[entity.name] = entity.id
        except Exception:
            pass

    def _save(self) -> None:
        if not self._dirty:
            return
        rp = _registry_path()
        rp.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 2,
            "registry_type": "domain",
            "domains": [e.to_dict() for e in self._entities.values()],
        }
        with open(rp, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._dirty = False
