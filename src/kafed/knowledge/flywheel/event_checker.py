"""
飞轮事件引擎 — 级联模型：E1 → E2 → E3 → E4 → E1（循环）

级联链（每步只检查，不强制执行）:
    E1 chunk_deposit   ingest 后新块积累 → 触发 E2 检查
    E2 centroid_drift   比较当前 centroid 与基线 → 漂移 > 阈值 → E3
    E3 knowledge_pack   域增长 >30% 且有漂移 → 打包 .kpak + 更新基线 → E4
    E4 quality_cycle    去重 + 压缩 → 回 E1

旁支:
    E5 stale_detection  time-based → 标记 90d 未访问的块
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from kafed.config import get_config

if TYPE_CHECKING:
    from kafed.knowledge.rag.rag_engine import RAGEngine
    from kafed.knowledge.rag.vector_store import VectorStore

logger = logging.getLogger("kafed.flywheel")

_DEFAULT_STATE = {
    "version": 2,
    "last_centroid_domains": [],
    "packed_domains": {},       # domain → {timestamp, count_at_pack, version}
    "rebalanced_domains": {},
    "e5_last_check": None,      # ISO timestamp
    "chunk_totals": {},         # domain → cumulative count since last centroid rebuild
    "stale_flagged": 0,
}


def _migrate_state(state: dict) -> dict:
    """从 v1（list 格式）迁移到 v2（dict 格式）。"""
    if state.get("version", 1) >= 2:
        return state
    # v1 → v2: packed_domains list → dict
    if isinstance(state.get("packed_domains"), list):
        old_list: list = state.pop("packed_domains", [])
        state["packed_domains"] = {
            d: {"timestamp": None, "count_at_pack": 0, "version": 1}
            for d in old_list
        }
    # v1 → v2: 移除旧布尔桩
    state.pop("e2_triggered", None)
    state.pop("e4_triggered", None)
    state["version"] = 2
    return state


class EventChecker:
    """飞轮事件引擎。每次 ingest/feedback 后自检，级联触发。"""

    def __init__(self, vector_store: VectorStore, rag_engine: RAGEngine) -> None:
        self._vs = vector_store
        self._rag = rag_engine
        self._cfg = get_config()
        self._state_path = self._cfg.data_dir / "event_state.json"
        self._state = self._load_state()
        # 缓存嵌入模型
        self._embed = None

    # ── 公开入口 ──────────────────────────────────────────

    def after_ingest(self, domain: str, new_chunks: int) -> list[dict]:
        """Ingest 后：E1 → 级联。返回触发的事件列表。"""
        events: list[dict] = []

        # 累加域 chunk 计数
        totals = self._state.setdefault("chunk_totals", {})
        totals[domain] = totals.get(domain, 0) + new_chunks
        cumulative = totals[domain]

        # ── E1: 知识沉积（跨批次累计，不每批都触发）────
        # 在阈值点触发 E2 检查
        E1_THRESHOLDS = [10, 50, 100, 200, 500, 1000]
        for t in E1_THRESHOLDS:
            if cumulative >= t and self._state.get(f"e1_{domain}_{t}") is None:
                self._state[f"e1_{domain}_{t}"] = datetime.now(timezone.utc).isoformat()
                e1 = {"event": "E1", "domain": domain,
                      "cumulative_chunks": cumulative, "threshold": t}
                events.append(e1)
                logger.info("E1: %s reached %d chunks", domain, t)

                # 级联 → E2: centroid drift check
                drift = self._check_centroid_drift(domain)
                e2_events = self._on_centroid_drift(domain, drift)
                events.extend(e2_events)
                break  # 只触发最近的阈值

        # ── 总是更新 centroid（轻量级，无需触发事件）────
        if new_chunks >= 5 and cumulative >= 10:
            self._rag.rebuild_centroids()

        self._save_state()
        return events

    def after_feedback(self) -> list[dict]:
        """反馈后飞轮（当前为桩 — 未来接入 ranker 微调）。"""
        return []

    def after_query(self, domain: str | None) -> None:
        """查询后飞轮 — 记录访问时间戳（供 E5 使用）。"""
        if domain:
            self._state.setdefault("last_query", {})
            self._state["last_query"][domain] = datetime.now(timezone.utc).isoformat()
            self._save_state()

    def run_daily_maintenance(self) -> list[dict]:
        """每日维护 — time-based 事件。由 cron 触发。"""
        events: list[dict] = []

        # ── E5: stale detection ───────────────────────────
        stale = self._check_stale_chunks()
        if stale > 0:
            self._state["stale_flagged"] += stale
            e5 = {"event": "E5", "action": "stale_flagged",
                  "count": stale, "total": self._state["stale_flagged"]}
            events.append(e5)
            logger.info("E5: flagged %d stale chunks", stale)

        # ── 全域 centroid 同步 ────────────────────────────
        domains = self._vs.list_domains()
        for d in domains:
            count = self._vs.count_by_domain(d)
            if count > 0 and count % 100 < 20:  # 在 100n 附近
                drift = self._check_centroid_drift(d)
                if drift > 0.05:
                    events.extend(self._on_centroid_drift(d, drift))

        self._state["e5_last_check"] = datetime.now(timezone.utc).isoformat()
        self._save_state()
        return events

    def run_weekly_maintenance(self) -> list[dict]:
        """每周维护 — 质量审计 + 重打包检测。"""
        events = self.run_daily_maintenance()

        # ── E3: 知识包重新打包 ────────────────────────────
        domains = self._vs.list_domains()
        for d in domains:
            count = self._vs.count_by_domain(d)
            packed = self._state.get("packed_domains", {}).get(d, {})
            count_at_pack = packed.get("count_at_pack", 0)

            # 条件：域增长 >30% 且 条目 ≥200
            if count >= 200 and count_at_pack > 0:
                growth_pct = (count - count_at_pack) / count_at_pack * 100
                if growth_pct >= 30:
                    drift = self._check_centroid_drift(d)
                    if drift > 0.03:
                        events.extend(self._on_domain_grown(d, count))
            elif count >= 200 and not packed:
                # 首次打包
                drift = self._check_centroid_drift(d)
                events.extend(self._on_domain_grown(d, count))

        self._save_state()
        return events

    # ── E2: centroid drift ────────────────────────────────

    def _check_centroid_drift(self, domain: str) -> float:
        """计算当前 centroid 与基线（最近一次 pack/rebuild）的余弦漂移。"""
        centroid_path = self._cfg.data_dir / "centroids.json"
        if not centroid_path.exists():
            return 0.0

        with open(centroid_path) as f:
            data = json.load(f)

        if domain not in data:
            return 0.0

        current = np.array(data[domain].get("centroid", []))
        baseline = self._state.setdefault("_baseline_centroids", {}).get(domain)

        if current.size == 0:
            return 0.0
        if baseline is None:
            # 首次记录基线
            self._state["_baseline_centroids"][domain] = current.tolist()
            self._save_state()
            return 0.0

        baseline_arr = np.array(baseline)
        if baseline_arr.size == 0:
            return 0.0

        # 余弦距离 = 1 - cosine_similarity
        norm_product = np.linalg.norm(current) * np.linalg.norm(baseline_arr)
        if norm_product == 0:
            return 0.0
        cosine = np.dot(current, baseline_arr) / norm_product
        drift = float(1.0 - cosine)
        return drift

    def _on_centroid_drift(self, domain: str, drift: float) -> list[dict]:
        """E2 drift 事件处理 → 可能级联 E3。"""
        events: list[dict] = []
        if drift < 0.05:
            return events

        e2 = {"event": "E2", "domain": domain, "drift": round(drift, 4)}
        events.append(e2)
        logger.info("E2: %s centroid drift %.4f", domain, drift)

        # 级联 → E3: 检查是否需要打包
        count = self._vs.count_by_domain(domain)
        packed = self._state.get("packed_domains", {}).get(domain, {})
        count_at_pack = packed.get("count_at_pack", 0)

        if count >= 200:
            if count_at_pack == 0 or (count - count_at_pack) / max(count_at_pack, 1) >= 0.3:
                events.extend(self._on_domain_grown(domain, count))

        return events

    def _on_domain_grown(self, domain: str, total_count: int) -> list[dict]:
        """E3: 域达到包就绪状态 → 打包 + 更新基线。"""
        events: list[dict] = []

        try:
            from kafed.kpak.pack import pack_domain
            kpak_path = pack_domain(domain, self._vs, self._cfg)
            version = self._state.get("packed_domains", {}).get(domain, {}).get("version", 0) + 1
            self._state.setdefault("packed_domains", {})
            self._state["packed_domains"][domain] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "count_at_pack": total_count,
                "version": version,
                "path": str(kpak_path),
            }

            # 更新 centroid 基线
            self._state.setdefault("_baseline_centroids", {})
            centroid_path = self._cfg.data_dir / "centroids.json"
            if centroid_path.exists():
                with open(centroid_path) as f:
                    centroids = json.load(f)
                if domain in centroids:
                    self._state["_baseline_centroids"][domain] = centroids[domain].get("centroid", [])

            e3 = {"event": "E3", "domain": domain,
                  "version": version, "entries": total_count,
                  "path": str(kpak_path)}
            events.append(e3)
            logger.info("E3: packed %s v%d (%d entries) → %s",
                        domain, version, total_count, kpak_path)

            # 级联 → E4: quality cycle
            e4_events = self._on_quality_cycle(domain)
            events.extend(e4_events)

        except Exception as e:
            logger.error("E3 pack failed for %s: %s", domain, e)

        return events

    def _on_quality_cycle(self, domain: str) -> list[dict]:
        """E4: 打包后的质量清理。"""
        events: list[dict] = []
        removed = 0

        # 去重：cosine >0.95 的视为重复
        try:
            duplicates = self._deduplicate_domain(domain, threshold=0.95)
            if duplicates > 0:
                removed = duplicates
                self._state.setdefault("rebalanced_domains", {})
                self._state["rebalanced_domains"][domain] = {
                    "duplicates_removed": duplicates,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                e4 = {"event": "E4", "domain": domain,
                      "duplicates_removed": duplicates}
                events.append(e4)
                logger.info("E4: removed %d duplicates from %s", duplicates, domain)
        except Exception as e:
            logger.warning("E4 dedup failed for %s: %s", domain, e)

        return events

    # ── E5: stale detection ───────────────────────────────

    def _check_stale_chunks(self) -> int:
        """检查 stale 块。标准：
        - 从未被查询的域：仅当距今天 ≥30d（新系统宽限期）
        - 曾被查询过的域：距上次查询 ≥90d
        """
        last_query = self._state.get("last_query", {})
        now = datetime.now(timezone.utc)
        stale_count = 0
        grace_days = 30  # 新系统宽限期
        stale_days = self._cfg.e5_stale_days

        for d in self._vs.list_domains():
            ts = last_query.get(d)
            if ts:
                # 曾被查询 → 检查是否过期
                try:
                    last = datetime.fromisoformat(ts)
                    if (now - last).days >= stale_days:
                        count = self._vs.count_by_domain(d)
                        stale_count += count
                        logger.info("E5: domain %s stale (%d days idle, %d chunks)",
                                    d, (now - last).days, count)
                except ValueError:
                    pass
            else:
                # 从未被查询 → 需要宽限期
                count = self._vs.count_by_domain(d)
                # 没有元数据可查创建时间，用 chunk_totals 做宽松判断
                total = self._state.get("chunk_totals", {}).get(d, 0)
                if total > 0 and total < count * 0.5:
                    # 刚摄入不久 → 跳过
                    continue
                if count > 0:
                    logger.info("E5: domain %s never queried (%d chunks, within grace period)",
                                d, count)

        return stale_count

    # ── 去重 ──────────────────────────────────────────────

    def _deduplicate_domain(self, domain: str, threshold: float = 0.95) -> int:
        """找出并移除域内 cosine > threshold 的重复块。"""
        from kafed.knowledge.rag.embedding import embed_texts

        data = self._vs.get_by_domain(domain)
        ids = data.get("ids", [])
        documents = data.get("documents", [])

        if len(documents) < 2:
            return 0

        # 批量嵌入
        vecs = np.array(embed_texts(documents))

        # 余弦相似度矩阵（抽样 ≤200 条以控制计算量）
        N = min(len(vecs), 200)
        vecs = vecs[:N]
        ids = ids[:N]

        # 归一化
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1
        vecs_norm = vecs / norms

        # 上三角相似度矩阵
        sim = vecs_norm @ vecs_norm.T
        dup_ids = set()
        for i in range(N):
            for j in range(i + 1, N):
                if sim[i, j] > threshold:
                    dup_ids.add(ids[j])

        # 移除重复
        for d_id in dup_ids:
            try:
                self._vs._collection.delete(ids=[d_id])
            except Exception:
                pass

        return len(dup_ids)

    # ── 状态管理 ──────────────────────────────────────────

    def _load_state(self) -> dict:
        if self._state_path.exists():
            with open(self._state_path) as f:
                try:
                    raw = json.load(f)
                    return {**_DEFAULT_STATE, **(_migrate_state(raw))}
                except json.JSONDecodeError:
                    pass
        return dict(_DEFAULT_STATE)

    def _save_state(self) -> None:
        # 确保目录存在
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_path, "w") as f:
            json.dump(self._state, f, indent=2)

    def status(self) -> dict:
        """返回飞轮状态摘要。"""
        return {
            "version": self._state.get("version", 2),
            "packed_domains": list(self._state.get("packed_domains", {}).keys()),
            "e5_last_check": self._state.get("e5_last_check"),
            "stale_flagged": self._state.get("stale_flagged", 0),
            "chunk_totals": self._state.get("chunk_totals", {}),
        }

