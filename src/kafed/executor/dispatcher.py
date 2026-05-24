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
        """執行 DAG 任務集（同步阻塞）。

        注意：對於自然語言描述的子任務（非 shell 命令），
        調度器返回任務信息，由調用者（LLM）實際執行。
        子任務的 description 若以 'sh:' 開頭則視為 shell 腳本。
        """
        scheduler = DagScheduler(max_concurrent=max_concurrent)
        scheduler.register_batch(tasks)

        import time
        start = time.time()

        while not scheduler.is_done():
            ready = scheduler.pop_ready()
            if not ready:
                break

            for task in ready:
                scheduler.mark_running(task.id)
                if task.description.startswith("sh:"):
                    # 明確的 shell 腳本
                    result = Dispatcher.execute_script(
                        task.description[3:].strip(), timeout=60
                    )
                else:
                    # 自然語言描述 → 返回信息供 LLM 處理
                    result = DispatchResult(
                        task_id=task.id,
                        status="success",
                        output=f"[就緒] {task.description}",
                    )

                if result.is_success:
                    scheduler.complete(task.id, result.output)
                else:
                    scheduler.fail(task.id, result.error)
        
        summary = scheduler.summary()
        summary.duration = time.time() - start
        return summary
    
    @staticmethod
    def delegate_to_subagent(
        goal: str,
        context: str = "",
        model_name: str = "",
        model_provider: str = "",
        toolsets: list[str] | None = None,
        task_id: str = "delegate",
        kafed_root: str | None = None,
    ) -> DispatchResult:
        """準備子代理委託參數。

        生成帶 KAFED context 注入的 delegate_task 調用參數。
        調用者（Agent）根據 result 調用 delegate_task()：

            dr = Dispatcher.delegate_to_subagent(
                goal="審計 KAFED 代碼",
                model_name="deepseek-v4-flash",
                model_provider="deepseek",
            )
            if dr.is_success:
                result = delegate_task(goal=dr.output, model=dr.model)

        KAFED context 會自動注入到 subagent 的 context 中，
        確保 subagent 可以 import kafed 模塊。

        Args:
            goal: 子代理任務目標
            context: 額外背景信息
            model_name: Finder 選中的模型名（空=用默認）
            model_provider: Finder 選中的 provider
            toolsets: 子代理可用的工具集（默認 ['terminal', 'file']）
            task_id: 任務標識
            kafed_root: KAFED 項目根目錄（默認自動檢測）
        """
        import time
        start = time.time()
        from pathlib import Path

        # 自動檢測 KAFED 根目錄
        if not kafed_root:
            candidates = [
                Path.home() / "KAFED",
                Path.cwd() / "KAFED",
                Path(__file__).resolve().parent.parent.parent.parent,
            ]
            for c in candidates:
                if (c / "src" / "kafed" / "config.py").exists():
                    kafed_root = str(c)
                    break
        kafed_root = kafed_root or ""

        # 構建帶 KAFED 上下文的 context
        kafed_context = f"""KAFED 項目根目錄: {kafed_root}
使用 Python 導入 KAFED 前需先:
    import sys
    sys.path.insert(0, '{kafed_root}/src')
    from kafed.config import get_config

{context}"""

        if toolsets is None:
            toolsets = ["terminal", "file"]

        # 產出 delegate_task 參數
        delegate_params = {
            "goal": goal,
            "context": kafed_context,
            "toolsets": toolsets,
            "task_id": task_id,
        }
        if model_name:
            delegate_params["model"] = {
                "provider": model_provider,
                "model": model_name,
            }

        elapsed = (time.time() - start) * 1000
        import json as _json
        return DispatchResult(
            task_id=task_id,
            status="success",
            output=_json.dumps(delegate_params, ensure_ascii=False),
            duration_ms=elapsed,
        )

    # ── Finder→Executor 橋接 ─────────────────────────

    @staticmethod
    def dispatch_for(model_name: str = "", model_provider: str = "",
                     goal: str = "", context: str = "",
                     task_id: str = "dispatch") -> DispatchResult:
        """Finder 選中模型 → delegate_task 參數。"""
        return Dispatcher.delegate_to_subagent(
            goal=goal, context=context,
            model_name=model_name, model_provider=model_provider,
            task_id=task_id,
        )

    @staticmethod
    def needs_dispatch(model_name: str, current_model: str = "") -> bool:
        """當前模型是否即 Finder 選中的？不同則需 dispatch。"""
        if not model_name:
            return False  # Finder 未指定，用默認
        if current_model and model_name == current_model:
            return False  # 當前模型即 Finder 選中
        return True
