"""LOOM Scheduler — 內建任務。

註冊 LOOM 的定時維護任務到 TaskRegistry。
這些任務通過 Hermes cron 觸發，TaskScheduler 提供補償機制。
"""

from __future__ import annotations

import logging
from datetime import timedelta

from loom.scheduler.registry import Task, TaskResult, SimpleTask, registry

logger = logging.getLogger("loom.scheduler.builtins")


def register_builtins() -> None:
    """註冊所有內建任務到全局 TaskRegistry。

    在 bootstrap 時調用。每個任務只會被註冊一次。
    """
    _builtins = [
        SimpleTask(
            id="heartbeat",
            interval=timedelta(minutes=2),
            fn=_heartbeat_probe,
            max_missed=30,
        ),
        SimpleTask(
            id="centroid_flywheel",
            interval=timedelta(hours=12),
            fn=_centroid_rebuild,
            max_missed=14,
        ),
        SimpleTask(
            id="explorer_scan",
            interval=timedelta(hours=24),
            fn=_explorer_rescan,
            max_missed=7,
        ),
        SimpleTask(
            id="knowledge_audit",
            interval=timedelta(days=7),
            fn=_knowledge_audit,
            max_missed=4,
        ),
        SimpleTask(
            id="flywheel_daily",
            interval=timedelta(hours=24),
            fn=_flywheel_daily,
            max_missed=7,
        ),
    ]

    for task in _builtins:
        if registry.get(task.id) is None:
            registry.register(task)
            logger.info("builtin registered: %s", task.id)
        else:
            logger.debug("builtin already registered: %s", task.id)


# ══════════════════════════════════════════════════
# 任務函數（由 Hermes cron 或 scheduler 補償調用）
# ══════════════════════════════════════════════════

def _heartbeat_probe() -> TaskResult:
    """心跳探活：更新所有已註冊模型的狀態快取。"""
    try:
        from loom.finder.heartbeat import Heartbeat
        Heartbeat.tick()
        return TaskResult(task_id="heartbeat", status="success",
                          detail="probed")
    except Exception as e:
        return TaskResult(task_id="heartbeat", status="failed",
                          detail=str(e)[:200])


def _centroid_rebuild() -> TaskResult:
    """重建 domain centroid。"""
    try:
        from loom.knowledge.classify.classify import rebuild_centroids
        rebuild_centroids()
        return TaskResult(task_id="centroid_flywheel", status="success")
    except Exception as e:
        return TaskResult(task_id="centroid_flywheel", status="failed",
                          detail=str(e)[:200])


def _explorer_rescan() -> TaskResult:
    """重新掃描模型生態（更新向量空間 + 定價表）。"""
    try:
        from loom.finder.explorer import Explorer
        workers = Explorer.scan_all()
        Explorer.update_vector_space(workers)
        return TaskResult(task_id="explorer_scan", status="success",
                          detail=f"scanned {len(workers)} models")
    except Exception as e:
        return TaskResult(task_id="explorer_scan", status="failed",
                          detail=str(e)[:200])


def _knowledge_audit() -> TaskResult:
    """離線知識庫稽核。"""
    try:
        from loom.analyzer.knowledge_audit import KbAuditor
        auditor = KbAuditor()
        report = auditor.audit()
        issues = report.get("issues", 0)
        return TaskResult(task_id="knowledge_audit", status="success",
                          detail=f"{issues} issues found")
    except Exception as e:
        return TaskResult(task_id="knowledge_audit", status="failed",
                          detail=str(e)[:200])


def _flywheel_daily() -> TaskResult:
    """每日飛輪：事件檢查 + centroid 更新。"""
    try:
        from loom.knowledge.flywheel_events import check_events
        events = check_events()
        return TaskResult(task_id="flywheel_daily", status="success",
                          detail=f"{len(events)} events")
    except Exception as e:
        return TaskResult(task_id="flywheel_daily", status="failed",
                          detail=str(e)[:200])
