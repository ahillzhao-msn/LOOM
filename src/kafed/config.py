"""
KAFED 配置模块。

所有可调参数通过环境变量注入，零硬编码。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class KafedConfig:
    """KAFED 运行时配置。所有值可被环境变量覆盖。"""

    # ── 路径 ──────────────────────────────────────────────
    data_dir: Path = Path(
        os.getenv(
            "KAFED_DATA_DIR",
            str(Path(__file__).resolve().parent.parent.parent.parent / "data"),
        )
    )

    @property
    def chroma_path(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def feedback_dir(self) -> Path:
        return self.data_dir / "feedback_logs"

    @property
    def kpak_dir(self) -> Path:
        return self.data_dir / "kpak"

    # ── 嵌入模型 ──────────────────────────────────────────
    embedding_model: str = os.getenv("KAFED_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    embedding_dim: int = int(os.getenv("KAFED_EMBEDDING_DIM", "384"))

    # ── Chroma ────────────────────────────────────────────
    chroma_collection: str = os.getenv("KAFED_CHROMA_COLLECTION", "kafed_knowledge")

    # ── 分块 ──────────────────────────────────────────────
    chunk_max_chars: int = int(os.getenv("KAFED_CHUNK_MAX_CHARS", "500"))
    chunk_overlap: int = int(os.getenv("KAFED_CHUNK_OVERLAP", "50"))

    # ── 检索 ──────────────────────────────────────────────
    top_k_default: int = int(os.getenv("KAFED_TOP_K_DEFAULT", "5"))

    # ── 飞轮级联阈值 ──────────────────────────────────────
    e1_thresholds: str = os.getenv("KAFED_E1_THRESHOLDS", "10,50,100,200,500,1000")
    e2_drift_min: float = float(os.getenv("KAFED_E2_DRIFT_MIN", "0.05"))
    e3_min_entries: int = int(os.getenv("KAFED_E3_MIN_ENTRIES", "200"))
    e3_repack_growth_pct: float = float(os.getenv("KAFED_E3_REPACK_GROWTH", "30.0"))
    e4_dedup_threshold: float = float(os.getenv("KAFED_E4_DEDUP_THRESHOLD", "0.95"))
    e5_stale_days: int = int(os.getenv("KAFED_E5_STALE_DAYS", "90"))

    # ── 服务 ──────────────────────────────────────────────
    host: str = os.getenv("KAFED_HOST", "0.0.0.0")
    port: int = int(os.getenv("KAFED_PORT", "8765"))

    # ── 分類（非必需，無 = 只用 centroids）──────────────
    seed_patterns_path: str | None = os.getenv("KAFED_SEED_PATTERNS_PATH") or None


# ── 全局单例（FastAPI startup 时初始化） ────────────────
_config: KafedConfig | None = None


def get_config() -> KafedConfig:
    """返回全局配置单例。"""
    global _config
    if _config is None:
        _config = KafedConfig()
        for d in [_config.chroma_path, _config.feedback_dir, _config.kpak_dir]:
            d.mkdir(parents=True, exist_ok=True)
    return _config
