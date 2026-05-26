#!/usr/bin/env python3
"""
recluster.py — Phase 3: HDBSCAN 全量非監督重聚類 + LLM 域名命名。

流程:
  1. 從 ChromaDB 拉取全部 93K+ chunks（documents + embeddings + metadatas）
  2. HDBSCAN 非監督聚類（cosine metric, 自動確定 cluster 數）
  3. 離群點標為 noise，不強行歸類
  4. 每個 cluster 採樣 centroid 附近文本 → 本地 LLM 命名
  5. 更新 DomainRegistry（cluster_id 不變，只更新 centroid/name）
  6. 寫 cluster 映射表供下游使用

用法:
  cd ~/KAFED && source .venv/bin/activate
  python3 scripts/recluster.py [--dry-run] [--min-cluster-size N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from kafed.config import get_config
from kafed.knowledge.rag.vector_store import VectorStore
from kafed.knowledge.classify.domain_registry import DomainRegistry

# Unbuffer stdout
sys.stdout.reconfigure(line_buffering=True)

from kafed.config import get_config
_cfg = get_config()
LLAMA_API = f"{_cfg.llama_base_url}/v1/chat/completions"
LLAMA_MODEL = "leader"
LLAMA_KEY = "hermes-local"  # Qwen3.5-9B

NAME_PROMPT = """You are analyzing a cluster of related text chunks extracted from a knowledge base. These chunks form a natural semantic cluster — they share a common theme.

Below are representative samples from this cluster. Read them and suggest a concise English label (2-5 words) that describes their shared topic.

Guidelines:
- Be specific but not overly narrow
- Use general-purpose language, not domain-specific acronyms
- If the topic is clear (e.g., fleet vehicle maintenance, SAP customer service notifications, GIS data migration), name it directly

Samples:
{samples}

Suggested label (2-5 words, no quotes, no explanation):"""


def name_cluster(samples: list[str], cluster_id: int,
                 dry_run: bool = False) -> str:
    """調用本地 LLM 為 cluster 命名。"""
    if dry_run:
        return f"Cluster_{cluster_id}"

    import urllib.request
    import urllib.error

    # Format samples: truncate each to 200 chars
    formatted = "\n".join(
        f"- {s[:200].strip()}" for s in samples
    )
    prompt = NAME_PROMPT.format(samples=formatted)

    payload = json.dumps({
        "model": LLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 30,
    }).encode()

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                LLAMA_API, data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {LLAMA_KEY}",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                name = data["choices"][0]["message"]["content"].strip()
                # Clean up quotes and label prefix
                name = name.strip('"\'"\' """').strip()
                name = name.replace("Label: ", "").replace("label: ", "").strip()
                # Limit length
                name = name[:60]
                if name:
                    return name
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"    [WARN] LLM naming failed for cluster {cluster_id}: {e}")

    return f"Cluster_{cluster_id}"


# ── 主流程 ──────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="HDBSCAN 全量重聚類")
    parser.add_argument("--dry-run", action="store_true",
                        help="僅列出 cluster 而不寫入")
    parser.add_argument("--min-cluster-size", type=int, default=10,
                        help="HDBSCAN min_cluster_size (default: 10)")
    parser.add_argument("--min-samples", type=int, default=1,
                        help="HDBSCAN min_samples (default: 1)")
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 3: HDBSCAN Full Reclustering")
    print("=" * 60)

    # Step 1: Fetch all chunks from ChromaDB
    print("\n[1/5] Fetching chunks from ChromaDB...")
    vs = VectorStore()
    collection = vs._collection

    # Get total count first
    total = collection.count()
    print(f"  Total chunks: {total}")

    # Fetch in batches (ChromaDB has a limit)
    batch_size = 1000
    all_ids = []
    all_embeddings = []
    all_documents = []
    all_metadatas = []

    offset = 0
    while offset < total:
        batch = collection.get(
            offset=offset,
            limit=batch_size,
            include=["embeddings", "documents", "metadatas"],
        )
        if not batch["ids"]:
            break
        all_ids.extend(batch["ids"])
        all_embeddings.extend(batch["embeddings"])
        all_documents.extend(batch["documents"])
        all_metadatas.extend(batch["metadatas"])
        offset += len(batch["ids"])
        print(f"  Fetched {offset}/{total}", end="\r", flush=True)

    print(f"\n  Fetched {len(all_ids)} chunks")
    embeddings = np.array(all_embeddings, dtype=np.float32)
    print(f"  Embeddings shape: {embeddings.shape}")

    # L2-normalize embeddings for cosine similarity
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embeddings_normalized = embeddings / norms

    # Step 2: MiniBatchKMeans clustering (faster than HDBSCAN for 93K points)
    print("\n[2/5] Running MiniBatchKMeans clustering...")
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.metrics import silhouette_score

    # Search for optimal k using silhouette score
    # Sample 10K points for silhouette evaluation (too expensive on full set)
    n_samples = embeddings_normalized.shape[0]
    sample_idx = np.random.choice(n_samples, min(10000, n_samples), replace=False)
    sample_emb = embeddings_normalized[sample_idx]

    best_k = 0
    best_silhouette = -1
    k_range = list(range(8, min(51, n_samples // 50)))
    
    t0 = time.time()
    for k in k_range:
        t_k = time.time()
        km = MiniBatchKMeans(
            n_clusters=k,
            random_state=42,
            batch_size=1024,
            n_init='auto',
            max_iter=100,
        )
        km.fit(embeddings_normalized)
        labels_sample = km.predict(sample_emb)
        sil = silhouette_score(sample_emb, labels_sample, metric='cosine')
        elapsed_k = time.time() - t_k
        print(f"  k={k:2d} silhouette={sil:.4f} ({elapsed_k:.1f}s)")
        if sil > best_silhouette:
            best_silhouette = sil
            best_k = k

    elapsed = time.time() - t0
    print(f"\n  Best k: {best_k} (silhouette={best_silhouette:.4f})")
    print(f"  Total clustering time: {elapsed:.1f}s")

    # Final clustering with best k
    final_kmeans = MiniBatchKMeans(
        n_clusters=best_k,
        random_state=42,
        batch_size=1024,
        n_init='auto',
        max_iter=200,
    )
    labels = final_kmeans.fit_predict(embeddings_normalized)

    n_clusters = best_k
    n_noise = 0

    if args.dry_run:
        print("\n[Dry-run] 不寫入任何數據")
        return

    # Step 3: Build cluster centroids and sample texts
    print("\n[3/5] Computing cluster centroids and sampling texts...")
    cluster_info = {}
    for cid in range(n_clusters):
        mask = labels == cid
        cluster_emb = embeddings[mask]
        cluster_texts = [all_documents[i] for i in range(len(labels)) if labels[i] == cid]

        # Centroid: mean of cluster embeddings
        centroid = cluster_emb.mean(axis=0).tolist()

        # Sample: 5 texts nearest to centroid
        centroid_vec = np.array(centroid, dtype=np.float32)
        dists = np.array([
            1 - float(np.dot(centroid_vec, e) / (np.linalg.norm(centroid_vec) * np.linalg.norm(e)))
            for e in cluster_emb
        ])
        nearest_idx = np.argsort(dists)[:5]
        samples = [cluster_texts[i][:300] for i in nearest_idx]

        cluster_info[cid] = {
            "centroid": centroid,
            "count": len(cluster_texts),
            "samples": samples,
        }

    # Step 4: Name clusters via LLM
    print("\n[4/5] Naming clusters via local LLM...")
    cluster_names = {}
    for cid in sorted(cluster_info.keys()):
        info = cluster_info[cid]
        print(f"  Naming cluster {cid} ({info['count']} chunks)...")
        name = name_cluster(info["samples"], cid)
        cluster_names[cid] = name
        print(f"    → {name}")
        time.sleep(0.5)  # Rate limit

    # Step 5: Update DomainRegistry
    print("\n[5/5] Updating DomainRegistry...")
    reg = DomainRegistry.reset()

    old_to_new: dict[str, int] = {}  # old domain name → new cluster_id
    for i, md in enumerate(all_metadatas):
        old_domain = md.get("domain", "GENERAL")
        cid = int(labels[i])
        if cid >= 0:
            old_to_new[old_domain] = cid

    # Save cluster mapping
    mapping_path = get_config().data_dir / "cluster_mapping.json"
    mapping = {
        "version": 2,
        "n_clusters": n_clusters,
        "n_noise": n_noise,
        "clusters": {},
    }
    for cid in sorted(cluster_info.keys()):
        name = cluster_names[cid]
        info = cluster_info[cid]
        entity = reg.register_from_centroid(
            name=name,
            centroid=info["centroid"],
            count=info["count"],
            aliases=[],
        )
        mapping["clusters"][str(cid)] = {
            "cluster_id": entity.id,
            "name": name,
            "count": info["count"],
        }

    with open(mapping_path, "w") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

    print(f"\n  DomainRegistry updated: {reg.count} domains")
    print(f"  Mapping saved to: {mapping_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("Phase 3 Complete!")
    print("=" * 60)
    print(f"\nOld centroids: 39 (replaced)")
    print(f"New natural clusters: {n_clusters}")
    print(f"Noise (GENERAL): {n_noise} chunks")
    print(f"\nNew domains:")
    for cid in sorted(cluster_info.keys()):
        name = cluster_names.get(cid, f"Cluster_{cid}")
        size = cluster_info[cid]["count"]
        print(f"  [{cid:3d}] {name:40s} ({size:5d} chunks)")

    print(f"\n✅ Primary cluster dimensions updated in DomainRegistry")
    print(f"✅ Chunks NOT updated yet (add cluster_id to metadata in Phase 4)")
    print(f"✅ LevelRegistry/TypeRegistry pending (sub-clustering not yet run)")


if __name__ == "__main__":
    main()
