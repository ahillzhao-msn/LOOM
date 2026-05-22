"""
知识包导出 — 将向量库中的域打包为 .kpak。

.kpak  = zip 文件:
  manifest.json            — { version, domain, entry_count, embedding_model, created_at }
  knowledge_units.jsonl    — { content, metadata } 每行
  centroid.npy             — 384-dim float32 centroid 向量（可选）
  seed_rules.yaml          — 可选，bootstrap 正则规则

用法:
    from kafed.kpak.pack import pack_domain
    path = pack_domain("SAP_PM")  # → ~/.kafed/data/kpak/SAP_PM.kpak
"""

from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from kafed.config import get_config

logger = logging.getLogger("kafed.kpak.pack")


def pack_domain(
    domain: str,
    output_dir: str | Path | None = None,
    include_centroid: bool = True,
    include_seed_rules: bool = False,
) -> Path:
    """将指定域打包为 .kpak 文件。

    Args:
        domain: 域名（如 SAP_PM）
        output_dir: 输出目录，默认 config.kpak_dir
        include_centroid: 是否包含 centroid 向量
        include_seed_rules: 是否从 config 路径复制 seed_rules

    Returns:
        生成的 .kpak 文件路径

    Raises:
        ValueError: 域为空或数据不存在
        ImportError: 向量库未配置
    """
    cfg = get_config()
    output_dir = Path(output_dir or cfg.kpak_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    kpak_path = output_dir / f"{domain}.kpak"

    # 加载向量库（延迟导入，避免循环依赖）
    from kafed.knowledge.rag.vector_store import VectorStore

    vs = VectorStore()
    data = vs.get_by_domain(domain)
    documents: list[str] = data.get("documents", []) or []
    metadatas: list[dict] = data.get("metadatas", []) or []
    ids: list[str] = data.get("ids", []) or []

    if not documents:
        raise ValueError(f"域 '{domain}' 没有数据")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # manifest
        manifest = {
            "kpak_version": 2,
            "domain": domain,
            "entry_count": len(documents),
            "embedding_model": cfg.embedding_model,
            "embedding_dim": cfg.embedding_dim,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "has_centroid": include_centroid,
        }
        with open(tmp / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # knowledge units
        with open(tmp / "knowledge_units.jsonl", "w", encoding="utf-8") as f:
            for i, doc in enumerate(documents):
                unit = {
                    "id": ids[i] if i < len(ids) else f"{domain}_{i}",
                    "content": doc,
                    "metadata": metadatas[i] if i < len(metadatas) else {},
                }
                f.write(json.dumps(unit, ensure_ascii=False) + "\n")

        # centroid（可选）
        if include_centroid:
            try:
                from kafed.knowledge.classify.classify import build_centroids_from_labels
                centroids = build_centroids_from_labels()
                if domain in centroids:
                    vec = np.array(centroids[domain]["centroid"], dtype=np.float32)
                    np.save(tmp / "centroid.npy", vec)
            except Exception:
                logger.warning("centroid 計算失敗，跳過")

        # seed_rules（可选）
        if include_seed_rules and cfg.seed_patterns_path:
            sp = cfg.seed_patterns_path
            if sp.exists():
                import shutil
                shutil.copy2(sp, tmp / "seed_rules.yaml")

        # 打包
        with zipfile.ZipFile(kpak_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in tmp.iterdir():
                zf.write(item, item.name)

    logger.info(
        "域 %s 打包完成: %d 條, %s",
        domain, len(documents), kpak_path,
    )
    return kpak_path


def list_kpak(output_dir: str | Path | None = None) -> list[dict]:
    """列出所有可用的 .kpak 包。

    Returns:
        [{"domain": str, "entries": int, "created": str, "path": str}, ...]
    """
    cfg = get_config()
    output_dir = Path(output_dir or cfg.kpak_dir)
    if not output_dir.exists():
        return []

    results = []
    for f in sorted(output_dir.glob("*.kpak")):
        try:
            with zipfile.ZipFile(f, "r") as zf:
                manifest = json.loads(zf.read("manifest.json"))
            results.append({
                "domain": manifest.get("domain", f.stem),
                "entries": manifest.get("entry_count", 0),
                "created": manifest.get("created_at", ""),
                "path": str(f),
            })
        except Exception:
            results.append({"domain": f.stem, "entries": 0, "path": str(f)})
    return results
