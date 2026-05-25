"""
KAFED Executor — DAG 調度器。

子任務依賴追蹤、就緒管理、阻塞傳播。
吸收 pipeline/scripts/dag_scheduler.py + dag_workflow.py 的核心邏輯。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskState(Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class Task:
    """DAG 中的單個任務節點。"""
    id: str
    description: str
    depends_on: list[str] = field(default_factory=list)
    state: TaskState = TaskState.PENDING
    result: Any = None
    error: str = ""
    retries: int = 0
    max_retries: int = 1

    # Finder 選中的模型（從 Plan.SubTask 傳入）
    model_name: str = ""
    model_provider: str = ""
    
    def can_run(self, completed_ids: set[str]) -> bool:
        return (
            self.state in (TaskState.PENDING, TaskState.FAILED)
            and self.retries < self.max_retries
            and all(dep in completed_ids for dep in self.depends_on)
        )
    
    def is_blocked(self, failed_ids: set[str]) -> bool:
        return any(dep in failed_ids for dep in self.depends_on)


@dataclass
class DAGSummary:
    """DAG 執行摘要。"""
    total: int = 0
    completed: int = 0
    failed: int = 0
    blocked: int = 0
    running: int = 0
    pending: int = 0
    duration: float = 0.0
    
    @property
    def is_done(self) -> bool:
        return self.completed + self.failed == self.total
    
    @property
    def success_rate(self) -> float:
        return self.completed / max(self.total, 1)


class DagScheduler:
    """DAG 調度器。
    
    狀態機：Pending → Ready → Running → Completed / Failed
    失敗自動重試（1次），重試後仍失敗 → 永久 + 阻塞下游。
    """
    
    def __init__(self, max_concurrent: int = 3):
        self.tasks: dict[str, Task] = {}
        self.max_concurrent = max_concurrent
        self._running_count = 0
    
    def register(self, task: Task) -> None:
        self.tasks[task.id] = task
    
    def register_batch(self, tasks: list[Task]) -> None:
        for t in tasks:
            self.register(t)
    
    def pop_ready(self) -> list[Task]:
        """取出所有就緒（依賴已滿足 + 未超並發）的任務。"""
        completed_ids = {
            tid for tid, t in self.tasks.items()
            if t.state == TaskState.COMPLETED
        }
        failed_ids = {
            tid for tid, t in self.tasks.items()
            if t.state == TaskState.FAILED and t.retries >= t.max_retries
        }
        
        ready = []
        available = self.max_concurrent - self._running_count
        
        for t in self.tasks.values():
            if t.can_run(completed_ids):
                # 檢查是否被下游失敗阻塞
                if t.is_blocked(failed_ids):
                    t.state = TaskState.BLOCKED
                    continue
                t.state = TaskState.READY
                ready.append(t)
                self._running_count += 1
                if len(ready) >= available:
                    break
        
        return ready
    
    def mark_running(self, task_id: str) -> None:
        if task_id in self.tasks:
            self.tasks[task_id].state = TaskState.RUNNING
    
    def complete(self, task_id: str, result: Any = None) -> None:
        if task_id in self.tasks:
            self.tasks[task_id].state = TaskState.COMPLETED
            self.tasks[task_id].result = result
            self._running_count -= 1
    
    def fail(self, task_id: str, error: str = "") -> None:
        if task_id not in self.tasks:
            return
        t = self.tasks[task_id]
        t.error = error
        t.retries += 1
        self._running_count -= 1
        
        if t.retries >= t.max_retries:
            t.state = TaskState.FAILED
            # 阻塞所有依賴此任務的下游
            self._propagate_blocked(task_id)
        else:
            t.state = TaskState.PENDING  # 重試
    
    def _propagate_blocked(self, failed_id: str) -> None:
        """級聯阻塞所有依賴失敗任務的下游節點。"""
        changed = True
        while changed:
            changed = False
            for t in self.tasks.values():
                if t.state == TaskState.PENDING and failed_id in t.depends_on:
                    t.state = TaskState.BLOCKED
                    changed = True
    
    def is_done(self) -> bool:
        return all(
            t.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.BLOCKED)
            for t in self.tasks.values()
        )
    
    def summary(self) -> DAGSummary:
        return DAGSummary(
            total=len(self.tasks),
            completed=sum(1 for t in self.tasks.values() if t.state == TaskState.COMPLETED),
            failed=sum(1 for t in self.tasks.values() if t.state == TaskState.FAILED),
            blocked=sum(1 for t in self.tasks.values() if t.state == TaskState.BLOCKED),
            running=sum(1 for t in self.tasks.values() if t.state == TaskState.RUNNING),
            pending=sum(1 for t in self.tasks.values() if t.state in (TaskState.PENDING, TaskState.READY)),
        )
