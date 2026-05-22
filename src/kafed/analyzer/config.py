"""
KAFED Analyzer — 分析器配置與任務註冊表。

定義定時任務的格式、資源需求和觸發條件。
吸收 pulse_manager 的 pulse_tasks.yaml 任務註冊。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskType(Enum):
    """分析任務類型。"""
    SCRIPT = "script"          # 直接執行腳本
    ANALYSIS = "analysis"      # 自主分析（需 LLM）
    MAINTENANCE = "maintenance"  # 背景維護
    FLYWHEEL = "flywheel"     # 飛輪事件


class ResourceType(Enum):
    """所需資源。"""
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
    
    # 執行
    script: str = ""                      # type=script 時的腳本路徑
    resources: list[ResourceType] = field(default_factory=list)
    
    # 調度
    cooldown: int = 3600                  # 最小間隔（秒）
    max_age: int = 86400                  # 最長間隔，超此值強制觸發（秒）
    
    # 條件
    guard: str = ""                       # 觸發條件表達式（空=總是觸發）
    deps: list[str] = field(default_factory=list)  # 前置依賴任務
    
    # 優先級
    priority: int = 3                     # 1-5，5 最高
    
    # 執行限制
    timeout: int = 600                    # 超時秒數
    max_retries: int = 1
    
    # 歸屬層
    belongs_to: str = "analyzer"          # analyzer / knowledge / director
    
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


# ── 默認任務清單 ──────────────────────────────────

DEFAULT_TASKS: list[TaskConfig] = [
    # Knowledge 層維護
    TaskConfig(
        name="centroid_rebuild",
        description="重建 embedding centroid（基於 KAFED 新樣本）",
        task_type=TaskType.MAINTENANCE,
        script="python3 -c \"import sys; sys.path.insert(0, '$HOME/KAFED/src'); from kafed.knowledge.classify.classify import build_centroids; c = build_centroids(); print(f'centroids: {len(c)} domains')\"",
        resources=[ResourceType.GPU],
        cooldown=3600,
        max_age=43200,
        priority=3,
        belongs_to="knowledge",
    ),
    
    # 飛輪日常維護
    TaskConfig(
        name="flywheel_daily",
        description="每日維護：知識攝入 → centroid 一致性檢查",
        task_type=TaskType.FLYWHEEL,
        script="python3 $HOME/KAFED/scripts/flywheel.py --job daily",
        resources=[ResourceType.CPU, ResourceType.GPU],
        cooldown=21600,
        max_age=86400,
        priority=4,
        timeout=600,
        belongs_to="analyzer",
    ),
    
    # 飛輪每週審計
    TaskConfig(
        name="flywheel_weekly",
        description="每週審計：知識深度維護 → 訓練信號檢查",
        task_type=TaskType.FLYWHEEL,
        script="python3 $HOME/KAFED/scripts/flywheel.py --job weekly",
        resources=[ResourceType.CPU, ResourceType.GPU],
        deps=["flywheel_daily"],
        cooldown=432000,
        max_age=604800,
        guard="days_since_last_run >= 5",
        priority=3,
        timeout=600,
        belongs_to="analyzer",
    ),
    
    # YiCeNet 飛輪（湧現訓練）
    TaskConfig(
        name="yicenet_flywheel",
        description="掃描會話，增量訓練 YiCeNet 世界模型（湧現計算）",
        task_type=TaskType.FLYWHEEL,
        script="$HOME/.hermes/scripts/yicenet_flywheel.sh",
        resources=[ResourceType.GPU],
        cooldown=21600,
        max_age=172800,
        guard="yicenet_buffer_ready()",
        priority=2,
        timeout=600,
        belongs_to="analyzer",
    ),
    
    # 模式發現（待實現）
    TaskConfig(
        name="pattern_detect",
        description="模式發現：掃描 session 數據找重複模式",
        task_type=TaskType.ANALYSIS,
        resources=[ResourceType.CPU],
        cooldown=86400,
        max_age=259200,
        priority=2,
        belongs_to="analyzer",
    ),
    
    # E5 過期檢測
    TaskConfig(
        name="stale_detection",
        description="知識過期檢測：E5 飛輪觸發（90天）",
        task_type=TaskType.MAINTENANCE,
        resources=[ResourceType.CPU],
        cooldown=86400,
        max_age=172800,
        priority=2,
        belongs_to="knowledge",
    ),
]
