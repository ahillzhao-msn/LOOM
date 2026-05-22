"""
KAFED Analyzer — Benchmark
語義評分工具：用 embedding 相似度計算回答與期望概念的匹配程度。
"""

from typing import List

import numpy as np
from numpy import dot
from numpy.linalg import norm

try:
    from kafed.knowledge.rag.embedding import get_model
except ImportError:
    def get_model():
        return None


def benchmark_similarity(response: str, expected_concepts: List[str]) -> float:
    """用 embedding 相似度計算回答與期望概念的匹配程度。

    Args:
        response: 模型回答文本
        expected_concepts: 期望出現的概念列表

    Returns:
        0~1 的相似度分數
    """
    model = get_model()
    if model is None:
        return 0.0

    texts = [response[:512]] + [c[:128] for c in expected_concepts]
    embeddings = model.encode(texts, show_progress_bar=False)
    resp_vec = embeddings[0]
    concept_vecs = embeddings[1:]

    scores = []
    for cv in concept_vecs:
        sim = float(dot(resp_vec, cv) / (norm(resp_vec) * norm(cv)))
        scores.append(max(0, (sim + 1) / 2))

    return sum(scores) / len(scores) if scores else 0.0
