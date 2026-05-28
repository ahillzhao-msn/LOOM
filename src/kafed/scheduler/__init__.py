"""KAFED Scheduler — 任務排程與 WSL 補償機制。

WSL 環境無法保證 cron 按時執行。每個 Task 自帶 compensate() 方法：
錯過 N 次後合併補償，而非跳過。

三處觸發點：
  1. Bootstrap 結束時 — 檢查所有 overdue 任務
  2. Session 開始時 — 輕量 overdue 檢查
  3. Hermes cron tick  — 正常排程執行
"""

from kafed.scheduler.registry import Task, TaskResult, TaskRegistry
from kafed.scheduler.runner import TaskRunner
from kafed.scheduler.builtins import register_builtins

__all__ = [
    "Task",
    "TaskResult",
    "TaskRegistry",
    "TaskRunner",
    "register_builtins",
]
