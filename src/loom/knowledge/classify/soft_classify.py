"""
Soft Classification — 當 silhouette 低時，接受邊界模糊。

核心想法：classify() 返回 top-1 和 top-2，如果差距 < threshold，
說明這個查詢落在域邊界上。此時應該包含多個候選域，而非強行歸一。

用法:
  from loom.knowledge.classify.soft_classify import hierarchical_search
  
  results = hierarchical_search(text, threshold=0.10)
  # returns: {
  #   'candidates': [(domain, score), (domain, score), ...],
  #   'chains': [(domain, level, type), ...],  # 展開的獵取鏈
  #   'expanded': True/False,  # 是否因低silhouette而展開
  #   'search_filter': {...},  # 給 ChromaDB 的 where 條件
  # }

三層展開規則：
  1. Domain level: best_score - second_score < threshold → 包含兩個域
  2. Level level: 同上，針對每個候選域的子聚類
  3. Type level: 同上
  4. 如果三層都邊界模糊（超過 threshold 的候選 > 3），就真的是相似，返回全部
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from loom.knowledge.rag.embedding import get_model
from loom.knowledge.classify.domain_registry import DomainRegistry
from loom.knowledge.classify.sub_registry import (
    get_level_registry, get_type_registry,
)
from loom.knowledge.classify.embedding_space import Entity


@dataclass
class Candidate:
    entity: Entity
    score: float
    level: int  # 0=domain, 1=level, 2=type

    def __lt__(self, other):
        return self.score > other.score  # sort descending


@dataclass
class SoftResult:
    """軟分類結果。"""
    query: str
    candidates: list[Candidate] = field(default_factory=list)
    expanded: bool = False
    max_depth_reached: bool = False
    search_filter: dict | None = None

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def primary_domain(self) -> str:
        if self.candidates:
            return self.candidates[0].entity.name
        return "GENERAL"

    def to_chromadb_where(self) -> dict | None:
        """Generate ChromaDB where filter for all candidate domains."""
        if not self.candidates:
            return None
        
        # Collect unique domain cluster_ids
        cluster_ids = set()
        for c in self.candidates:
            if c.level == 0:
                # Domain-level candidates - use cluster_id from metadata
                # Need to map domain name to cluster_id
                pass
        
        return self.search_filter


def soft_classify(
    embedding: np.ndarray,
    registry: Any,
    threshold: float = 0.05,
    max_candidates: int = 3,
) -> list[Candidate]:
    """返回所有在 best_score 的 threshold 範圍內的候選。
    
    參數:
      embedding: 查詢的向量
      registry: DomainRegistry / LevelRegistry / TypeRegistry
      threshold: 差距閥值（best - second < threshold → 包含 second）
      max_candidates: 最多返回幾個（預設 3）
    
    返回:
      [(Entity, score), ...] 按 score 降序
    """
    if registry.count == 0:
        return []

    scores: list[tuple[Entity, float]] = []
    for entity in registry.entities:
        cv = entity.centroid_array
        score = float(np.dot(embedding, cv) / (
            np.linalg.norm(embedding) * np.linalg.norm(cv)
        ))
        scores.append((entity, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    
    if not scores:
        return []

    best_score = scores[0][1]
    results: list[Candidate] = []
    for entity, score in scores:
        if score >= best_score - threshold:
            results.append(Candidate(entity=entity, score=score, level=0))
        # 最多 max_candidates 個
        if len(results) >= max_candidates:
            break

    return results


def hierarchical_search(
    text: str,
    threshold: float = 0.10,
    max_depth: int = 3,
    max_expanded: int = 3,
) -> SoftResult:
    """三層軟分類獵取鏈。
    
    1. Domain level: 找最佳域 (threshold)
    2. Level level: 對每個候選域，找最佳 level
    3. Type level: 對每個 level，找最佳 type
    
    如果任何層級 best - second < threshold，展開到多個候選。
    
    返回:
      SoftResult 含完整候選列表 + ChromaDB where 條件
    """
    result = SoftResult(query=text)

    model = get_model()
    embedding = model.encode([text[:512]], show_progress_bar=False)[0]
    dr = DomainRegistry.instance()
    lr = get_level_registry()
    tr = get_type_registry()

    # Step 1: Domain level
    domain_candidates = soft_classify(embedding, dr, threshold, max_expanded)
    result.expanded = len(domain_candidates) > 1

    cluster_ids: set[int] = set()
    chains: list[tuple[str, str, str]] = []

    for dom_cand in domain_candidates:
        dom_name = dom_cand.entity.name
        dom_id = dom_cand.entity.id

        cluster_id = _name_to_cluster_id(dom_name, dr)
        if cluster_id is not None:
            cluster_ids.add(cluster_id)

        # Step 2: Level level
        level_entities = lr.get_by_parent(dom_id)
        level_candidates: list[Candidate] = []
        if level_entities:
            # Treat level entities as their own mini-registry
            best_score = -1.0
            all_scores: list[tuple[Entity, float]] = []
            for le in level_entities:
                cv = le.centroid_array
                score = float(np.dot(embedding, cv) / (
                    np.linalg.norm(embedding) * np.linalg.norm(cv)
                ))
                all_scores.append((le, score))
            
            all_scores.sort(key=lambda x: x[1], reverse=True)
            if all_scores:
                best_score = all_scores[0][1]
                for le, score in all_scores:
                    if score >= best_score - threshold:
                        level_candidates.append(
                            Candidate(entity=le, score=score, level=1)
                        )
                    if len(level_candidates) >= max_expanded:
                        break

        for lv_cand in level_candidates:
            # Step 3: Type level
            type_entities = tr.get_by_parent(lv_cand.entity.id)
            type_candidates: list[Candidate] = []
            if type_entities:
                best_score = -1.0
                all_scores: list[tuple[Entity, float]] = []
                for te in type_entities:
                    cv = te.centroid_array
                    score = float(np.dot(embedding, cv) / (
                        np.linalg.norm(embedding) * np.linalg.norm(cv)
                    ))
                    all_scores.append((te, score))
                
                all_scores.sort(key=lambda x: x[1], reverse=True)
                if all_scores:
                    best_score = all_scores[0][1]
                    for te, score in all_scores:
                        if score >= best_score - threshold:
                            type_candidates.append(
                                Candidate(entity=te, score=score, level=2)
                            )
                        if len(type_candidates) >= max_expanded:
                            break

            for ty_cand in type_candidates:
                chains.append((dom_name, lv_cand.entity.name, ty_cand.entity.name))
            
            if not type_candidates:
                chains.append((dom_name, lv_cand.entity.name, ""))

        if not level_candidates:
            chains.append((dom_name, "", ""))

    result.candidates = domain_candidates

    # Build ChromaDB where filter
    if cluster_ids:
        if len(cluster_ids) == 1:
            result.search_filter = {"cluster_id": list(cluster_ids)[0]}
        else:
            result.search_filter = {
                "$or": [{"cluster_id": cid} for cid in cluster_ids]
            }

    result.max_depth_reached = max_depth >= 3

    # Attach chains as metadata for debugging
    result._chains = chains

    return result


# Cluster centroid cache: loaded from cluster_mapping.json + DomainRegistry
_CLUSTER_CENTROIDS: list[np.ndarray] | None = None
# Cluster ID mapping: integer → entity UUID (from cluster_mapping.json)
_CLUSTER_MAP: dict[str, int] | None = None  # UUID → integer cluster_id


def _load_cluster_centroids() -> list[np.ndarray]:
    """Load KMeans cluster centroids from data (cluster_mapping.json + DomainRegistry)."""
    global _CLUSTER_CENTROIDS, _CLUSTER_MAP
    if _CLUSTER_CENTROIDS is not None:
        return _CLUSTER_CENTROIDS

    from loom.config import get_config
    import json
    path = get_config().data_dir / "cluster_mapping.json"
    dr = DomainRegistry.instance()

    centroids: list[np.ndarray] = []
    mapping: dict[str, int] = {}  # UUID → integer ID

    try:
        cmap = json.loads(path.read_text())
        clusters = cmap.get("clusters", {})
        for cid_str, info in clusters.items():
            cid = int(cid_str)
            uuid = info.get("cluster_id", "")
            ent = dr.get(uuid)
            if ent and ent.centroid:
                centroids.append(np.array(ent.centroid, dtype=np.float32))
                mapping[uuid] = cid
    except Exception:
        pass

    _CLUSTER_CENTROIDS = centroids
    _CLUSTER_MAP = mapping
    return centroids


def _name_to_cluster_id(name: str, dr: DomainRegistry | None = None) -> int | None:
    """Map any domain name → KMeans cluster_id via centroid proximity. Data-driven, no hardcoded names."""
    if dr is None:
        dr = DomainRegistry.instance()
    ent = dr.get_by_name(name)
    if ent is None:
        return None

    ccentroids = _load_cluster_centroids()
    if not ccentroids:
        return None

    cv = np.array(ent.centroid, dtype=np.float32)
    best_cid = -1
    best_sim = -1.0
    for cid, cc in enumerate(ccentroids):
        sim = float(np.dot(cv, cc) / (np.linalg.norm(cv) * np.linalg.norm(cc)))
        if sim > best_sim:
            best_sim = sim
            best_cid = cid
    return best_cid if best_cid >= 0 else None
