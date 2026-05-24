#!/usr/bin/env python3
"""
Phase 5: 子聚類 — LevelRegistry + TypeRegistry。

為每個 Domain 做兩層子聚類：
  Domain (k=8) → Level (k=3~6 per domain) → Type (k=2~4 per level)

用法:
  cd ~/KAFED && source .venv/bin/activate
  python3 scripts/sub_cluster.py [--dry-run] [--min-level-k 3] [--max-level-k 6]
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict

import numpy as np

sys.stdout.reconfigure(line_buffering=True)

from kafed.knowledge.rag.vector_store import VectorStore
from kafed.knowledge.classify.sub_registry import (
    reset_level_registry, reset_type_registry,
    get_level_registry, get_type_registry,
)
from kafed.knowledge.classify.domain_registry import DomainRegistry
from kafed.knowledge.classify.embedding_space import Entity, name_to_uuid

CLUSTER_NAMES = {
    0: "SAP workflow technical documentation",
    1: "ESRI Query Client Methods",
    2: "Warehouse Management System Data",
    3: "CSS table cell styling",
    4: "Work order data mapping logic",
    5: "Asset Inventory and Event Data Models",
    6: "Task and Use Case References",
    7: "Pole Attachment Project Management",
}


def _sub_cluster(embeddings: np.ndarray, min_k: int, max_k: int,
                 n_init: str = "auto") -> tuple[np.ndarray, int, float]:
    """MiniBatchKMeans 搜尋最佳子聚類 k。"""
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.metrics import silhouette_score

    sample_size = min(5000, len(embeddings))
    if sample_size < min_k:
        # Too few samples, just assign all to one cluster
        return np.zeros(len(embeddings), dtype=int), 1, 0.0

    sample_idx = np.random.choice(len(embeddings), sample_size, replace=False)
    sample_emb = embeddings[sample_idx]

    best_k = min_k
    best_sil = -1.0

    for k in range(min_k, min(max_k + 1, len(embeddings) // 5 + 1)):
        km = MiniBatchKMeans(n_clusters=k, random_state=42,
                             batch_size=256, n_init=n_init, max_iter=100)
        km.fit(embeddings)
        labels_s = km.predict(sample_emb)
        sil = silhouette_score(sample_emb, labels_s, metric='cosine')
        if sil > best_sil:
            best_sil = sil
            best_k = k

    km = MiniBatchKMeans(n_clusters=best_k, random_state=42,
                         batch_size=256, n_init=n_init, max_iter=200)
    return km.fit_predict(embeddings), best_k, best_sil


def main():
    parser = argparse.ArgumentParser(description="Phase 5: 子聚類")
    parser.add_argument("--dry-run", action="store_true",
                        help="僅分析，不寫入")
    parser.add_argument("--min-level-k", type=int, default=3,
                        help="Level 最小 k (default: 3)")
    parser.add_argument("--max-level-k", type=int, default=6,
                        help="Level 最大 k (default: 6)")
    parser.add_argument("--min-type-k", type=int, default=2,
                        help="Type 最小 k (default: 2)")
    parser.add_argument("--max-type-k", type=int, default=4,
                        help="Type 最大 k (default: 4)")
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 5: Sub-Clustering — Level + Type Registry")
    print("=" * 60)

    # Step 1: Load all chunks from ChromaDB
    print("\n[1/6] Loading chunks from ChromaDB...")
    vs = VectorStore()
    collection = vs._collection
    total = collection.count()
    print(f"  Total chunks: {total}")

    batch_size = 1000
    all_ids: list[str] = []
    all_embeddings: list[list[float]] = []
    all_metadatas: list[dict] = []
    offset = 0
    while offset < total:
        batch = collection.get(
            offset=offset, limit=batch_size,
            include=["embeddings", "metadatas"],
        )
        if not batch["ids"]:
            break
        all_ids.extend(batch["ids"])
        all_embeddings.extend(batch["embeddings"])
        all_metadatas.extend(batch["metadatas"] or [{}] * len(batch["ids"]))
        offset += len(batch["ids"])
        print(f"  Fetching {offset}/{total}", end="\r", flush=True)

    print(f"\n  Loaded {len(all_ids)} chunks")

    # Step 2: Group by cluster_id
    print("\n[2/6] Grouping by cluster_id...")
    dom_groups: dict[int, list[tuple[int, np.ndarray]]] = defaultdict(list)
    for i, (eid, md) in enumerate(zip(all_ids, all_metadatas)):
        cid = (md or {}).get("cluster_id", -1)
        if cid >= 0:
            dom_groups[int(cid)].append((i, np.array(all_embeddings[i])))

    for cid in sorted(dom_groups.keys()):
        name = CLUSTER_NAMES.get(cid, f"Cluster_{cid}")
        print(f"  [{cid}] {name}: {len(dom_groups[cid])} chunks")

    # Step 3: Level sub-clustering (per domain)
    print("\n[3/6] Level sub-clustering per domain...")

    # L2 normalize
    all_emb = np.array(all_embeddings, dtype=np.float32)
    norms = np.linalg.norm(all_emb, axis=1, keepdims=True)
    norms[norms == 0] = 1
    all_emb_n = all_emb / norms

    # For each domain, sub-cluster into levels
    dom_entities = DomainRegistry.instance()
    domain_level_labels: dict[int, np.ndarray] = {}
    level_info: dict[int, list[dict]] = {}  # cid → [{level_id, name, count}]

    for cid in sorted(dom_groups.keys()):
        indices = [t[0] for t in dom_groups[cid]]
        if len(indices) < args.min_level_k * 2:
            n_levels = 1
            labels = np.zeros(len(indices), dtype=int)
            sil = 0.0
            print(f"  [{cid}] too small ({len(indices)}), keeping 1 level")
        else:
            emb = all_emb_n[indices]
            labels, n_levels, sil = _sub_cluster(
                emb, args.min_level_k, args.max_level_k,
            )

        # Build level label array for all chunks
        level_labels = np.full(len(all_ids), -1, dtype=int)
        for j, idx in enumerate(indices):
            level_labels[idx] = int(labels[j]) if n_levels > 1 else 0
        domain_level_labels[cid] = level_labels

        # Compute centroids and register levels
        dom_name = CLUSTER_NAMES.get(cid, f"Cluster_{cid}")
        dom_ent = dom_entities.get_by_name(dom_name)
        dom_id = dom_ent.id if dom_ent else ""

        level_info[cid] = []
        for lid in range(n_levels):
            mask = level_labels == lid
            lidx = [i for i in range(len(all_ids)) if mask[i]]
            if len(lidx) == 0:
                continue
            centroid = all_emb_n[lidx].mean(axis=0).tolist()
            level_name = f"{dom_name} Level_{lid}"
            level_entity = Entity(
                id=name_to_uuid(level_name),
                centroid=centroid,
                name=level_name,
                count=len(lidx),
                metadata={"domain_id": dom_id, "domain_name": dom_name,
                          "level_index": lid, "parent_cluster": cid},
            )
            level_info[cid].append(level_entity)

        print(f"  [{cid}] {dom_name:40s} → {n_levels} levels (sil={sil:.4f})")

    # Step 4: Type sub-clustering (per level)
    print("\n[4/6] Type sub-clustering per level...")

    all_type_labels = np.full(len(all_ids), -1, dtype=int)
    type_total = 0

    for cid in sorted(level_info.keys()):
        for level_entity in level_info[cid]:
            # Find indices for this level
            lidx = [i for i in range(len(all_ids))
                    if domain_level_labels[cid][i] == level_entity.metadata["level_index"]]

            if len(lidx) < args.min_type_k * 2:
                n_types = 1
                labels = np.zeros(len(lidx), dtype=int)
                sil = 0.0
            else:
                emb = all_emb_n[lidx]
                labels, n_types, sil = _sub_cluster(
                    emb, args.min_type_k, args.max_type_k,
                )

            for j, idx in enumerate(lidx):
                all_type_labels[idx] = int(labels[j]) if n_types > 1 else 0

            type_total += n_types

            print(f"    Level {level_entity.name:45s} → {n_types} types (sil={sil:.4f})")

    # Step 5: Register in LevelRegistry + TypeRegistry
    print("\n[5/6] Registering in LevelRegistry & TypeRegistry...")

    level_reg = reset_level_registry()
    type_reg = reset_type_registry()
    level_reg._dirty = True
    type_reg._dirty = True

    # Register levels
    level_count = 0
    for cid in sorted(level_info.keys()):
        for level_entity in level_info[cid]:
            level_reg.register(level_entity)
            level_count += 1

    level_reg._save()
    print(f"  LevelRegistry: {level_count} entities")

    # Register types
    type_count = 0
    for cid in sorted(level_info.keys()):
        for level_entity in level_info[cid]:
            lidx = [i for i in range(len(all_ids))
                    if domain_level_labels[cid][i] == level_entity.metadata["level_index"]]
            level_emb = all_emb_n[lidx]
            n_types = len(set(all_type_labels[lidx]) - {-1})

            for tid in range(n_types):
                mask = all_type_labels == tid
                tidx = [i for i in lidx if all_type_labels[i] == tid]
                if len(tidx) == 0:
                    continue
                centroid = all_emb_n[tidx].mean(axis=0).tolist()
                type_name = f"{level_entity.name} Type_{tid}"
                type_entity = Entity(
                    id=name_to_uuid(type_name),
                    centroid=centroid,
                    name=type_name,
                    count=len(tidx),
                    metadata={
                        "level_id": level_entity.id,
                        "level_name": level_entity.name,
                        "domain_id": level_entity.metadata.get("domain_id", ""),
                        "type_index": tid,
                    },
                )
                type_reg.register(type_entity)
                type_count += 1

    type_reg._save()
    print(f"  TypeRegistry: {type_count} entities")

    if args.dry_run:
        print("\n[Dry-run] 不更新 ChromaDB metadata")
        return

    # Step 6: Update ChromaDB metadata
    print("\n[6/6] Updating ChromaDB metadata with level_id + type_id...")

    # Build level_id and type_id lookup
    level_by_name = {e.name: e.id for e in level_reg.entities}
    type_by_name = {e.name: e.id for e in type_reg.entities}

    update_batch_size = 500
    batch_ids: list[str] = []
    batch_md: list[dict] = []
    updated = 0

    for i in range(len(all_ids)):
        md = dict(all_metadatas[i] or {})
        cid = md.get("cluster_id", -1)
        if cid >= 0:
            lid = int(domain_level_labels.get(int(cid), np.array([-1]))[i])
            tid = int(all_type_labels[i])

            # Find level entity id by name
            dom_name = CLUSTER_NAMES.get(int(cid), f"Cluster_{int(cid)}")
            level_name = f"{dom_name} Level_{lid}"
            level_id = level_by_name.get(level_name, "")
            type_name = f"{level_name} Type_{tid}"
            type_id = type_by_name.get(type_name, "")

            md["level_id"] = level_id
            md["level_index"] = lid
            md["type_id"] = type_id
            md["type_index"] = tid

        batch_ids.append(all_ids[i])
        batch_md.append(md)

        if len(batch_ids) >= update_batch_size:
            collection.update(ids=batch_ids, metadatas=batch_md)
            updated += len(batch_ids)
            print(f"  Updated {updated}/{len(all_ids)}", end="\r", flush=True)
            batch_ids, batch_md = [], []
            time.sleep(0.02)

    if batch_ids:
        collection.update(ids=batch_ids, metadatas=batch_md)
        updated += len(batch_ids)
        print(f"  Updated {updated}/{len(all_ids)}", end="\r", flush=True)

    print(f"\n  Done. {updated} chunks updated with level/type metadata.")

    # Summary
    print("\n" + "=" * 60)
    print("Phase 5 Complete!")
    print("=" * 60)
    print(f"\n  LevelRegistry: {level_count} entities")
    print(f"  TypeRegistry:  {type_count} entities")
    print(f"  Total chunks with full hierarchy: {updated}")


if __name__ == "__main__":
    main()
