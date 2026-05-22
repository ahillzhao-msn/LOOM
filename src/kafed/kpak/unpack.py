"""
知识包导入 — 将 .kpak 解压并导入向量库。

导入流程:
  1. 解压 .kpak
  2. 验证 manifest 兼容性
  3. 读取 knowledge_units，逐条嵌入 + 存入向量库
  4. 合并 centroid（与已有 centroid 加权平均）
"""
from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from ..server.app.config import KafedConfig
    from ..server.app.vector_store import VectorStore

logger = logging.getLogger("kafed.kpak.unpack")


def unpack_kpak(kpak_path: str | Path, vector_store: "VectorStore",
                config: "KafedConfig") -> dict:
    """导入 .kpak 到向量库。

    Returns:
        { "domain": str, "imported": int, "merged_centroid": bool }
    """
    kpak_path = Path(kpak_path)
    if not kpak_path.exists():
        raise FileNotFoundError(f"知识包不存在: {kpak_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # 解压
        with zipfile.ZipFile(kpak_path, "r") as zf:
            zf.extractall(tmp)

        # 读取 manifest
        with open(tmp / "manifest.json") as f:
            manifest: dict = json.load(f)

        domain = manifest["domain"]
        expected_dim = manifest.get("embedding_dim", 384)

        # 读取知识单元
        units: list[dict] = []
        with open(tmp / "knowledge_units.jsonl") as f:
            for line in f:
                line = line.strip()
                if line:
                    units.append(json.loads(line))

        if not units:
            raise ValueError(f"知识包 '{kpak_path.name}' 为空")

        # 嵌入 + 写入向量库
        texts = [u["content"] for u in units]
        metadatas = [
            {
                **(u.get("metadata", {}) or {}),
                "domain": domain,
                "origin_kpak": kpak_path.name,
            }
            for u in units
        ]
        ids = vector_store.add(texts, metadatas)

        # 合并 centroid
        merged = False
        centroid_path = tmp / "centroid.npy"
        if centroid_path.exists():
            try:
                new_centroid = np.load(centroid_path)
                if new_centroid.shape[0] == expected_dim:
                    _merge_centroid(domain, new_centroid, len(units), config)
                    merged = True
            except Exception as e:
                logger.warning("合并 centroid 失败: %s", e)

        return {
            "domain": domain,
            "imported": len(units),
            "merged_centroid": merged,
        }


def _merge_centroid(domain: str, new_centroid: np.ndarray,
                    new_count: int, config: "KafedConfig") -> None:
    """加权合并 centroid。"""
    centroid_path = config.data_dir / "centroids.json"
    if centroid_path.exists():
        with open(centroid_path) as f:
            centroids: dict = json.load(f)
    else:
        centroids = {}

    if domain in centroids:
        old = np.array(centroids[domain]["centroid"])
        old_count = centroids[domain]["count"]
        # 加权平均
        total = old_count + new_count
        merged = (old * old_count + new_centroid * new_count) / total
        centroids[domain] = {
            "centroid": merged.tolist(),
            "count": total,
        }
    else:
        centroids[domain] = {
            "centroid": new_centroid.tolist(),
            "count": new_count,
        }

    with open(centroid_path, "w") as f:
        json.dump(centroids, f, ensure_ascii=False, indent=2)

    logger.info("Centroid 已合并: %s (total=%d)", domain,
                centroids[domain]["count"])
