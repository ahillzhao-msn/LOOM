"""
LOOM Analyzer — 任務規劃層。

職責轉變（2026-05-22）：
  之前：pulse 充當執行引擎（內部排程 + 執行）
  現在：pulse 已提升為 Hermes 層工具 (~/.hermes/bin/pulse-check.py)
         Analyzer 回歸規劃職責：定義任務、制定排程、生成 cron 配置

本模塊提供：
  1. TaskConfig — 任務定義數據結構（共用）
  2. register_task / unregister_task / list_tasks — 任務規劃 API
  3.建議任務清單 — Analyzer 層認為「系統需要哪些定期任務」
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TaskType(Enum):
    SCRIPT = "script"
    ANALYSIS = "analysis"
    MAINTENANCE = "maintenance"
    FLYWHEEL = "flywheel"


class ResourceType(Enum):
    CPU = "cpu"
    GPU = "gpu"
    API = "api"
    NETWORK = "network"
    NONE = "none"


@dataclass
class TaskConfig:
    """單個分析任務的配置定義。"""
    name: str
    description: str = ""
    task_type: TaskType = TaskType.SCRIPT
    script: str = ""
    resources: list[ResourceType] = field(default_factory=list)
    cooldown: int = 3600
    max_age: int = 86400
    guard: str = ""
    deps: list[str] = field(default_factory=list)
    priority: int = 3
    timeout: int = 600
    max_retries: int = 1
    belongs_to: str = "analyzer"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "task_type": self.task_type.value,
            "script": self.script,
            "resources": [r.value for r in self.resources],
            "cooldown": self.cooldown,
            "max_age": self.max_age,
            "guard": self.guard,
            "deps": self.deps,
            "priority": self.priority,
            "timeout": self.timeout,
            "belongs_to": self.belongs_to,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskConfig:
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            task_type=TaskType(data.get("task_type", "script")),
            script=data.get("script", ""),
            resources=[ResourceType(r) for r in data.get("resources", [])],
            cooldown=data.get("cooldown", 3600),
            max_age=data.get("max_age", 86400),
            guard=data.get("guard", ""),
            deps=data.get("deps", []),
            priority=data.get("priority", 3),
            timeout=data.get("timeout", 600),
            belongs_to=data.get("belongs_to", "analyzer"),
        )


# ── 任務規劃註冊表 ─────────────────────────────
# 這裡定義 Analyzer 層認為系統需要的定期任務。
# 實際執行由 Hermes cron + pulse-check.py 負責。
# register_task() 提供給各組件規劃自己的任務。

_TASK_REGISTRY: dict[str, TaskConfig] = {}
_TASK_REGISTRY_PATH: str = ""


def _registry_path() -> Path:
    global _TASK_REGISTRY_PATH
    if not _TASK_REGISTRY_PATH:
        from loom.config import get_config
        from pathlib import Path
        _TASK_REGISTRY_PATH = str(get_config().data_dir / "task_registry.yaml")
    from pathlib import Path
    return Path(_TASK_REGISTRY_PATH)


def register_task(config: TaskConfig):
    """註冊任務。自動持久化到 task_registry.yaml。"""
    _TASK_REGISTRY[config.name] = config
    _save_registry()


def unregister_task(name: str):
    """取消註冊任務。自動持久化。"""
    _TASK_REGISTRY.pop(name, None)
    _save_registry()


def list_tasks() -> list[TaskConfig]:
    """列出所有註冊的任務。"""
    return list(_TASK_REGISTRY.values())


def _save_registry() -> None:
    """寫入任務註冊表到磁碟。"""
    try:
        import yaml
        rp = _registry_path()
        rp.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "tasks": [t.to_dict() for t in _TASK_REGISTRY.values()],
        }
        with open(rp, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    except Exception:
        pass  # 非關鍵操作，失敗不影響運行


def _load_registry() -> None:
    """從磁碟加載任務註冊表。"""
    global _TASK_REGISTRY
    rp = _registry_path()
    if not rp.exists():
        return
    try:
        import yaml
        with open(rp) as f:
            data = yaml.safe_load(f)
        if data and "tasks" in data:
            for t in data["tasks"]:
                config = TaskConfig.from_dict(t)
                _TASK_REGISTRY[config.name] = config
    except Exception:
        pass


# ── Analyzer 建議的默認任務清單 ───────────────
# 這些是 Analyzer 層認為「該有」的定期任務。
# 實際註冊到 cron 需要通過 cronjob 工具。

RECOMMENDED_TASKS: list[TaskConfig] = [
    TaskConfig(
        name="centroid_rebuild",
        description="重建 embedding centroid（基於 LOOM 新樣本）",
        task_type=TaskType.MAINTENANCE,
        resources=[ResourceType.GPU],
        cooldown=3600,
        max_age=43200,
        priority=3,
        belongs_to="knowledge",
    ),
    TaskConfig(
        name="flywheel_daily",
        description="每日維護：知識攝入 → centroid 一致性檢查",
        task_type=TaskType.FLYWHEEL,
        resources=[ResourceType.CPU, ResourceType.GPU],
        cooldown=21600,
        max_age=86400,
        priority=4,
        belongs_to="analyzer",
    ),
    TaskConfig(
        name="flywheel_weekly",
        description="每週審計：知識深度維護 → 訓練信號檢查",
        task_type=TaskType.FLYWHEEL,
        resources=[ResourceType.CPU, ResourceType.GPU],
        cooldown=432000,
        max_age=604800,
        guard="days_since_last_run >= 5",
        priority=3,
        belongs_to="analyzer",
    ),
    TaskConfig(
        name="yicenet_flywheel",
        description="掃描會話，增量訓練 YiCeNet 世界模型",
        task_type=TaskType.FLYWHEEL,
        resources=[ResourceType.GPU],
        cooldown=21600,
        max_age=172800,
        guard="yicenet_buffer_ready()",
        priority=2,
        belongs_to="analyzer",
    ),
]

# 初始化時註冊推薦任務 + 加載持久化任務
for t in RECOMMENDED_TASKS:
    register_task(t)
_load_registry()


# ── 向下兼容包裝 ──────────────────────────────
# 以下函數供 engine.py / __init__.py 導入用。
# 實際執行已遷移至 ~/.hermes/bin/pulse-check.py。

import json
import subprocess
import sys as _sys
from pathlib import Path as _Path

from loom.config import get_config


def _pulse_check_bin() -> str:
    exe = get_config().pulse_check_script
    if exe and exe.exists():
        return str(exe)
    return ""


def pulse() -> list[dict]:
    """調用 pulse-check.py 執行一次 cron 看門狗掃描。"""
    exe = _pulse_check_bin()
    if not exe:
        return [{"status": "error", "message": "pulse-check.py not found"}]
    try:
        r = subprocess.run(
            [_sys.executable, exe],
            capture_output=True, text=True, timeout=120,
        )
        return [{"status": "ok", "output": r.stdout.strip()}]
    except Exception as e:
        return [{"status": "error", "message": str(e)}]


def status() -> dict:
    """返回脈動狀態（委託 cron jobs.json）。"""
    try:
        data = json.loads(
            (get_config().data_dir / "cron_jobs.json").read_text()
        )
        jobs = []
        for j in data.get("jobs", []):
            jobs.append({
                "name": j.get("name"),
                "schedule": j.get("schedule_display", "?"),
                "last_run": j.get("last_run_at", "never")[:19] if j.get("last_run_at") else "never",
                "state": j.get("state", "?"),
            })
        return {"pulse_check": "active", "cron_jobs": jobs}
    except Exception as e:
        return {"pulse_check": "error", "error": str(e)}


# ── Backlog 消費者 ──────────────────────────────
# 以下函數供 pulse-check.py 或 cron 調用。
# backlog 現在由 Hermes 原生管理。此函數委託給 Hermes CLI。


def check_backlog_and_signal(silent: bool = False) -> dict:
    """檢查 Hermes backlog 是否有高優先級待辦。

    委託給 Hermes 原生 backlog——LOOM 不再維護獨立 backlog。

    Returns:
        {"status": str, "count": int, "top": str or None, "signaled": bool}
    """
    try:
        import json
        import subprocess

        result = subprocess.run(
            ["hermes", "backlog", "list", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {"status": "hermes_unavailable", "count": 0,
                    "top": None, "signaled": False}

        items = json.loads(result.stdout) if result.stdout.strip() else []
        if not items:
            return {"status": "empty", "count": 0, "top": None, "signaled": False}

        # Hermes backlog 沒有 priority_score——取第一個 pending
        top = items[0] if isinstance(items, list) else items
        title = top.get("title", top.get("goal", "?")) if isinstance(top, dict) else str(top)[:80]

        if not silent:
            print(f"  [backlog] Hermes 待辦: {len(items)} 項 → top: {title[:60]}")

        return {"status": "ok", "count": len(items),
                "top": title, "signaled": len(items) > 0}

    except Exception as e:
        if not silent:
            print(f"  [backlog] 檢查失敗: {e}")
        return {"status": "error", "count": 0, "top": None,
                "signaled": False, "error": str(e)}


def run_task(task_name: str) -> dict:
    """強制執行指定 cron job。"""
    return {"status": "deprecated", "message": "請用 hermes cron run <job_id>"}
