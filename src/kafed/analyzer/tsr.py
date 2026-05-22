"""
KAFED Analyzer — TSR (時空標尺)
嵌入空間維護工具。三層分析：L3 centroid 空間 → L2 entity 分布 → L1 消散特徵。
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from numpy import dot
from numpy.linalg import norm

# KAFED imports
try:
    from kafed.knowledge.classify.classify import load_centroids, load_labels
    from kafed.knowledge.rag.embedding import get_model
except ImportError:
    # During initial import testing without full KAFED stack
    def load_centroids():
        return {}
    def load_labels():
        return []
    def get_model():
        return None


class TSR:
    """時空標尺 — embedding 空間維護工具。

    使用 KAFED centroids 和 labels 做三層分析：
    - L3: Centroid 空間密度/相似度/合併建議
    - L2: Entity 域內凝聚度/離群點
    - L2↔L3: Centroid Drift 檢測
    - L1: Split-half cluster shift 驗證
    """

    def __init__(self):
        self.centroids = load_centroids()
        self.model = get_model() if self.centroids else None

    def analyze_centroids(self):
        """L3: Centroid 空間分析 — 密度、噪音、域間關係"""
        if not self.centroids:
            print("No centroids loaded")
            return

        names = list(self.centroids.keys())
        N = len(names)
        vecs = np.array([self.centroids[n]["centroid"] for n in names])
        counts = [self.centroids[n].get("count", 0) for n in names]

        print(f"\n{'='*65}")
        print(f"TSR L3 — Centroid 空間分析 | {N} domains | 384d embedding")
        print(f"{'='*65}")

        norms = vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-10)
        sim_matrix = norms @ norms.T
        D = np.clip(1 - sim_matrix, 0, 2)

        print(f"\n相似度矩陣: max={sim_matrix.max():.4f} min={sim_matrix.min():.4f} mean={sim_matrix.mean():.4f}")

        pairs = []
        for i in range(N):
            for j in range(i + 1, N):
                pairs.append((sim_matrix[i, j], names[i], names[j]))
        pairs.sort(reverse=True)

        print(f"\n最近 domain 對 (>0.5):")
        for sim, a, b in pairs:
            if sim > 0.5:
                print(f"  {a:16s} ↔ {b:16s}  sim={sim:.4f}")
            else:
                break

        density = np.sum(np.exp(-(D ** 2) / (2 * 0.3 ** 2)), axis=1)
        density_norm = density / N
        print(f"\n密度分布 (核密度, σ=0.3):")
        for i in np.argsort(density_norm):
            marker = "⚠ ISOLATED" if density_norm[i] < 0.3 else ""
            print(f"  {names[i]:16s} density={density_norm[i]:.4f} ({counts[i]} entities) {marker}")

        print(f"\n合併建議 (sim > 0.75, 同一上位域):")
        mergers = []
        for sim, a, b in pairs:
            if sim > 0.75 and _same_parent(a, b):
                mergers.append((a, b, sim))
        if mergers:
            for a, b, sim in mergers:
                print(f"  ＞ 考慮合併 {a} ↔ {b} (sim={sim:.4f})")
        else:
            print(f"  (無建議合併)")

        eigvals = np.linalg.eigvalsh(sim_matrix)
        eigvals = np.maximum(eigvals, 0)
        entropy = -np.sum(eigvals * np.log(np.maximum(eigvals, 1e-10)))
        print(f"\n空間多樣性熵: {entropy:.2f}")
        if entropy < 1.0:
            print(f"  ⚠ 多樣性偏低 — centroid 之間太近，可能過度分類")

        return sim_matrix

    def analyze_entities(self, domain: str = None):
        """L2: Entity 分布分析 — 域內凝聚度 + 離群點檢測"""
        labels = load_labels()
        if not labels:
            print("No labels loaded")
            return

        entities = [lb for lb in labels if lb.get("domain") == domain] if domain else labels
        groups = defaultdict(list)
        for lb in entities:
            groups[lb.get("domain", "GENERAL")].append(lb)

        print(f"\n{'='*65}")
        print(f"TSR L2 — Entity 分布分析 | {sum(len(v) for v in groups.values())} entities")
        print(f"{'='*65}")

        for d, grp in sorted(groups.items()):
            if len(grp) < 2:
                print(f"\n{d:16s}: 1 entity (無法計算分布)")
                continue

            texts = [e.get("text", "")[:512] for e in grp]
            vecs = self.model.encode(texts, show_progress_bar=False)

            norms = vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-10)
            sim = norms @ norms.T
            cohesion = (np.sum(sim) - len(grp)) / (len(grp) * (len(grp) - 1))

            centroid = vecs.mean(axis=0)
            cnorm = centroid / np.maximum(np.linalg.norm(centroid), 1e-10)
            distances = 1 - norms @ cnorm

            outliers = [
                (distances[j], grp[j].get("id", "?")[:30])
                for j in np.argsort(distances)[-3:]
                if distances[j] > 0.3
            ]

            print(f"\n{d:16s}: {len(grp)} entities, cohesion={cohesion:.4f}")
            if outliers:
                print(f"  ⚠ 離群點 (>0.3):")
                for dist, eid in outliers:
                    print(f"    dist={dist:.4f} {eid}")

    def analyze_drift(self):
        """L2↔L3: Centroid Drift — 對比當前 centroid 與 re-calc 的偏差"""
        labels = load_labels()
        if not labels or not self.centroids:
            print("Need both centroids and labels")
            return

        print(f"\n{'='*65}")
        print(f"TSR Drift — Centroid vs Entity-Calculated 偏差")
        print(f"{'='*65}")

        groups = defaultdict(list)
        for lb in labels:
            groups[lb.get("domain", "GENERAL")].append(lb.get("text", "")[:512])

        for domain, texts in sorted(groups.items()):
            if domain not in self.centroids or len(texts) < 2:
                continue
            cur = np.array(self.centroids[domain]["centroid"])
            vecs = self.model.encode(texts, show_progress_bar=False)
            recalc = vecs.mean(axis=0)
            drift = 1 - float(dot(cur, recalc) / (norm(cur) * norm(recalc)))
            marker = "⚠ NEED REBUILD" if drift > 0.05 else ""
            print(f"  {domain:16s} drift={drift:.4f} ({len(texts)} entities) {marker}")

    def analyze_cluster_shift(self, pre_labels_path=None, post_labels_path=None):
        """L1: Split-half cluster shift 穩定性驗證"""
        labels = load_labels()
        if not labels or not self.centroids:
            print("Need both centroids and labels")
            return

        if pre_labels_path or post_labels_path:
            print("External labels comparison not yet implemented")
            return

        print(f"\n{'='*65}")
        print(f"TSR Cluster Shift — Split-Half 穩定性驗證")
        print(f"{'='*65}")

        groups = defaultdict(list)
        for lb in labels:
            groups[lb.get("domain", "GENERAL")].append(lb.get("text", "")[:512])

        for domain, texts in sorted(groups.items()):
            if len(texts) < 4:
                continue
            half = len(texts) // 2
            vecs = self.model.encode(texts, show_progress_bar=False)
            shift = 1 - float(
                dot(vecs[:half].mean(axis=0), vecs[half:].mean(axis=0))
                / (norm(vecs[:half].mean(axis=0)) * norm(vecs[half:].mean(axis=0)))
            )
            marker = "⚠ UNSTABLE" if shift > 0.15 else ""
            print(f"  {domain:16s} split-half drift={shift:.4f} ({len(texts)} entities) {marker}")

    def demo(self):
        """快速演示 TSR 功能"""
        self.analyze_centroids()
        print()
        self.analyze_entities()
        print()
        self.analyze_drift()


def _same_parent(a: str, b: str) -> bool:
    prefixes = {"SAP_", "SAP"}
    return any(a.startswith(p) and b.startswith(p) for p in prefixes)
