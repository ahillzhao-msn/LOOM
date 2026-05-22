"""
KAFED Executor — 任務調度器（Dispatcher）。

負責將子任務分發到對應的執行器：
- 直接執行（Direct）→ 當前 LLM 上下文中
- 模型調用（find_partners）→ Finder 找模型 → 調用
- 委託（Delegate）→ 子代理
- DAG 調度 → 使用 DAG 調度器
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any, Optional

from kafed.executor.dag import DagScheduler, Task, TaskState, DAGSummary


@dataclass
class DispatchResult:
    """分發結果。"""
    task_id: str
    status: str          # success / failed / skipped
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0
    
    @property
    def is_success(self) -> bool:
        return self.status == "success"


class Dispatcher:
    """任務調度器。
    
    支援三種執行模式：
    1. direct — 直接執行（腳本 or 簡單命令）
    2. delegated — 委託子代理
    3. dag — DAG 排程（複雜多任務）
    """
    
    @staticmethod
    def execute_script(script: str, timeout: int = 300) -> DispatchResult:
        """執行腳本。"""
        import time
        start = time.time()
        
        try:
            result = subprocess.run(
                script, shell=True, capture_output=True, text=True, timeout=timeout
            )
            elapsed = (time.time() - start) * 1000
            
            if result.returncode == 0:
                return DispatchResult(
                    task_id="script",
                    status="success",
                    output=result.stdout[:2000],
                    duration_ms=elapsed,
                )
            else:
                return DispatchResult(
                    task_id="script",
                    status="failed",
                    error=result.stderr[:500],
                    duration_ms=elapsed,
                )
        except subprocess.TimeoutExpired:
            return DispatchResult(
                task_id="script",
                status="failed",
                error=f"Timeout ({timeout}s)",
                duration_ms=timeout * 1000,
            )
        except Exception as e:
            return DispatchResult(
                task_id="script",
                status="failed",
                error=str(e),
            )
    
    @staticmethod
    def execute_dag(tasks: list[Task], max_concurrent: int = 3) -> DAGSummary:
        """執行 DAG 任務集（同步阻塞）。"""
        scheduler = DagScheduler(max_concurrent=max_concurrent)
        scheduler.register_batch(tasks)
        
        import time
        start = time.time()
        
        while not scheduler.is_done():
            ready = scheduler.pop_ready()
            if not ready:
                break  # 無就緒任務，可能全部阻塞
            
            for task in ready:
                scheduler.mark_running(task.id)
                result = Dispatcher.execute_script(task.description, timeout=60)
                if result.is_success:
                    scheduler.complete(task.id, result.output)
                else:
                    scheduler.fail(task.id, result.error)
        
        summary = scheduler.summary()
        summary.duration = time.time() - start
        return summary
    
    @staticmethod
    def dispatch_plan(tasks: list[tuple[str, str, str]]) -> list[DispatchResult]:
        """分發任務計劃（無依賴，並行執行）。
        
        每個 tuple: (id, description, execution_type)
        execution_type: script / direct
        """
        results = []
        for task_id, description, exec_type in tasks:
            if exec_type == "script":
                result = Dispatcher.execute_script(description)
                result.task_id = task_id
                results.append(result)
            else:
                results.append(DispatchResult(
                    task_id=task_id,
                    status="success",
                    output=f"Task '{task_id}' registered for LLM execution",
                ))
        return results
