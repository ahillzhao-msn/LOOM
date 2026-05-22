"""
KAFED Director — 任務規劃器（Planner）。

任務分解的數據結構和規劃邏輯。
產生 Executor 可以消費的 TaskPlan。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskStatus(Enum):
    """子任務狀態。"""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class ExecutionStrategy(Enum):
    """執行策略。"""
    DIRECT = "direct"                    # 單步直接執行
    SEQUENTIAL = "sequential"           # 順序執行（有依賴）
    FIND_PARTNERS = "find_partners"     # 需找模型
    RAG_QUERY = "rag_query"             # 知識庫查詢
    WEB_SEARCH = "web_search"           # Web 搜索
    DAG_SCHEDULE = "dag_schedule"       # DAG 調度
    DELEGATE = "delegate"               # 委託子代理


@dataclass
class SubTask:
    """單個子任務。"""
    id: str                              # 唯一標識
    description: str                     # 自然語言描述
    strategy: ExecutionStrategy = ExecutionStrategy.DIRECT
    
    # 依賴關係
    depends_on: list[str] = field(default_factory=list)  # 前置子任務 ID
    
    # 領域信息
    domain: Optional[str] = None         # 如 SAP_PM
    suggested_model: Optional[str] = None  # 建議模型（可選）
    
    # 狀態
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    
    # 預算
    estimated_tokens: int = 0
    
    # 輸出約束
    output_format: Optional[str] = None  # 如 "markdown", "json"


@dataclass
class TaskPlan:
    """完整的任務計劃。"""
    id: str                              # 計劃唯一標識
    goal: str                            # 總目標
    subtasks: list[SubTask] = field(default_factory=list)
    
    # EVAL 評分
    eval_score: Optional[Any] = None     # EvalScore 實例
    
    # 戰略取向
    strategy: Optional[Any] = None       # StrategyDecision 實例
    
    # 元數據
    created_at: Optional[str] = None
    source: str = "director"             # director / pulse / cron
    
    def add_subtask(self, task: SubTask) -> None:
        """添加子任務。"""
        self.subtasks.append(task)
    
    def ready_tasks(self) -> list[SubTask]:
        """獲取所有就緒（依賴已滿足）的子任務。"""
        completed_ids = {t.id for t in self.subtasks if t.status == TaskStatus.COMPLETED}
        return [
            t for t in self.subtasks
            if t.status == TaskStatus.PENDING
            and all(dep in completed_ids for dep in t.depends_on)
        ]
    
    def is_complete(self) -> bool:
        """所有子任務是否都完成了。"""
        return all(t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED) for t in self.subtasks)
    
    def describe(self) -> str:
        """人類可讀的計劃描述。"""
        lines = [
            f"📋 任務計劃: {self.goal}",
            f"   子任務數: {len(self.subtasks)}",
            f"   來源: {self.source}",
            "",
            "子任務列表:",
        ]
        for t in self.subtasks:
            deps_str = f" [依賴: {', '.join(t.depends_on)}]" if t.depends_on else ""
            domain_str = f" [{t.domain}]" if t.domain else ""
            lines.append(f"  {t.id}: {t.description}{deps_str}{domain_str} ({t.strategy.value})")
        
        if self.eval_score:
            lines.append(f"\nEVAL: Tier {self.eval_score.tier}")
        if self.strategy:
            lines.append(f"策略: {self.strategy.primary.value}")
        
        return "\n".join(lines)


class Planner:
    """任務規劃器。
    
    輔助 Director 進行任務分解。
    產生 TaskPlan，供 Executor 執行。
    """
    
    @staticmethod
    def create_plan(goal: str, source: str = "director") -> TaskPlan:
        """創建空任務計劃。"""
        import uuid
        return TaskPlan(
            id=uuid.uuid4().hex[:12],
            goal=goal,
            source=source,
        )
    
    @staticmethod
    def sequential_subtasks(tasks: list[tuple[str, str, str]]) -> list[SubTask]:
        """創建順序依賴的子任務列表。
        
        每個 tuple: (id, description, domain)
        自動添加依賴鏈：t2 依賴 t1, t3 依賴 t2...
        """
        result = []
        prev_id = None
        for task_id, desc, domain in tasks:
            deps = [prev_id] if prev_id else []
            result.append(SubTask(
                id=task_id,
                description=desc,
                strategy=ExecutionStrategy.SEQUENTIAL,
                depends_on=deps,
                domain=domain or None,
            ))
            prev_id = task_id
        return result
    
    @staticmethod
    def parallel_subtasks(tasks: list[tuple[str, str, str]]) -> list[SubTask]:
        """創建並行子任務列表（無依賴）。"""
        return [
            SubTask(
                id=t[0],
                description=t[1],
                strategy=ExecutionStrategy.DIRECT,
                domain=t[2] or None,
            )
            for t in tasks
        ]
