"""ContextSpace — 短期動態嵌入空間。

每輪交互結束時，將用戶輸入、Director EVAL、YiCeNet 卦象等語境
嵌入並累積到一個向量緩衝區。find_partners 調用時，當前語境向量
與緩衝區做最近鄰，成功歷史中的模型獲得 context_boost。

磁碟持久化：通過 get_config().context_dir 配置。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from numpy import dot
from numpy.linalg import norm

from loom.config import get_config


class ContextSpace:
    """短期語境嵌入空間。

    用法:
        cs = ContextSpace()
        cs.record(context_vec, model_name, success=True)
        cs.record_batch(context_entries)
        boosts = cs.modulate(current_context_vec, candidates)
    """

    def __init__(self) -> None:
        self._cfg = get_config()
        self._max_entries: int = self._cfg.context_buffer_size
        self._ctx_dir = self._cfg.context_dir
        self._ctx_dir.mkdir(parents=True, exist_ok=True)
        self._buffer_path: Path = self._ctx_dir / self._cfg.context_buffer_filename
        self._buffer: list[dict] = []
        self._load()

    # ── 載入/保存 ──────────────────────────────────────

    def _load(self) -> None:
        """載入緩衝區（最多 max_entries 條）。"""
        if not self._buffer_path.exists():
            self._buffer = []
            return
        try:
            with open(self._buffer_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._buffer.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            # 裁減超出部分
            if len(self._buffer) > self._max_entries:
                self._buffer = self._buffer[-self._max_entries:]
        except Exception:
            self._buffer = []

    def _save(self) -> None:
        """寫入緩衝區（追加模式，保存時壓縮到 max_entries）。"""
        # 超出時淘汰最舊
        if len(self._buffer) > self._max_entries:
            self._buffer = self._buffer[-self._max_entries:]
        try:
            with open(self._buffer_path, "w") as f:
                for entry in self._buffer:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ── 記錄 ────────────────────────────────────────────

    def record(self, context_vec: list[float],
               model_name: str, success: bool = True,
               user_input: str = "", eval_info: str = "",
               hexagram_info: str = "") -> None:
        """記錄一次交互的語境向量和選擇結果。"""
        entry = {
            "context_vec": [round(v, 6) for v in context_vec],
            "model": model_name,
            "success": success,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if user_input:
            entry["input"] = user_input[:120]
        if eval_info:
            entry["eval"] = eval_info[:80]
        if hexagram_info:
            entry["hexagram"] = hexagram_info[:40]

        self._buffer.append(entry)
        self._save()

        from loom.flow import hop, stop
        hop("ctx", f"{model_name} {'+' if success else '-'}",
            detail=f"buf={len(self._buffer)}")

    def record_batch(self, entries: list[dict]) -> None:
        """批量記錄。每個 entry 必須含 context_vec 和 model。"""
        for e in entries:
            if "context_vec" in e and "model" in e:
                e["ts"] = e.get("ts", datetime.now(timezone.utc).isoformat())
                if "context_vec" in e and isinstance(e["context_vec"], list):
                    e["context_vec"] = [round(v, 6) for v in e["context_vec"]]
                self._buffer.append(e)
        self._save()

    # ── 調製 ────────────────────────────────────────────

    def modulate(self, current_vec: list[float],
                 candidates: list) -> dict[str, float]:
        """對當前語境，為每位候選模型計算 context_boost。

        Args:
            current_vec: 當前交互的語境向量（384d）
            candidates: WorkerCandidate 列表（用於 name 匹配）

        Returns:
            {model_name: boost_amount, ...}
        """
        if not self._buffer or not current_vec:
            return {}

        cfg = self._cfg
        boost_amount = cfg.context_boost_amount
        current = np.array(current_vec, dtype=np.float32)
        boosts: dict[str, float] = {}

        # 從緩衝區找出成功歷史
        successes = [e for e in self._buffer if e.get("success", True)]

        # 對每個成功條目，計算與當前語境的相似度
        recent_scores: list[tuple[str, float]] = []
        for entry in successes[-200:]:  # 只看最近 200 條（性能）
            cv = entry.get("context_vec")
            if not cv or len(cv) != len(current_vec):
                continue
            cv_arr = np.array(cv, dtype=np.float32)
            sim = float(dot(current, cv_arr) / (norm(current) * norm(cv_arr) + 1e-10))
            model = entry.get("model", "")
            if model:
                recent_scores.append((model, sim))

        # 對每個候選：最高相似度 Top-3 的平均值 → 決定是否 boost
        candidate_names = {c.name for c in candidates}
        for model_name in candidate_names:
            scores = [s for m, s in recent_scores if m == model_name]
            if len(scores) >= 2:
                top3 = sorted(scores, reverse=True)[:3]
                avg_sim = sum(top3) / len(top3)
                if avg_sim > 0.65:  # 相似度閾值
                    boost = boost_amount * min(1.0, avg_sim)
                    boosts[model_name] = round(boost, 4)

        return boosts

    # ── 統計與管理 ──────────────────────────────────────

    def size(self) -> int:
        return len(self._buffer)

    def count_by_model(self, model_name: str) -> int:
        return sum(1 for e in self._buffer if e.get("model") == model_name)

    def clear(self) -> None:
        """清空緩衝區（用於測試或重置）。"""
        self._buffer = []
        self._save()

    def recent(self, n: int = 10) -> list[dict]:
        """最近 n 條記錄。"""
        return self._buffer[-n:] if self._buffer else []
