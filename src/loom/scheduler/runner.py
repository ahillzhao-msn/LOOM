"""LOOM Scheduler — TaskRunner：執行 + 補償引擎。

三種模式：
  tick        — 正常排程：執行所有到期任務
  compensate  — 補償模式：錯過的任務合併執行
  bootstrap   — 啟動模式：檢查 overdue 並補償
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from loom.scheduler.registry import Task, TaskResult, registry

logger = logging.getLogger("loom.scheduler.runner")


class TaskRunner:
    """任務執行器。

    用法：
        runner = TaskRunner()
        results = runner.tick()           # 正常排程
        results = runner.compensate()     # 補償
        results = runner.bootstrap()      # 啟動檢查
    """

    def __init__(self, task_registry=None):
        """task_registry: TaskRegistry-compatible object (defaults to global singleton)."""
        self._registry = task_registry if task_registry is not None else registry

    def tick(self) -> list[TaskResult]:
        """執行所有到期任務（正常模式）。

        只執行 is_due 的任務。錯過多個週期的任務仍只執行一次——
        這是正常 cron tick，不是補償。
        """
        due_tasks = self._registry.get_due()
        if not due_tasks:
            return []

        results = []
        for task in due_tasks:
            result = self._run_one(task)
            results.append(result)
            self._registry.mark_run(task.id)
        return results

    def compensate(self) -> list[TaskResult]:
        """補償模式：錯過至少一個完整週期的任務合併執行。

        只補償 overdue（missed_cycles >= 1），正常到期的不處理。
        """
        overdue = self._registry.get_overdue()
        if not overdue:
            return []

        results = []
        for task in overdue:
            result = task.compensate(task.missed_cycles)
            result.status = "compensated"
            results.append(result)
            self._registry.mark_run(task.id)
        return results

    def bootstrap(self) -> list[TaskResult]:
        """啟動檢查：補償所有 overdue 任務。

        在 loom-bootstrap 和 session_start 時調用。
        與 compensate() 相同但記錄為 bootstrap 模式。
        """
        results = self.compensate()
        for r in results:
            r.status = "compensated"
        if results:
            logger.info("bootstrap: compensated %d overdue tasks", len(results))
        return results

    def run_all(self) -> list[TaskResult]:
        """強制執行所有註冊的 enabled 任務（不檢查到期）。"""
        results = []
        for task in self._registry:
            if task.enabled:
                result = self._run_one(task)
                results.append(result)
        return results

    def _run_one(self, task: Task) -> TaskResult:
        """執行單個 Task，計時 + 捕獲異常。"""
        start = time.perf_counter()
        try:
            result = task.execute()
            result.elapsed = time.perf_counter() - start
            logger.info("task %s → %s (%.2fs)", task.id, result.status, result.elapsed)
            return result
        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.error("task %s → failed: %s", task.id, e)
            return TaskResult(
                task_id=task.id, status="failed",
                elapsed=elapsed, detail=str(e)[:200],
            )


# 便利函數
def run_due() -> list[TaskResult]:
    return TaskRunner().tick()


def run_compensate() -> list[TaskResult]:
    return TaskRunner().compensate()
