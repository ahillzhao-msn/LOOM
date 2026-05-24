#!/usr/bin/env python3
"""
Phase 4: 將 cluster_id 寫回 ChromaDB metadata。

用法:
  cd ~/KAFED && source .venv/bin/activate
  python3 scripts/update_cluster_metadata.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

sys.stdout.reconfigure(line_buffering=True)

from kafed.config import get_config
from kafed.knowledge.rag.vector_store import VectorStore


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
    parser = argparse.ArgumentParser(description="Update ChromaDB cluster metadata")
    parser.add_argument("--dry-run", action="store_true", help="审核，不更新")
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 4: Update ChromaDB Cluster Metadata")
    print("=" * 60)

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

    print(f"\n  Loaded {len(all_ids)} chunks, shape ({len(all_ids)}, {len(all_embeddings[0])})")

    print("\n[2/4] Reproducing KMeans clustering...")
    from sklearn.cluster import MiniBatchKMeans

    embeddings = np.array(all_embeddings, dtype=np.float32)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    emb_norm = embeddings / norms

    kmeans = MiniBatchKMeans(n_clusters=8, random_state=42,
                              batch_size=1024, n_init='auto', max_iter=200)
    t0 = time.time()
    labels = kmeans.fit_predict(emb_norm)
    print(f"  Clustered in {time.time() - t0:.1f}s")

    print("\n[3/4] Cluster distribution:")
    for cid in range(8):
        count = int((labels == cid).sum())
        print(f"  [{cid}] {CLUSTER_NAMES[cid]:40s} {count:>5d} chunks")

    if args.dry_run:
        print("\n[Dry-run] — 不下寫。")
        print("如需寫入，去掉 --dry-run 後執行。")
        return

    print("\n[4/4] Updating ChromaDB metadata (via update) ...")
    updates_done = 0
    batch_start = 0
    while batch_start < len(all_ids):
        batch_end = min(batch_start + batch_size, len(all_ids))
        batch_ids = all_ids[batch_start:batch_end]
        batch_metadatas = [
            {"cluster_id": int(labels[i]),
             "cluster_name": CLUSTER_NAMES[int(labels[i])]}
            for i in range(batch_start, batch_end)
        ]
        collection.update(ids=batch_ids, metadatas=batch_metadatas)
        updates_done += batch_end - batch_start
        batch_start = batch_end
        print(f"  Updated {updates_done}/{len(all_ids)}", end="\r", flush=True)
        time.sleep(0.05)

    print(f"\n  Done. {updates_done} chunks updated.")

    # Verify
    sample = collection.get(limit=5, include=["metadatas"])
    print("\n  Sample metadata:")
    for i, md in enumerate(sample["metadatas"]):
        cid = md.get("cluster_id", "?") if md else "?"
        cname = md.get("cluster_name", "?") if md else "?"
        print(f"    {i}: cluster_id={cid}, cluster_name={cname}")

    print(f"\n✅ Phase 4 Complete — {updates_done} chunks labeled with cluster_id.")


if __name__ == "__main__":
    main()
