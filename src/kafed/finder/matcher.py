"""
KAFED Finder — 模型匹配與路由核心數據結構。

模型元數據 Schema（全量公開屬性，一次性定義）：
  新增屬性只需在 MODEL_META_SCHEMA 加一行，嵌入描述自動生成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


# ══════════════════════════════════════════════════════
# 模型元數據 Schema
# ══════════════════════════════════════════════════════

MODEL_META_SCHEMA = {
    # ── 身份 ──
    "name":           (str,   ""),          # 模型名 (worker_md1)
    "provider":       (str,   "local"),     # 服務商 (local/deepseek/anthropic)
    "model_id":       (str,   ""),          # API 調用用 ID

    # ── 容量 ──
    "context_window": (int,   16384),       # 最大上下文 (tokens)
    "max_tokens":     (int,   0),           # 最大生成长度 (0=同 context_window)

    # ── 生成參數默認值 ──
    "temperature":    (float, 0.6),         # 採樣溫度
    "top_p":          (float, 0.9),         # 核採樣
    "top_k":          (int,   40),          # top-k (0=關閉)
    "repeat_penalty": (float, 1.1),         # 重複懲罰

    # ── 能力 ──
    "supports_reasoning": (bool, False),    # 推理能力
    "supports_vision":    (bool, False),    # 視覺輸入
    "supports_functions": (bool, False),    # 工具調用

    # ── 性能與成本 ──
    "tps":            (int,   0),           # tokens/秒 (估算)
    "cost_per_token": (float, 0.0),         # USD/token (本地=0)

    # ── 狀態 ──
    "is_online":      (bool,  True),
}


def meta_keys() -> list[str]:
    """返回 schema 中所有鍵名（按定義順序）。"""
    return list(MODEL_META_SCHEMA.keys())


def meta_defaults() -> dict:
    """返回 schema 默認值字典。"""
    return {k: v[1] for k, v in MODEL_META_SCHEMA.items()}


def build_meta_description(meta: dict) -> str:
    """從 schema 遍歷，自動生成嵌入描述文本。

    只包含非默認值 + 關鍵標識字段，避免噪聲。
    新增 schema 字段後不需改此函數。
    """
    defaults = meta_defaults()
    parts = []
    # 身份字段始終包含
    for k in ("name", "provider", "model_id"):
        v = meta.get(k, "")
        if v:
            parts.append(f"{k}={v}")
    # 非默認值字段
    for k, v in meta.items():
        if k in ("name", "provider", "model_id", "embedding"):
            continue
        default = defaults.get(k)
        if isinstance(default, bool):
            if v:
                parts.append(f"{k}=yes")
        elif isinstance(v, (int, float)):
            if v != default and v != 0:
                parts.append(f"{k}={v}")
        elif v and v != default:
            parts.append(f"{k}={v}")
    return " | ".join(parts)


# ══════════════════════════════════════════════════════
# 數據結構
# ══════════════════════════════════════════════════════


@dataclass
class WorkerCandidate:
    """模型候選 — 基於 MODEL_META_SCHEMA。

    新增元屬性只需在 MODEL_META_SCHEMA 加一行，WorkerCandidate 通過 meta 字典承載。

    匹配流程：
      1. meta 從各來源（llama.cpp / config）填充
      2. build_meta_description() 生成描述文本 → embedding
      3. find_partners 用 cosine similarity（任務 ⊗ 模型向量）匹配
    """

    name: str
    provider: str = "local"
    model_id: str = ""

    # ── 元數據字典（承載 schema 所有字段 + 擴展）──
    meta: dict = field(default_factory=dict)

    # ── 匹配信息 ──
    match_score: float = 0.5
    domain: str = ""

    # ── 實時狀態 ──
    is_online: bool = True
    estimated_tps: int = 0
    status_vector: list[float] = field(default_factory=lambda: [1.0, 0.0, 0.0])

    # ── 語境調製 ──
    context_boost: float = 0.0

    # ── 歷史 ──
    total_calls: int = 0
    success_rate: float = 0.0
    last_selected: str = ""

    # ── 成本 ──
    is_free: bool = True
    cost_per_token: float = 0.0

    # ── 能力標籤（保留向後兼容）──
    capability_tags: list[str] = field(default_factory=list)

    # ── 嵌入（可選，避免重複查詢）──
    embedding: Optional[np.ndarray] = None

    # ── 上下文窗口（快捷訪問 meta['context_window']）──
    @property
    def context_window(self) -> int:
        return self.meta.get("context_window",
                             MODEL_META_SCHEMA["context_window"][1])

    @context_window.setter
    def context_window(self, value: int):
        self.meta["context_window"] = value

    # ── 推理能力快捷訪問 ──
    @property
    def supports_reasoning(self) -> bool:
        return self.meta.get("supports_reasoning", False)

    @property
    def supports_vision(self) -> bool:
        return self.meta.get("supports_vision", False)

    def describe(self) -> str:
        """人類可讀描述（無 emoji、無 ANSI）。"""
        status = "online" if self.is_online else "offline"
        cost = "free" if self.is_free else f"${self.cost_per_token:.6f}/tok"
        ctx = self.context_window
        caps = ",".join(self.capability_tags[:4]) if self.capability_tags else ""
        return (
            f"{'[+]' if self.is_online else '[-]'} {self.name:20s} | "
            f"{self.provider:12s} | ctx={ctx:<6} | score={self.match_score:.2f} | "
            f"{cost} | {caps}"
        )


@dataclass
class FindPartnersRequest:
    """find_partners 請求參數。"""
    task_brief: str
    budget: str = "any"          # free / low / any
    prefer_local: bool = False
    top_k: int = 5
    domain: Optional[str] = None

    # ContextSpace 輸入（可選）
    context_vec: Optional[list[float]] = None

    # 過濾條件
    min_match_score: float = 0.0
    require_online: bool = True


@dataclass
class FindPartnersResult:
    """find_partners 結果。"""
    request: FindPartnersRequest
    candidates: list[WorkerCandidate] = field(default_factory=list)
    total_candidates: int = 0
    match_method: str = "embedding"
    task_index: int = 0  # 在多 brief 中的序號

    # 路由路徑
    route_mode: str = "full"
    aggregation: dict[str, float] = field(default_factory=dict)

    def best(self) -> Optional[WorkerCandidate]:
        return self.candidates[0] if self.candidates else None

    def filter_by_budget(self, budget: str) -> list[WorkerCandidate]:
        if budget == "free":
            return [c for c in self.candidates if c.is_free]
        return self.candidates
