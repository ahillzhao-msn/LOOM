#!/usr/bin/env python3
"""
Centroid Flywheel — 定期重聚類飛輪。

每週 cron 觸發：
  1. 從 ChromaDB 拉取全部 embeddings
  2. MiniBatchKMeans (k=8, random_state=42)
  3. 計算新 centroid 與舊 centroid 的 cosine shift
  4. 若 shift > 閥值（default 0.05），更新 DomainRegistry + ChromaDB metadata
  5. 寫 flywheel 日誌

用法:
  cd ~/KAFED && source .venv/bin/activate
  python3 scripts/centroid_flywheel.py [--force] [--threshold 0.05]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np

sys.stdout.reconfigure(line_buffering=True)

from kafed.config import get_config
from kafed.knowledge.rag.vector_store import VectorStore
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


def main():
    parser = argparse.ArgumentParser(description="Centroid Flywheel")
    parser.add_argument("--force", action="store_true",
                        help="強制更新，無論 shift")
    parser.add_argument("--threshold", type=float, default=0.05,
                        help="shift 閥值 (default: 0.05)")
    args = parser.parse_args()

    print(f"Centroid Flywheel — {datetime.now(timezone.utc).isoformat()}")
    print(f"  force={args.force}, threshold={args.threshold}")
    print("=" * 50)

    # Step 1: Load embeddings
    print("\n[1/4] Loading embeddings from ChromaDB...")
    vs = VectorStore()
    collection = vs._collection
    total = collection.count()
    print(f"  Total chunks: {total}")

    batch_size = 1000
    all_ids: list[str] = []
    all_embeddings: list[list[float]] = []
    offset = 0
    while offset < total:
        batch = collection.get(
            offset=offset, limit=batch_size,
            include=["embeddings"],
        )
        if not batch["ids"]:
            break
        all_ids.extend(batch["ids"])
        all_embeddings.extend(batch["embeddings"])
        offset += len(batch["ids"])
        print(f"  Fetching {offset}/{total}", end="\r", flush=True)

    embeddings = np.array(all_embeddings, dtype=np.float32)
    print(f"\n  Loaded {len(all_ids)} chunks, shape {embeddings.shape}")

    # Step 2: Cluster
    print("\n[2/4] Clustering...")
    from sklearn.cluster import MiniBatchKMeans

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    emb_norm = embeddings / norms

    t0 = time.time()
    kmeans = MiniBatchKMeans(n_clusters=8, random_state=42,
                              batch_size=1024, n_init='auto', max_iter=200)
    labels = kmeans.fit_predict(emb_norm)
    print(f"  Clustered in {time.time() - t0:.1f}s")

    # Step 3: Check centroid shift
    print("\n[3/4] Computing centroid shift...")
    dr = DomainRegistry.instance()
    new_centroids: dict[int, np.ndarray] = {}
    cluster_counts: dict[int, int] = {}

    for cid in range(8):
        mask = labels == cid
        cluster_emb = emb_norm[mask]
        centroid = cluster_emb.mean(axis=0)
        new_centroids[cid] = centroid
        cluster_counts[cid] = int(mask.sum())
        print(f"  Cluster {cid}: {cluster_counts[cid]} chunks")

    # Compare with existing centroids
    max_shift = 0.0
    shifts: dict[int, float] = {}
    for cid in range(8):
        name = CLUSTER_NAMES[cid]
        ent = dr.get_by_name(name)
        if ent:
            old_c = np.array(ent.centroid, dtype=np.float32)
            new_c = new_centroids[cid]
            cos_sim = float(np.dot(old_c, new_c) / (
                np.linalg.norm(old_c) * np.linalg.norm(new_c)))
            shift = 1.0 - cos_sim
            shifts[cid] = shift
            max_shift = max(max_shift, shift)
            print(f"  Cluster {cid} ({name[:30]}): shift={shift:.4f}")
        else:
            print(f"  Cluster {cid}: NEW (no existing centroid)")
            shifts[cid] = 1.0
            max_shift = 1.0

    print(f"\n  Max centroid shift: {max_shift:.4f}")

    if max_shift < args.threshold and not args.force:
        print(f"  Shift < threshold ({args.threshold}), skipping update.")
        print(f"\n✅ Flywheel: no update needed.")
        return

    # Step 4: Update
    print("\n[4/4] Updating DomainRegistry and ChromaDB...")
    
    # Update DomainRegistry
    for cid in range(8):
        name = CLUSTER_NAMES[cid]
        centroid_list = new_centroids[cid].tolist()
        ent = dr.get_by_name(name)
        if ent:
            ent.centroid = centroid_list
            ent.count = cluster_counts[cid]
            dr._dirty = True
        else:
            dr.register_from_centroid(
                name=name, centroid=centroid_list,
                count=cluster_counts[cid],
            )
    dr._save()
    print(f"  DomainRegistry updated: {dr.count} entities")

    # Update ChromaDB metadata
    update_batch = 500
    batch_ids: list[str] = []
    batch_md: list[dict] = []
    updated = 0

    for i in range(len(all_ids)):
        cid = int(labels[i])
        batch_ids.append(all_ids[i])
        batch_md.append({
            "cluster_id": cid,
            "cluster_name": CLUSTER_NAMES[cid],
        })
        if len(batch_ids) >= update_batch:
            collection.update(ids=batch_ids, metadatas=batch_md)
            updated += len(batch_ids)
            batch_ids, batch_md = [], []
            print(f"  Updated {updated}/{len(all_ids)}", end="\r", flush=True)

    if batch_ids:
        collection.update(ids=batch_ids, metadatas=batch_md)
        updated += len(batch_ids)

    print(f"\n  ChromaDB updated: {updated} chunks")

    # Save flywheel log
    log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_chunks": len(all_ids),
        "max_shift": max_shift,
        "shifts": shifts,
        "cluster_counts": cluster_counts,
        "updated": args.force or max_shift >= args.threshold,
    }
    log_dir = get_config().data_dir / "flywheel"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"centroid_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)
    print(f"  Log saved: {log_path}")

    print(f"\n✅ Flywheel complete.")
    print(f"  Centroid shift: {max_shift:.4f} (max)")
    print(f"  Domains: {dr.count}")
    print(f"  Chunks: {updated}")


if __name__ == "__main__":
    main()
