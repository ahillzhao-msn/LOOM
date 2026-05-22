"""
KAFED Executor — 執行引擎。

接收 Director 的任務計劃（TaskPlan），調度執行：
1. 對每個子任務調用 Finder 獲取候選模型
2. 通過 Dispatcher 執行
3. 管理 DAG 依賴
4. 執行結果回流 Director
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from kafed.executor.dag import DagScheduler, Task as DAGTask, DAGSummary
from kafed.executor.dispatcher import Dispatcher, DispatchResult


@dataclass
class ExecutionReport:
    """執行報告。"""
    plan_id: str
    status: str                     # completed / partial / failed
    subtask_results: list[DispatchResult] = field(default_factory=list)
    dag_summary: Optional[DAGSummary] = None
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    
    @property
    def is_success(self) -> bool:
        return self.status == "completed"
    
    def summarize(self) -> str:
        lines = [f"🎯 執行報告: {self.plan_id} ({self.status})"]
        if self.dag_summary:
            ds = self.dag_summary
            lines.append(f"  DAG: {ds.completed}/{ds.total} ✅, {ds.failed} ❌, {ds.blocked} ⛔")
            lines.append(f"  成功率: {ds.success_rate:.0%}")
        lines.append(f"  耗時: {self.duration_ms:.0f}ms")
        if self.errors:
            lines.append(f"  錯誤: {len(self.errors)}")
            for e in self.errors[:3]:
                lines.append(f"    · {e[:80]}")
        return "\n".join(lines)


class ExecutorEngine:
    """執行引擎。
    
    直接從 Director 接收 TaskPlan 或 SubTask 列表。
    支援：
    - 直接執行（腳本/命令）
    - DAG 排程（有依賴的多任務）
    - 非同步回調（Director 可查詢狀態）
    """
    
    def __init__(self):
        self.dispatcher = Dispatcher()
    
    def execute_direct(self, subtasks: list[tuple[str, str, str]]) -> ExecutionReport:
        """直接執行一組無依賴的子任務。"""
        import time
        start = time.time()
        
        results = self.dispatcher.dispatch_plan(subtasks)
        errors = [r.error for r in results if not r.is_success]
        
        return ExecutionReport(
            plan_id="direct",
            status="completed" if not errors else "partial",
            subtask_results=results,
            errors=errors,
            duration_ms=(time.time() - start) * 1000,
        )
    
    def execute_dag(self, tasks: list[DAGTask], max_concurrent: int = 3) -> ExecutionReport:
        """執行 DAG 任務集。"""
        import time
        start = time.time()
        
        summary = self.dispatcher.execute_dag(tasks, max_concurrent)
        
        return ExecutionReport(
            plan_id="dag",
            status="completed" if summary.failed == 0 else "partial",
            dag_summary=summary,
            errors=[] if summary.failed == 0 else [f"{summary.failed} tasks failed"],
            duration_ms=summary.duration * 1000,
        )
    
    def status(self) -> dict:
        """當前執行器狀態。"""
        return {
            "status": "ready",
            "executor": "kafed.executor.engine.ExecutorEngine",
        }
