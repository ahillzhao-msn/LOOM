#!/usr/bin/env python3
"""
pulse_manager.py — 脉动调度引擎

orchestrator.pulse() 的实现。由单一 cron 每15min触发。
职责：读取任务注册表 → 评估条件 → 资源检测 → 优先级排序 → 执行一个任务

设计原则：
  - 每 tick 只执行一个任务（自然解决资源冲突）
  - 无数据变化时静默退出（零开销 tick）
  - 所有决策记入 pulse_state.json 供三省审计
  - GPU 任务独占，CPU/API 任务可并行（但在单 tick 设计中天然串行）

Usage:
    python pulse_manager.py              # 正常脉动
    python pulse_manager.py --status     # 查看状态
    python pulse_manager.py --run-task centroid_rebuild  # 强制运行某任务
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

HOME = Path.home()
PULSE_DIR = Path(os.getenv("KAFED_DATA_DIR", str(HOME / ".hermes" / "data")))
TASKS_YAML = PULSE_DIR / "pulse_tasks.yaml"
STATE_FILE = PULSE_DIR / "pulse_state.json"
TRIGGER_DIR = PULSE_DIR / "pulse_triggers"

# ── 工具函数 ──────────────────────────────────

def log(msg: str):
    print(f"[pulse] {msg}", file=sys.stderr)

def now_ts() -> float:
    return time.time()

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 状态管理 ──────────────────────────────────

def load_state() -> Dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            if isinstance(data, dict) and "tasks" not in data:
                return {"tasks": data, "version": 2, "last_tick": now_iso()}
            return data
        except (json.JSONDecodeError, Exception):
            pass
    return {"version": 2, "tasks": {}, "last_tick": None, "last_tick_result": None}


def save_state(state: Dict):
    state["last_tick"] = now_iso()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def get_task_state(state: Dict, task_name: str) -> Dict:
    return state["tasks"].setdefault(task_name, {
        "last_run": None,
        "last_result": None,
        "missed_count": 0,
        "total_runs": 0,
    })


# ── 任务注册表加载 ────────────────────────────

def load_tasks() -> Dict:
    """从 pulse_tasks.yaml 加载任务定义"""
    if not TASKS_YAML.exists():
        log(f"✗ pulse_tasks.yaml not found at {TASKS_YAML}")
        return {"tasks": {}}
    
    import yaml
    with open(TASKS_YAML) as f:
        data = yaml.safe_load(f)
    
    tasks = data.get("tasks", {}) if data else {}
    return {"tasks": tasks}


# ── 守卫条件评估 ──────────────────────────────

_KAFED_IMPORTABLE: Optional[bool] = None

def kafed_online() -> bool:
    """检查 KAFED 模块是否可导入（import 模式，无须 HTTP）"""
    global _KAFED_IMPORTABLE
    if _KAFED_IMPORTABLE is not None:
        return _KAFED_IMPORTABLE
    try:
        KAFED_SRC = HOME / "KAFED" / "src"
        if str(KAFED_SRC) not in sys.path:
            sys.path.insert(0, str(KAFED_SRC))
        from kafed.config import get_config  # noqa: F401
        _KAFED_IMPORTABLE = True
    except Exception:
        _KAFED_IMPORTABLE = False
    return _KAFED_IMPORTABLE


def run_kafed_analyzer() -> Dict:
    """运行 KAFED 分析器（模式检测 + 涌现计算 + 洞察生成）。

    在空闲 tick 时调用，结果记入 pulse_state 供三省审计。
    """
    if not kafed_online():
        return {"status": "offline"}
    try:
        KAFED_SRC = HOME / "KAFED" / "src"
        if str(KAFED_SRC) not in sys.path:
            sys.path.insert(0, str(KAFED_SRC))
        from kafed.analyzer import engine as az_engine
        from kafed.analyzer import pulse as az_pulse_fn
        from kafed.analyzer import patterns as az_patterns

        # 1) 脈動事件檢查（E1-E4）— 調用 pulse()，返回執行摘要
        pulse_result = az_pulse_fn(tasks=[])
        pulse_events = {"status": pulse_result.get("status", "idle")}

        # 2) 模式檢測（每 6 tick 一次，約 90min）
        patterns_result = az_patterns.detect() if _should_run_patterns() else {}

        # 3) 引擎綜合分析
        status = az_engine.cycle()

        return {
            "status": "ok",
            "events": pulse_events,
            "patterns": patterns_result,
            "engine": status,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _should_run_patterns() -> bool:
    """每 6 次检查运行一次模式检测"""
    state_path = PULSE_DIR / "pulse_state.json"
    if not state_path.exists():
        return True
    try:
        with open(state_path) as f:
            state = json.load(f)
        last_tick = state.get("analyzer", {}).get("last_patterns_tick", 0)
        return int(time.time() / 900) - last_tick >= 6
    except Exception:
        return True


def pending_chunks() -> int:
    """KAFED 中未分類的 chunks 數量（import 模式檢查）"""
    if not kafed_online():
        return 0
    return 0  # KAFED import mode 下由 analyzer 事件驅動，無須查詢 pending count


def yicenet_buffer_ready() -> bool:
    """YiCeNet buffer >= 20 时才能触发飞轮"""
    buffer_path = HOME / "YiCeNet" / "data" / "flywheel_buffer.jsonl"
    if not buffer_path.exists():
        return False
    try:
        with open(buffer_path) as f:
            count = sum(1 for _ in f)
        return count >= 20
    except Exception:
        return False


def memory_usage() -> int:
    """估算记忆使用率（百分比）"""
    # 无法直接读 Memory 大小，从 state 推断
    return 0  # placeholder — 由 agent 任务自行判断


def days_since_last_run(task_name: str, state: Dict) -> float:
    task_state = get_task_state(state, task_name)
    if not task_state.get("last_run"):
        return 999  # 从未运行过，视为过期
    last = datetime.fromisoformat(task_state["last_run"])
    return (datetime.now(timezone.utc) - last).total_seconds() / 86400


def gpu_available() -> bool:
    """GPU 是否可用且负载不高"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return False
        line = result.stdout.strip()
        parts = [p.strip().replace(" MiB", "").replace(" %", "") for p in line.split(",")]
        util_gpu = int(parts[0])
        mem_used = int(parts[1])
        mem_total = int(parts[2])
        # GPU util > 60% 或 VRAM > 80% 认忙
        if util_gpu > 60 or mem_used / mem_total > 0.8:
            return False
        return True
    except Exception:
        return False


GUARD_FUNCTIONS = {
    "kafed_online": kafed_online,
    "pending_chunks": lambda: pending_chunks() >= 20,
    "yicenet_buffer_ready": yicenet_buffer_ready,
    "memory_usage": memory_usage,
    "days_since_last_run": days_since_last_run,
}


def evaluate_guard(guard_expr: str, task_name: str, state: Dict) -> bool:
    """评估 guard 表达式。空字符串 = 总是触发"""
    if not guard_expr:
        return True
    for fn_name, fn in GUARD_FUNCTIONS.items():
        if fn_name in guard_expr:
            try:
                result = fn(task_name, state) if "days_since_last_run" in guard_expr else fn()
                if result:
                    return True
            except Exception as e:
                log(f"  guard '{fn_name}' error: {e}")
                return False
    return True


# ── 任务就绪判断 ──────────────────────────────

def is_task_ready(task_name: str, task_cfg: Dict, state: Dict) -> bool:
    """判断任务是否可执行"""
    task_state = get_task_state(state, task_name)
    now = now_ts()

    # 1) 冷却检查
    last_run = task_state.get("last_run")
    if last_run:
        last_ts = datetime.fromisoformat(last_run).timestamp()
        elapsed = now - last_ts
        cooldown = task_cfg.get("cooldown", 3600)
        if elapsed < cooldown * 0.8:  # 80% 冷却已过即视为可触发
            return False

    # 2) 资源检查
    resources = task_cfg.get("resources", [])
    if "gpu" in resources and not gpu_available():
        return False

    # 3) 依赖检查
    deps = task_cfg.get("deps", [])
    for dep in deps:
        dep_state = get_task_state(state, dep)
        if not dep_state.get("last_run"):
            # 依赖从未运行过
            # 如果是同一天创建的，允许运行；否则等依赖先跑
            return False
        # 依赖在上次脉动后运行了？
        # 简单策略：发出警告但不阻塞
        dep_last = dep_state.get("last_run")
        state_last = state.get("last_tick")
        if dep_last and state_last:
            if dep_last < state_last:
                # 依赖在上次脉动之后还没跑过
                pass  # 不阻塞，只打出 log

    # 4) Guard 条件
    guard = task_cfg.get("guard", "")
    if not evaluate_guard(guard, task_name, state):
        return False

    # 5) Max age 强制触发
    max_age = task_cfg.get("max_age", 0)
    if last_run and max_age > 0:
        last_ts = datetime.fromisoformat(last_run).timestamp()
        if now - last_ts > max_age:
            return True  # 超时强制触发

    return True


def score_task(task_name: str, task_cfg: Dict, state: Dict) -> float:
    """
    任务优先级评分。越高越先执行。
    因素：优先级 × 错过次数 × 紧急度
    """
    task_state = get_task_state(state, task_name)
    priority = task_cfg.get("priority", 3)
    missed = task_state.get("missed_count", 0)
    last_run = task_state.get("last_run")

    # 基础分 = 优先级
    score = priority * 10

    # 错过一次加 5
    score += missed * 5

    # 超时未运行大幅加分
    if last_run:
        now = now_ts()
        last_ts = datetime.fromisoformat(last_run).timestamp()
        max_age = task_cfg.get("max_age", 86400)
        overdue = (now - last_ts) / max_age if max_age > 0 else 0
        if overdue > 1.0:
            score += 20 * overdue  # 超期越多分越高
    else:
        # 从未运行过，加基础分
        score += 15

    return score


# ── 脚本任务执行 ──────────────────────────────

def run_script_task(task_name: str, task_cfg: Dict, state: Dict) -> Dict:
    """执行 type=script 的任务"""
    script = task_cfg.get("script", "")
    timeout = task_cfg.get("timeout", 300)

    log(f"▶ running script task: {task_name}")

    start = time.time()
    try:
        result = subprocess.run(
            script, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(HOME)
        )
        elapsed = time.time() - start
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout[-500:],
            "stderr": result.stderr[-500:],
            "elapsed": round(elapsed, 1),
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "error": f"timeout after {timeout}s", "elapsed": timeout}
    except Exception as e:
        return {"exit_code": -2, "error": str(e), "elapsed": round(time.time() - start, 1)}


def write_agent_trigger(task_name: str, task_cfg: Dict):
    """为 type=agent 任务写触发信号文件"""
    TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
    trigger = {
        "task": task_name,
        "triggered_at": now_iso(),
        "prompt": task_cfg.get("agent_prompt", ""),
    }
    (TRIGGER_DIR / f"{task_name}.json").write_text(
        json.dumps(trigger, indent=2, ensure_ascii=False)
    )
    log(f"  ⚡ agent trigger written: {task_name}")


# ── 主脉动函数 ────────────────────────────────

def pulse(force_run: Optional[str] = None) -> Dict:
    """
    脉动主逻辑：每 tick 执行一次。
    返回决策记录供三省审计。
    """
    state = load_state()
    tasks_def = load_tasks()
    tasks = tasks_def.get("tasks", {})

    decision = {
        "tick": now_iso(),
        "tasks_evaluated": 0,
        "tasks_ready": 0,
        "selected": None,
        "skipped_reasons": {},
        "result": None,
    }

    # 0) 空检查
    if not tasks:
        decision["note"] = "no tasks defined"
        save_state(state)
        return decision

    # 1) 评估所有任务的就绪状态
    ready_tasks = []
    for task_name, task_cfg in tasks.items():
        decision["tasks_evaluated"] += 1

        if force_run and task_name == force_run:
            ready_tasks.append((task_name, task_cfg, 999))
            continue

        if is_task_ready(task_name, task_cfg, state):
            score = score_task(task_name, task_cfg, state)
            ready_tasks.append((task_name, task_cfg, score))
        else:
            # 记录跳过的原因
            task_state = get_task_state(state, task_name)
            task_state["missed_count"] = task_state.get("missed_count", 0) + 1
            decision.setdefault("skipped_reasons", {})[task_name] = {
                "missed_count": task_state["missed_count"],
                "last_run": task_state.get("last_run"),
            }

    # 2) 排序：优先级最高的先执行
    ready_tasks.sort(key=lambda x: -x[2])
    decision["tasks_ready"] = len(ready_tasks)

    if not ready_tasks:
        # 空闲 tick → 运行 KAFED 分析器（模式检测 + 涌现计算）
        log("· no ready tasks, running KAFED analyzer")
        analyzer_result = run_kafed_analyzer()
        state["analyzer"] = {
            "last_run": now_iso(),
            "last_result": analyzer_result,
            "last_patterns_tick": int(time.time() / 900),
        }
        decision["selected"] = "kafed_analyzer"
        decision["result"] = analyzer_result
        if analyzer_result.get("status") == "ok" and (
            analyzer_result.get("events") or analyzer_result.get("patterns")
        ):
            log(f"  ⚡ analyzer events: {analyzer_result.get('events', {})}")
        save_state(state)
        return decision

    # 3) 选择最高优先级任务执行
    selected_name, selected_cfg, selected_score = ready_tasks[0]
    decision["selected"] = selected_name
    decision["score"] = selected_score
    log(f"→ selected: {selected_name} (score={selected_score})")

    task_state = get_task_state(state, selected_name)

    # 4) 执行
    task_type = selected_cfg.get("type", "script")
    if task_type == "script":
        result = run_script_task(selected_name, selected_cfg, state)
    elif task_type == "agent":
        write_agent_trigger(selected_name, selected_cfg)
        result = {"triggered": True, "type": "agent"}
    else:
        result = {"error": f"unknown type: {task_type}"}

    # 5) 更新状态
    task_state["last_run"] = now_iso()
    task_state["last_result"] = result.get("exit_code", result.get("triggered"))
    task_state["missed_count"] = 0
    task_state["total_runs"] = task_state.get("total_runs", 0) + 1

    decision["result"] = result
    state["last_tick_result"] = "ok" if result.get("exit_code", 0) == 0 else "error"
    save_state(state)

    log(f"✔ done: {selected_name} ({result.get('elapsed', '?')}s)")
    return decision


# ── 状态查看 ──────────────────────────────────

def show_status():
    """打印各任务当前状态"""
    state = load_state()
    tasks_def = load_tasks()
    tasks = tasks_def.get("tasks", {})

    print(f"\n{'='*60}")
    print(f"  脉动调度器状态  |  last_tick: {state.get('last_tick', 'never')}")
    print(f"{'='*60}")
    print(f"{'任务':<22} {'上次执行':<22} {'错过':>5} {'总运行':>5} {'就绪?'}")
    print(f"{'-'*60}")

    now = now_ts()
    for name, cfg in tasks.items():
        ts = get_task_state(state, name)
        last = ts.get("last_run", "—")[:19] if ts.get("last_run") else "—"
        missed = ts.get("missed_count", 0)
        total = ts.get("total_runs", 0)
        
        # 就绪判断
        ready = is_task_ready(name, cfg, state)
        ready_str = "✓" if ready else "·"
        
        # 颜色指示
        days_since = "—"
        if ts.get("last_run"):
            last_ts = datetime.fromisoformat(ts["last_run"]).timestamp()
            days = (now - last_ts) / 86400
            days_since = f"{days:.1f}d"
        
        print(f"  {name:<20} {last:<22} {missed:>5} {total:>5}  {ready_str}  ({days_since})")

    print(f"{'='*60}")
    print(f"  GPU可用: {'✓' if gpu_available() else '✗'}")
    print(f"  KAFED在线: {'✓' if kafed_online() else '✗'}  分析器: {'✓' if state.get('analyzer', {}).get('last_result', {}).get('status') == 'ok' else '·'}")
    print(f"  YiCeNet buffer: {'✓' if yicenet_buffer_ready() else '·'}")
    print()


# ── 入口 ──────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="脉动调度引擎")
    parser.add_argument("--status", action="store_true", help="查看调度器状态")
    parser.add_argument("--run-task", type=str, default=None, help="强制运行某任务")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.run_task:
        result = pulse(force_run=args.run_task)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        result = pulse()
        # 静默模式：有输出表示做了事，无输出=无事
        if result.get("selected"):
            print(json.dumps(result, indent=2, ensure_ascii=False))
