"""EventChecker — 飞轮事件驱动的级联触发器。

E1: chunk 计数里程碑（10/50/100/200/500/1000）
E2: centroid 漂移检测（角距离变化 > 阈值）
E3: 域增长触发的重新打包（增长 > 30% 且 >= 200 条）
E4: 反馈触发的去重检查（相似度 > 0.95）
E5: 陈旧清理（90 天无访问）

所有状态持久化到 event_state.json。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from numpy import dot
from numpy.linalg import norm

from loom.config import get_config


class EventChecker:
    """飞轮事件检查器。每次 intake/feedback 后检查是否触发事件。"""

    def __init__(self, vector_store, rag_engine) -> None:
        self._vs = vector_store
        self._rag = rag_engine
        self._cfg = get_config()
        self._state_path: Path = self._cfg.data_dir / self._cfg.event_state_filename
        self._state: dict[str, Any] = self._load_state()

    # ── 状态管理 ──────────────────────────────────────

    def _load_state(self) -> dict[str, Any]:
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text())
            except Exception:
                pass
        return {"version": 2, "packed_domains": {}, "rebalanced_domains": {},
                "e5_last_check": None, "chunk_totals": {}, "last_centroid_domains": []}

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(self._state, indent=2, ensure_ascii=False))

    # ── 公开接口 ──────────────────────────────────────

    def after_ingest(self, domain: str, chunk_count: int) -> list[dict]:
        """摄入后检查 E1/E2/E3。返回触发的事件列表。"""
        events: list[dict] = []

        # 更新域总计数
        prev_total = self._state.get("chunk_totals", {}).get(domain, 0)
        new_total = self._vs.count_by_domain(domain)
        self._state.setdefault("chunk_totals", {})[domain] = new_total

        # E1: chunk 里程碑
        e1 = self._check_e1(domain, new_total)
        if e1:
            events.append(e1)

        # E2: centroid 漂移（隔 50 条以上检查一次）
        if new_total - prev_total >= 50 and domain in self._state.get("last_centroid_domains", []):
            e2 = self._check_e2(domain)
            if e2:
                events.append(e2)

        # E3: 增长触发的 repack
        e3 = self._check_e3(domain, new_total)
        if e3:
            events.append(e3)

        self._save_state()
        return events

    def after_feedback(self) -> list[dict]:
        """反馈后检查 E4（去重）。"""
        events: list[dict] = []
        e4 = self._check_e4()
        if e4:
            events.append(e4)
        self._save_state()
        return events

    # ── E1-E5 实现 ────────────────────────────────────

    def _check_e1(self, domain: str, count: int) -> dict | None:
        """Chunk 计数里程碑。"""
        try:
            thresholds = sorted(int(t) for t in self._cfg.e1_thresholds.split(","))
        except Exception:
            thresholds = [10, 50, 100, 200, 500, 1000]

        prev = self._state.get("chunk_totals", {}).get(domain, 0)
        crossed = [t for t in thresholds if prev < t <= count]
        if crossed:
            return {
                "event": "E1",
                "domain": domain,
                "milestones": crossed,
                "total": count,
                "action_hint": "centroid_rebuild" if max(crossed) >= 100 else "none",
            }
        return None

    def _check_e2(self, domain: str) -> dict | None:
        """域 centroid 漂移：比较当前 centroid 与上次记录的余弦角。"""
        cfg = self._cfg
        min_drift = cfg.e2_drift_min if hasattr(cfg, "e2_drift_min") else 0.05

        # 获取当前 centroid
        centroids_path = self._cfg.data_dir / self._cfg.centroids_filename
        if not centroids_path.exists():
            return None

        try:
            centroids = json.loads(centroids_path.read_text())
            if domain not in centroids or "centroid" not in centroids[domain]:
                return None

            current = np.array(centroids[domain]["centroid"], dtype=np.float32)

            # 用 LOOM embedding 模型重新生成单点 centroid 对比
            from loom.knowledge.rag.embedding import get_model
            model = get_model()
            samples = self._vs.get_by_domain(domain, limit=50)
            texts = samples.get("documents", [])
            if len(texts) < 5:
                return None

            new_vecs = model.encode(texts[:20], show_progress_bar=False)
            new_centroid = new_vecs.mean(axis=0)

            drift = float(1.0 - dot(current, new_centroid) / (norm(current) * norm(new_centroid)))
            if drift > min_drift:
                return {
                    "event": "E2",
                    "domain": domain,
                    "drift": round(drift, 4),
                    "action_hint": "centroid_rebuild",
                }
        except Exception:
            pass
        return None

    def _check_e3(self, domain: str, current_count: int) -> dict | None:
        """域增长触发的 repack：增长 > 30% 且 >= 200 条。"""
        packed = self._state.get("packed_domains", {}).get(domain)
        if not packed:
            return None

        cfg = self._cfg
        min_entries = cfg.e3_min_entries if hasattr(cfg, "e3_min_entries") else 200
        growth_pct = cfg.e3_repack_growth_pct if hasattr(cfg, "e3_repack_growth_pct") else 30.0

        if current_count < min_entries:
            return None

        count_at_pack = packed.get("count_at_pack", 0)
        if count_at_pack <= 0:
            return None

        growth = (current_count - count_at_pack) / count_at_pack * 100
        if growth > growth_pct:
            return {
                "event": "E3",
                "domain": domain,
                "growth_pct": round(growth, 1),
                "count_before": count_at_pack,
                "count_now": current_count,
                "action_hint": "kpak_repack",
            }
        return None

    def _check_e4(self) -> dict | None:
        """反馈触发的去重检查。反馈计数达到 20 的倍数时触发。"""
        feedback_count = self._rag.count_feedback()
        last_rebalance = self._state.get("rebalanced_domains", {})
        total_rebalanced = sum(
            d.get("duplicates_removed", 0) for d in last_rebalance.values()
        )

        # 每 20 次反馈或满 500 总去重后检查
        if feedback_count > 0 and feedback_count % 20 == 0:
            return {
                "event": "E4",
                "feedback_count": feedback_count,
                "total_deduped": total_rebalanced,
                "action_hint": "dedup_check",
            }
        return None

    def check_e5(self) -> dict | None:
        """陈旧清理检查：距上次检查 >= stale_days。"""
        cfg = self._cfg
        stale_days = cfg.e5_stale_days if hasattr(cfg, "e5_stale_days") else 90
        last = self._state.get("e5_last_check")

        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                days_since = (datetime.now(timezone.utc) - last_dt).days
                if days_since < stale_days:
                    return None
            except Exception:
                pass

        self._state["e5_last_check"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

        return {
            "event": "E5",
            "stale_days": stale_days,
            "action_hint": "stale_cleanup",
        }
