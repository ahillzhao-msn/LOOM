"""
KAFED Analyzer — 分析器配置。

任務規劃已遷移至 pulse.py 的 RECOMMENDED_TASKS。
本模塊只保留數據結構定義，供各層共用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


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
    """單個分析任務的配置。"""
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
