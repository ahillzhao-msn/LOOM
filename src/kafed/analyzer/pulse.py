"""
KAFED Analyzer — 脈動排程引擎。

吸收 pulse_manager.py 的全部邏輯。
管理任務註冊表、條件評估、資源檢測、優先級排序、執行調度。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from kafed.analyzer.config import TaskConfig, TaskType, ResourceType, DEFAULT_TASKS

HOME = Path.home()
PULSE_DIR = Path(os.getenv("KAFED_DATA_DIR", str(HOME / ".hermes" / "data")))
STATE_FILE = PULSE_DIR / "pulse_state.json"

# ── 工具函數 ──────────────────────────────────


def log(msg: str):
    print(f"[pulse] {msg}", file=sys.stderr)


def now_ts() -> float:
    return time.time()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def days_since(ts_str: Optional[str]) -> float:
    if not ts_str:
        return float("inf")
    try:
        dt = datetime.fromisoformat(ts_str)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except (ValueError, TypeError):
        return float("inf")


# ── 狀態管理 ──────────────────────────────────


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            if isinstance(data, dict) and "tasks" not in data:
                return {"tasks": data, "version": 2, "last_tick": now_iso()}
            return data
        except (json.JSONDecodeError, Exception):
            pass
    return {"version": 2, "tasks": {}, "last_tick": None, "last_tick_result": None}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def get_task_state(state: dict, task_name: str) -> dict:
    return state.setdefault("tasks", {}).setdefault(task_name, {
        "last_run": None, "last_result": None, "missed_count": 0, "total_runs": 0,
    })


# ── 條件檢查 ──────────────────────────────────


def check_guard(guard_expr: str, task_name: str, state: dict) -> bool:
    """檢查保護條件。空表達式表示總是觸發。"""
    if not guard_expr:
        return True
    
    ts = get_task_state(state, task_name)
    last_run = ts.get("last_run")
    
    # 內建 guards
    if guard_expr == "yicenet_buffer_ready()":
        buffer_path = HOME / "YiCeNet" / "data" / "flywheel_buffer.jsonl"
        if not buffer_path.exists():
            return False
        try:
            count = sum(1 for _ in open(buffer_path))
            return count >= 20
        except Exception:
            return False
    
    if guard_expr.startswith("days_since_last_run"):
        return days_since(last_run) >= 5  # 默認 5 天
    
    log(f"未知 guard: {guard_expr}，跳過")
    return False


def check_dependencies(deps: list[str], state: dict) -> bool:
    """檢查依賴任務是否已完成。"""
    for dep in deps:
        dep_state = state.get("tasks", {}).get(dep, {})
        if dep_state.get("last_result") is None:
            return False
    return True


def check_resources_available(resources: list[ResourceType]) -> bool:
    """檢查所需資源是否可用。"""
    for r in resources:
        if r == ResourceType.GPU:
            # 快速 GPU 檢查
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return False
            # 檢查 VRAM 使用率
            for line in result.stdout.strip().split("\n"):
                try:
                    used = int(line.strip())
                    if used > 10000:  # >10GB VRAM，可能已被佔用
                        return False
                except ValueError:
                    pass
    return True


# ── 任務選擇 ──────────────────────────────────


def select_task(tasks: list[TaskConfig], state: dict) -> Optional[TaskConfig]:
    """選出最高優先級的可行任務。"""
    candidates = []
    
    for task in tasks:
        ts = get_task_state(state, task.name)
        last_run = ts.get("last_run")
        elapsed = now_ts()
        
        if last_run:
            try:
                last_dt = datetime.fromisoformat(last_run)
                elapsed = now_ts() - last_dt.timestamp()
            except (ValueError, TypeError):
                elapsed = float("inf")
        
        # 冷卻檢查
        if elapsed < task.cooldown:
            continue
        
        # 依賴檢查
        if not check_dependencies(task.deps, state):
            continue
        
        # Guard 條件
        if not check_guard(task.guard, task.name, state):
            continue
        
        # 最大間隔強制觸發
        if elapsed >= task.max_age:
            candidates.append((task, 999))  # 強制
            continue
        
        # 資源可用
        if not check_resources_available(task.resources):
            continue
        
        candidates.append((task, task.priority))
    
    if not candidates:
        return None
    
    # 按優先級降序
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


# ── 任務執行 ──────────────────────────────────


def execute_task(task: TaskConfig, state: dict) -> tuple[bool, str]:
    """執行任務。返回 (success, output)。"""
    log(f"執行: {task.name}")
    
    if task.task_type == TaskType.SCRIPT or task.task_type in (TaskType.MAINTENANCE, TaskType.FLYWHEEL):
        if not task.script:
            return False, "無腳本路徑"
        
        try:
            result = subprocess.run(
                task.script,
                shell=True,
                capture_output=True,
                text=True,
                timeout=task.timeout,
            )
            output = result.stdout + result.stderr
            success = result.returncode == 0
            return success, output[:2000]  # 截短
        except subprocess.TimeoutExpired:
            return False, f"超時 ({task.timeout}s)"
        except Exception as e:
            return False, str(e)
    
    elif task.task_type == TaskType.ANALYSIS:
        # 分析型任務——寫 trigger 文件供下次 LLM 會話處理
        trigger_dir = PULSE_DIR / "pulse_triggers"
        trigger_dir.mkdir(parents=True, exist_ok=True)
        trigger_file = trigger_dir / f"{task.name}.trigger"
        trigger_file.write_text(json.dumps({
            "task": task.name,
            "triggered_at": now_iso(),
            "description": task.description,
        }))
        return True, f"trigger 已寫入 {trigger_file}"
    
    return False, f"未知任務類型: {task.task_type}"


# ── 主入口 ──────────────────────────────────


def pulse(tasks: Optional[list[TaskConfig]] = None) -> dict:
    """一次脈動 tick。返回執行摘要。"""
    if tasks is None:
        tasks = DEFAULT_TASKS
    
    state = load_state()
    state["last_tick"] = now_iso()
    
    # 選擇任務
    task = select_task(tasks, state)
    if task is None:
        state["last_tick_result"] = "no_task"
        save_state(state)
        return {"status": "idle", "message": "無可行任務"}
    
    # 記錄執行前狀態
    ts_state = get_task_state(state, task.name)
    ts_state["last_run"] = now_iso()
    ts_state["total_runs"] = ts_state.get("total_runs", 0) + 1
    
    # 執行
    success, output = execute_task(task, state)
    ts_state["last_result"] = 0 if success else 1
    if not success:
        ts_state["missed_count"] = ts_state.get("missed_count", 0) + 1
    
    # 更新狀態
    state["last_tick_result"] = f"{task.name}: {'✅' if success else '❌'}"
    save_state(state)
    
    return {
        "status": "completed" if success else "failed",
        "task": task.name,
        "output": output[:500],
    }


def status() -> dict:
    """查看當前脈動狀態。"""
    state = load_state()
    return {
        "last_tick": state.get("last_tick"),
        "last_result": state.get("last_tick_result"),
        "tasks": {
            name: {
                "last_run": ts.get("last_run"),
                "last_result": "✅" if ts.get("last_result") == 0 else "❌" if ts.get("last_result") == 1 else None,
                "total_runs": ts.get("total_runs", 0),
                "missed": ts.get("missed_count", 0),
            }
            for name, ts in state.get("tasks", {}).items()
        },
    }


def run_task(task_name: str) -> dict:
    """強制運行特定任務（跳過 guard）。"""
    tasks = DEFAULT_TASKS
    task_map = {t.name: t for t in tasks}
    
    if task_name not in task_map:
        return {"status": "error", "message": f"未知任務: {task_name}"}
    
    state = load_state()
    success, output = execute_task(task_map[task_name], state)
    
    ts_state = get_task_state(state, task_name)
    ts_state["last_run"] = now_iso()
    ts_state["total_runs"] = ts_state.get("total_runs", 0) + 1
    ts_state["last_result"] = 0 if success else 1
    save_state(state)
    
    return {
        "status": "completed" if success else "failed",
        "task": task_name,
        "output": output[:500],
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--status":
            print(json.dumps(status(), indent=2))
        elif sys.argv[1] == "--run-task" and len(sys.argv) > 2:
            result = run_task(sys.argv[2])
            print(json.dumps(result, indent=2))
        else:
            print(f"用法: {sys.argv[0]} [--status|--run-task <name>]")
    else:
        result = pulse()
        print(json.dumps(result, indent=2))
