"""
KAFED Executor — 任務執行、DAG 調度、模型調用。

E 層是 KAFED 飛輪的「肌肉」：
  接收 Director 的任務計劃 → 調用 Finder 找模型 → 執行 → 回報
"""

from kafed.executor.dag import DagScheduler, Task as DAGTask, TaskState, DAGSummary
from kafed.executor.dispatcher import Dispatcher, DispatchResult
from kafed.executor.engine import ExecutorEngine, ExecutionReport, FeedbackAction, FeedbackDecision, default_feedback_callback

__all__ = [
    "DagScheduler", "DAGTask", "TaskState", "DAGSummary",
    "Dispatcher", "DispatchResult",
    "ExecutorEngine", "ExecutionReport", "FeedbackAction", "FeedbackDecision",
    "default_feedback_callback",
]
