"""KAFED Executor — 執行引擎。

接收 Director 的任務計劃（TaskPlan），調度執行：
1. 對每個子任務調用 Finder 獲取候選模型
2. 通過 Dispatcher 執行
3. 管理 DAG 依賴
4. 執行結果回流 Director（監督回饋環）

監督回饋環：
  Executor 執行 DAG，每完成/失敗一個任務就調用 feedback_callback。
  callback 返回 "continue"（繼續 DAG）/"replan"（需要重新規劃）/"abort"（終止）。
  這樣 Executor 擁有正常流自動化，Director 保留異常流干預權。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from kafed.executor.dag import DagScheduler, Task as DAGTask, DAGSummary
from kafed.executor.dispatcher import Dispatcher, DispatchResult


class FeedbackAction(Enum):
    """Executor 監督回饋的決策動作。"""
    CONTINUE = "continue"   # 一切正常，繼續 DAG
    REPLAN = "replan"       # 需要 Director 重新規劃
    ABORT = "abort"         # 終止整體執行


@dataclass
class FeedbackDecision:
    """Director 對 Executor 回饋的決策結果。"""
    action: FeedbackAction = FeedbackAction.CONTINUE
    new_tasks: list[dict] = field(default_factory=list)
    message: str = ""
    # replan 時攜帶新的子任務描述
    # new_tasks: [{"id": "d", "description": "...", "depends_on": ["c"]}, ...]


# 回饋回調類型簽名
# 參數: (task_id: str, status: str, subtask_result: DispatchResult) -> FeedbackDecision
FeedbackCallback = Callable[[str, str, DispatchResult], FeedbackDecision]


@dataclass
class ExecutionReport:
    """執行報告。"""
    plan_id: str
    status: str                     # completed / partial / failed / aborted
    subtask_results: list[DispatchResult] = field(default_factory=list)
    dag_summary: Optional[DAGSummary] = None
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    feedback_actions: list[str] = field(default_factory=list)  # 回饋決策記錄

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
        if self.feedback_actions:
            lines.append(f"  回饋動作: {', '.join(self.feedback_actions)}")
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
    - DAG 排程（有依賴的多任務，含監督回饋環）
    - 非同步回調（Director 可查詢狀態）
    """

    def __init__(self):
        self.dispatcher = Dispatcher()

    def execute_dag(
        self,
        tasks: list[DAGTask],
        max_concurrent: int = 3,
        feedback_callback: FeedbackCallback | None = None,
    ) -> ExecutionReport:
        """執行 DAG 任務集，支援監督回饋環。

        每完成/失敗一個任務，若提供了 feedback_callback，
        則調用它讓 Director 決定下一步動作：
        - CONTINUE: 繼續 DAG
        - REPLAN: 插入新任務後繼續
        - ABORT: 剩餘任務全部取消

        Args:
            tasks: DAG 任務列表
            max_concurrent: 最大並行數
            feedback_callback: 監督回饋回調 (task_id, status, result) -> FeedbackDecision
        """
        import time
        start = time.time()

        scheduler = DagScheduler(max_concurrent=max_concurrent)
        scheduler.register_batch(tasks)

        results: list[DispatchResult] = []
        feedback_actions: list[str] = []
        aborted = False
        errors: list[str] = []

        while not scheduler.is_done() and not aborted:
            ready = scheduler.pop_ready()
            if not ready:
                break

            for task in ready:
                scheduler.mark_running(task.id)

                # 執行任務
                if task.description.startswith("sh:"):
                    result = Dispatcher.execute_script(
                        task.description[3:].strip(), timeout=300
                    )
                else:
                    result = DispatchResult(
                        task_id=task.id,
                        status="success",
                        output=f"[就緒] {task.description}",
                    )

                # 標記完成/失敗
                if result.is_success:
                    scheduler.complete(task.id, result.output)
                else:
                    scheduler.fail(task.id, result.error)
                    errors.append(f"{task.id}: {result.error[:80]}")

                results.append(result)

                # ── 監督回饋環 ──────────────────────────
                if feedback_callback:
                    task_status = "completed" if result.is_success else "failed"
                    decision = feedback_callback(task.id, task_status, result)
                    feedback_actions.append(decision.action.value)

                    if decision.action == FeedbackAction.ABORT:
                        aborted = True
                        break  # 跳出 for 循環

                    elif decision.action == FeedbackAction.REPLAN:
                        # Director 要求重新規劃——新任務插入 DAG
                        for new_task_spec in decision.new_tasks:
                            new_task = DAGTask(
                                id=new_task_spec["id"],
                                description=new_task_spec["description"],
                                depends_on=new_task_spec.get("depends_on", []),
                                timeout=new_task_spec.get("timeout", 300),
                            )
                            scheduler.register(new_task)
                        # 重新 pop ready（可能新任務已就緒）
                        break  # 跳出 for，重新 while 循環

        summary = scheduler.summary()
        summary.duration = time.time() - start

        # 決定最終狀態
        if aborted:
            final_status = "aborted"
        elif summary.failed > 0 and summary.completed == 0:
            final_status = "failed"
        elif summary.failed > 0:
            final_status = "partial"
        else:
            final_status = "completed"

        return ExecutionReport(
            plan_id="dag",
            status=final_status,
            subtask_results=results,
            dag_summary=summary,
            errors=errors,
            duration_ms=summary.duration * 1000,
            feedback_actions=feedback_actions,
        )

    def status(self) -> dict:
        """當前執行器狀態。"""
        return {
            "status": "ready",
            "executor": "kafed.executor.engine.ExecutorEngine",
        }
