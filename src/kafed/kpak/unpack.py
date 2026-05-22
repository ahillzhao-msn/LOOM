"""
知识包导入 — 将 .kpak 解压并导入向量库。

导入流程:
  1. 解压 .kpak
  2. 验证 manifest 兼容性（embedding_dim）
  3. 读取 knowledge_units，逐条嵌入 + 存入向量库
  4. 合并 centroid（与已有 centroid 加权平均）

用法:
    from kafed.kpak.unpack import unpack_kpak
    result = unpack_kpak("SAP_PM.kpak")
    # → {"domain": "SAP_PM", "imported": 150, "merged_centroid": True}
"""

from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from kafed.config import get_config

logger = logging.getLogger("kafed.kpak.unpack")


def unpack_kpak(kpak_path: str | Path) -> dict:
    """导入 .kpak 到向量库。

    Args:
        kpak_path: .kpak 文件路径

    Returns:
        {"domain": str, "imported": int, "merged_centroid": bool}

    Raises:
        FileNotFoundError: .kpak 不存在
        ValueError: manifest 不兼容
    """
    kpak_path = Path(kpak_path)
    if not kpak_path.exists():
        raise FileNotFoundError(f"知识包不存在: {kpak_path}")

    cfg = get_config()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # 解压
        with zipfile.ZipFile(kpak_path, "r") as zf:
            zf.extractall(tmp)

        # 读取 manifest
        with open(tmp / "manifest.json") as f:
            manifest: dict = json.load(f)

        domain = manifest["domain"]
        kpak_version = manifest.get("kpak_version", 1)
        expected_dim = manifest.get("embedding_dim", 384)

        # 验证兼容性
        if expected_dim != cfg.embedding_dim:
            raise ValueError(
                f"嵌入维度不兼容: .kpak={expected_dim}, "
                f"当前配置={cfg.embedding_dim}"
            )

        # 读取知识单元
        units: list[dict] = []
        with open(tmp / "knowledge_units.jsonl") as f:
            for line in f:
                line = line.strip()
                if line:
                    units.append(json.loads(line))

        if not units:
            raise ValueError(f"知识包 {kpak_path} 中没有知识单元")

        # 嵌入 + 存入向量库
        from kafed.knowledge.rag.vector_store import VectorStore

        vs = VectorStore()

        chunk_size = 100
        imported = 0
        for i in range(0, len(units), chunk_size):
            batch = units[i:i + chunk_size]
            texts = [u["content"] for u in batch]
            metadatas = [
                {**u.get("metadata", {}), "domain": domain, "source": kpak_path.name}
                for u in batch
            ]
            ids = [f"{domain}_kpak_{u.get('id', f'{i}_{j}')}"
                   for j, u in enumerate(batch)]

            vs.add(texts, metadatas=metadatas, ids=ids)
            imported += len(texts)

        # 合并 centroid（可选）
        merged_centroid = False
        centroid_path = tmp / "centroid.npy"
        if centroid_path.exists():
            try:
                new_vec = np.load(centroid_path)
                # 加载已有 centroids
                centroids_path = cfg.data_dir / cfg.centroids_filename
                if centroids_path.exists():
                    with open(centroids_path) as f:
                        centroids = json.load(f)
                else:
                    centroids = {}

                if domain in centroids:
                    old_vec = np.array(centroids[domain]["centroid"], dtype=np.float32)
                    old_count = centroids[domain].get("count", 1)
                    # 加权平均：旧 centroid * 旧比重 + 新 centroid * 新比重
                    new_count = imported
                    total = old_count + new_count
                    merged = (old_vec * old_count + new_vec * new_count) / total
                    centroids[domain] = {
                        "centroid": merged.tolist(),
                        "count": total,
                    }
                else:
                    centroids[domain] = {
                        "centroid": new_vec.tolist(),
                        "count": imported,
                    }

                # 写回
                centroids_path.parent.mkdir(parents=True, exist_ok=True)
                with open(centroids_path, "w") as f:
                    json.dump(centroids, f, ensure_ascii=False, indent=2)
                merged_centroid = True
            except Exception:
                logger.warning("centroid 合并失败，跳過")

    logger.info(
        "域 %s 导入完成: %d 条, centroid 合并=%s",
        domain, imported, merged_centroid,
    )
    return {
        "domain": domain,
        "imported": imported,
        "merged_centroid": merged_centroid,
    }
