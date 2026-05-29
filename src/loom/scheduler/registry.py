"""LOOM Scheduler — Task 與 TaskRegistry。

每個 Task 是自包含的排程命令：定義何時執行、如何執行、如何補償。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger("loom.scheduler.registry")


@dataclass
class TaskResult:
    """Task 執行結果。"""
    task_id: str
    status: str           # "success" | "failed" | "compensated" | "deferred"
    elapsed: float = 0.0
    detail: str = ""
    data: Any = None
    missed_count: int = 0  # 補償時：合併了多少次錯過


@dataclass
class Task(ABC):
    """一個可排程的任務。

    屬性：
        id: 唯一標識
        interval: 預期間隔（timedelta）
        last_run: 上次執行時間
        max_missed: 最多允許錯過次數（錯過 > N 次記錄警告但仍執行）
        enabled: 是否啟用
        fn: 可選的直接執行函數（簡化版，不子類化 Task 時用）

    子類化時覆寫 execute() 和 compensate()。
    使用 fn 參數時自動生成 SimpleTask 子類。
    """

    id: str
    interval: timedelta
    last_run: Optional[datetime] = None
    max_missed: int = 10
    enabled: bool = True
    fn: Optional[Callable] = None
    _result: Optional[TaskResult] = None

    @abstractmethod
    def execute(self) -> TaskResult:
        """正常執行。"""
        ...

    def compensate(self, missed_count: int) -> TaskResult:
        """補償執行——錯過 N 次後被調用。

        默認行為：調用 execute() 並記錄 missed_count。
        子類可覆寫以合併多次錯過的任務（如飛輪只需跑一次而非 N 次）。
        """
        result = self.execute()
        result.missed_count = missed_count
        result.status = "compensated"
        return result

    @property
    def is_due(self) -> bool:
        """檢查是否到期（距離上次執行已超過 interval）。"""
        if self.last_run is None:
            return True  # 從未執行 → 立即到期
        return datetime.now(timezone.utc) - self.last_run >= self.interval

    @property
    def missed_cycles(self) -> int:
        """計算錯過的週期數。"""
        if self.last_run is None:
            return 1
        elapsed = datetime.now(timezone.utc) - self.last_run
        return max(0, int(elapsed / self.interval))

    def __repr__(self) -> str:
        due = "DUE" if self.is_due else "wait"
        missed = f" missed={self.missed_cycles}" if self.missed_cycles > 0 else ""
        return f"<Task {self.id} {due}{missed}>"


class SimpleTask(Task):
    """基於 fn 的簡化 Task。"""

    def execute(self) -> TaskResult:
        if self.fn is None:
            return TaskResult(task_id=self.id, status="failed",
                              detail="no fn assigned")
        try:
            data = self.fn()
            return TaskResult(task_id=self.id, status="success", data=data)
        except Exception as e:
            return TaskResult(task_id=self.id, status="failed",
                              detail=str(e)[:200])


class TaskRegistry:
    """全局任務註冊表。

    管理所有 Task，提供 overdue 檢測、批量執行入口。
    """

    def __init__(self):
        self._tasks: dict[str, Task] = {}

    def register(self, task: Task) -> None:
        """註冊一個 Task。同名覆蓋。"""
        self._tasks[task.id] = task
        logger.debug("registered task: %s interval=%s", task.id, task.interval)

    def unregister(self, task_id: str) -> bool:
        """移除一個 Task。"""
        if task_id in self._tasks:
            del self._tasks[task_id]
            return True
        return False

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list_all(self) -> list[Task]:
        return list(self._tasks.values())

    def get_due(self) -> list[Task]:
        """返回所有到期任務（含過期補償）。"""
        return [t for t in self._tasks.values()
                if t.enabled and t.is_due]

    def get_overdue(self) -> list[Task]:
        """返回錯過至少一個完整週期的任務。"""
        return [t for t in self._tasks.values()
                if t.enabled and t.missed_cycles >= 1]

    def mark_run(self, task_id: str) -> None:
        """標記任務已執行（更新 last_run）。"""
        task = self._tasks.get(task_id)
        if task:
            task.last_run = datetime.now(timezone.utc)

    def __len__(self) -> int:
        return len(self._tasks)

    def __iter__(self):
        return iter(self._tasks.values())


# 全局單例
registry = TaskRegistry()
