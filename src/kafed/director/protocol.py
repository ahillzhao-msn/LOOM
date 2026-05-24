"""
KAFED Director → Executor / Knowledge 協議接口。

定義 Director 如何與其他層通信的標準協議。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from kafed.director.planner import TaskPlan


@dataclass
class DispatchOrder:
    """Director → Executor 的派遣指令。"""
    plan: TaskPlan                       # 任務計劃
    priority: int = 3                    # 1-5, 5 最高
    max_retries: int = 1                 # 最大重試次數
    timeout: Optional[int] = None        # 超時秒數
    
    # 回調
    notify_on_complete: bool = True      # 完成時通知 Director
    notify_on_failure: bool = True       # 失敗時通知 Director


@dataclass
class ExecutionReport:
    """Executor → Director 的執行報告。"""
    order_id: str
    status: str                          # completed / failed / partial
    subtask_results: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    summary: str = ""
    
    @property
    def is_success(self) -> bool:
        return self.status == "completed"
    
    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


@dataclass
class KnowledgeDeposit:
    """Director → Knowledge 的知識沉澱指令。"""
    content: str
    source: str                          # 來源類型
    domain: Optional[str] = None         # 領域
    deposit_type: str = "domain_fact"    # lesson / procedure / architecture / domain_fact / preference
    
    def describe(self) -> str:
        deposit_names = {
            "lesson": "教訓",
            "procedure": "程序",
            "architecture": "架構",
            "domain_fact": "領域事實",
            "preference": "用戶偏好",
        }
        return f"[{deposit_names.get(self.deposit_type, self.deposit_type)}] {self.content[:80]}..."


# ── 默認反饋回調 ──────────────────────────────────

def default_feedback_callback() -> Callable:
    """返回默認的 Executor 監督回調：首次失敗→replan，後續→continue。"""
    _fail_count: dict[str, int] = {"count": 0}

    def callback(task_id: str, status: str, result: Any) -> Any:
        from kafed.executor.engine import FeedbackAction, FeedbackDecision
        if status == "failed":
            _fail_count["count"] += 1
            if _fail_count["count"] == 1:
                return FeedbackDecision(
                    action=FeedbackAction.REPLAN,
                    message=f"Task {task_id} failed, requesting replan",
                )
        return FeedbackDecision(action=FeedbackAction.CONTINUE)
    return callback
