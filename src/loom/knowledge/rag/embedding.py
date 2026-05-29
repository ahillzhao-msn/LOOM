"""
嵌入模块 — bge-small-en-v1.5 封装。

全局单例模型，延迟加载。纯文本嵌入，零领域注入。
"""
from __future__ import annotations

from sentence_transformers import SentenceTransformer

from loom.config import get_config

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """返回嵌入模型单例。首次调用时加载。自动检测 CUDA GPU。"""
    global _model
    if _model is None:
        cfg = get_config()
        _model = SentenceTransformer(cfg.embedding_model)
        try:
            import torch
            if torch.cuda.is_available():
                _model = _model.to("cuda")
        except ImportError:
            pass
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """将文本列表嵌入为浮点向量列表。"""
    model = get_model()
    return model.encode(texts, show_progress_bar=False).tolist()


def embed_query(text: str) -> list[float]:
    """嵌入单条查询文本。"""
    return embed_texts([text])[0]
