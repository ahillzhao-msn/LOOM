"""
EmbeddingSpace — 嵌入空間分層註冊服務。

通用抽象：
  Registry — 註冊表（抽象基類）
  Entity — 域實體（嵌入空間中的一個聚類）

分層實例：
  DomainRegistry → 一級聚類：語義域
  LevelRegistry  → 二級聚類：域內知識深度（子聚類）
  TypeRegistry   → 二級聚類：域內知識類型（子聚類）
  FinderRegistry → 模型能力向量匹配
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# UUID v5 namespace for deterministic entity IDs
_ENTITY_NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def name_to_uuid(name: str) -> str:
    """從名字生成確定性 UUID（v5）。"""
    return str(uuid.uuid5(_ENTITY_NS, name))


@dataclass
class Entity:
    """嵌入空間中的一個聚類實體。

    id: 永久 UUID，永不改變。
    centroid: 聚類中心向量——這是真身，name 只是描述。
    name: 人類可讀名（可變，LLM 生成，不影響分類決策）。
    aliases: 歷史名列表（向後相容，追蹤遷移）。
    count: 該聚類的樣本數。
    metadata: 擴展屬性（層級、來源等）。
    """
    id: str
    centroid: list[float]
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def centroid_array(self) -> np.ndarray:
        return np.array(self.centroid, dtype=np.float32)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "centroid": self.centroid,
            "name": self.name,
            "aliases": self.aliases,
            "count": self.count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Entity:
        return cls(
            id=data["id"],
            centroid=data["centroid"],
            name=data.get("name", ""),
            aliases=data.get("aliases", []),
            count=data.get("count", 0),
            metadata=data.get("metadata", {}),
        )


class Registry(ABC):
    """註冊表抽象基類。

    所有嵌入分類層（Domain、Level、Type、Finder）共用同一套接口。
    """

    @abstractmethod
    def classify(self, embedding: np.ndarray) -> tuple[Entity | None, float, float]:
        """找最近的 Entity（cosine 距離）。
        Returns: (Entity or None, best_score, second_score)
        """
        ...

    @abstractmethod
    def classify_text(self, text: str) -> tuple[Entity | None, float, float]:
        """文本 → embedding → 找最近 Entity。"""
        ...

    @abstractmethod
    def get(self, entity_id: str) -> Entity | None:
        """按 ID 查詢。"""
        ...

    @abstractmethod
    def get_by_name(self, name: str) -> Entity | None:
        """按名字查詢（向後相容）。"""
        ...

    @abstractmethod
    def register(self, entity: Entity) -> Entity:
        """註冊 Entity（冪等）。"""
        ...

    @property
    @abstractmethod
    def entities(self) -> list[Entity]:
        ...

    @property
    @abstractmethod
    def count(self) -> int:
        ...
