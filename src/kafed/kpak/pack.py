"""
知识包导出 — 将向量库中的域打包为 .kpak。

.kpak  = zip 文件:
  manifest.json        — { version, domain, entry_count, embedding_model, created_at }
  knowledge_units.jsonl — { content, metadata } 每行
  centroid.npy          — 384-dim float32 centroid 向量
  seed_rules.yaml       — 可选，bootstrap 正则规则
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from ..server.app.config import KafedConfig
    from ..server.app.vector_store import VectorStore

logger = logging.getLogger("kafed.kpak.pack")


def pack_domain(domain: str, vector_store: "VectorStore",
                config: "KafedConfig",
                output_dir: str | Path | None = None) -> Path:
    """将指定域打包为 .kpak 文件。

    Returns:
        生成的 .kpak 文件路径
    """
    output_dir = Path(output_dir or config.kpak_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    kpak_path = output_dir / f"{domain}.kpak"

    # 读取域数据
    data = vector_store.get_by_domain(domain)
    documents = data.get("documents", []) or []
    metadatas = data.get("metadatas", []) or []
    ids = data.get("ids", []) or []

    if not documents:
        raise ValueError(f"域 '{domain}' 没有数据")

    # 计算 centroid (延迟导入，支持独立运行)
    try:
        from ..server.app.embedding import embed_texts as _embed
    except ImportError:
        # 独立运行（CLI / 测试）
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(config.embedding_model)
        def _embed(texts): return _model.encode(texts, show_progress_bar=False).tolist()

    vectors = _embed(documents)
    centroid = np.mean(vectors, axis=0).astype(np.float32)

    # 构建 manifest
    manifest = {
        "kafed_version": "1.0.0",
        "domain": domain,
        "entry_count": len(documents),
        "embedding_model": config.embedding_model,
        "embedding_dim": config.embedding_dim,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": f"KAFED 知识包: {domain}",
    }

    # 写入临时目录，然后压缩
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # manifest.json
        with open(tmp / "manifest.json", "w") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # knowledge_units.jsonl
        with open(tmp / "knowledge_units.jsonl", "w") as f:
            for doc, meta, doc_id in zip(documents, metadatas, ids):
                line = {
                    "id": doc_id,
                    "content": doc,
                    "metadata": meta,
                }
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

        # centroid.npy
        np.save(tmp / "centroid.npy", centroid)

        # 打包为 zip
        with zipfile.ZipFile(kpak_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in tmp.iterdir():
                zf.write(item, arcname=item.name)

    logger.info("知识包已打包: %s (%d 条目, %s)", kpak_path, len(documents), manifest["domain"])
    return kpak_path


def pack_by_count(vector_store: "VectorStore", config: "KafedConfig",
                  min_entries: int = 200) -> list[Path]:
    """将所有满足最低条目数的域打包。"""
    paths = []
    for domain in vector_store.list_domains():
        count = vector_store.count_by_domain(domain)
        if count >= min_entries:
            try:
                path = pack_domain(domain, vector_store, config)
                paths.append(path)
            except Exception as e:
                logger.warning("打包域 '%s' 失败: %s", domain, e)
    return paths
