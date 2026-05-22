"""
KAFED Director — 戰略取向。

三種戰略姿態的定義、選擇邏輯和配置。
吸收 strategic-awareness skill 的核心邏輯。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Orientation(Enum):
    """戰略取向。"""
    RESOURCE_SENSITIVE = "resource_sensitive"   # 資源敏感：弱模型時激活
    PARALLEL_OFFLOAD = "parallel_offload"       # 並行分流：強模型時激活  
    FLYWHEEL_EVOLUTION = "flywheel_evolution"   # 飛輪演進：始終激活（默認基調）


@dataclass
class StrategyConfig:
    """戰略配置。"""
    # 當前默認模型信息
    default_model: str = "deepseek-v4-flash"     # 當前模型
    is_strong_model: bool = True                 # 是否為強模型（API 付費）
    is_free_model: bool = False                  # 是否為免費模型
    
    # 取向開關（可手動覆蓋）
    force_orientation: Optional[Orientation] = None
    
    # 飛輪檢查
    check_flywheel: bool = True                  # 始終檢查可沉澱知識
    
    # 標記
    notes: list[str] = field(default_factory=list)


@dataclass
class StrategyDecision:
    """戰略取向決策結果。"""
    primary: Orientation                        # 主取向
    secondary: Optional[Orientation] = None     # 次取向
    reasoning: str = ""                         # 選擇理由
    implications: list[str] = field(default_factory=list)  # 行動提示
    
    def describe(self) -> str:
        """人類可讀的描述。"""
        names = {
            Orientation.RESOURCE_SENSITIVE: "資源敏感模式",
            Orientation.PARALLEL_OFFLOAD: "並行分流模式",
            Orientation.FLYWHEEL_EVOLUTION: "飛輪演進模式",
        }
        lines = [
            f"主取向: {names.get(self.primary, self.primary.value)}",
        ]
        if self.secondary:
            lines.append(f"次取向: {names.get(self.secondary, self.secondary.value)}")
        lines.append(f"理由: {self.reasoning}")
        if self.implications:
            lines.append("行動提示:")
            for imp in self.implications:
                lines.append(f"  · {imp}")
        return "\n".join(lines)


class StrategySelector:
    """戰略取向選擇器。
    
    根據當前模型和任務特徵，選擇最合適的戰略取向。
    三省之「道」層面的落地。
    """
    
    # 取向的行動提示
    ORIENTATION_IMPLICATIONS = {
        Orientation.RESOURCE_SENSITIVE: [
            "價值判讀 → 槓桿觸發：高價值複雜任務激活付費模型",
            "低複雜度子任務分解 → 本地模型逐步完成",
            "關鍵節點設 checkpoint，自測輸出質量",
            "付費模型是手術刀，不是錘子",
        ],
        Orientation.PARALLEL_OFFLOAD: [
            "腦手分離：強模型做分析/調度，本地模型做簡單子任務",
            "可並行的低複雜度子任務委託給 0.8B/2B 模型",
            "不需要複雜工作流引擎——delegate_task + 本地模型即可",
        ],
        Orientation.FLYWHEEL_EVOLUTION: [
            "任務執行中標記知識沉澱點（執行完成後固化）",
            "三省產出洞察 → 四型分流固化",
            "每次交互都有機會沉澱知識",
        ],
    }
    
    @classmethod
    def select(cls, config: StrategyConfig) -> StrategyDecision:
        """選擇戰略取向。"""
        # 手動覆蓋
        if config.force_orientation:
            return StrategyDecision(
                primary=config.force_orientation,
                reasoning=f"手動覆蓋為 {config.force_orientation.value}",
                implications=cls.ORIENTATION_IMPLICATIONS.get(config.force_orientation, []),
            )
        
        # 默認：飛輪演進是基調
        primary = Orientation.FLYWHEEL_EVOLUTION
        secondary = None
        reasoning_parts = ["飛輪演進是默認基調（始終激活）"]
        implications = list(cls.ORIENTATION_IMPLICATIONS[Orientation.FLYWHEEL_EVOLUTION])
        
        # 資源檢查
        if config.is_free_model or not config.is_strong_model:
            primary = Orientation.RESOURCE_SENSITIVE
            secondary = Orientation.FLYWHEEL_EVOLUTION
            reasoning_parts.append(f"當前模型 {config.default_model} 為弱/免費模型 → 資源敏感模式優先")
            implications = list(cls.ORIENTATION_IMPLICATIONS[Orientation.RESOURCE_SENSITIVE])
        elif config.is_strong_model:
            secondary = Orientation.PARALLEL_OFFLOAD
            reasoning_parts.append(f"當前模型 {config.default_model} 為強模型 → 並行分流模式可激活")
            implications.extend(cls.ORIENTATION_IMPLICATIONS[Orientation.PARALLEL_OFFLOAD])
        
        if config.notes:
            reasoning_parts.extend(config.notes)
        
        return StrategyDecision(
            primary=primary,
            secondary=secondary,
            reasoning="；".join(reasoning_parts),
            implications=implications,
        )
    
    @classmethod
    def check_flywheel_opportunity(cls, task_completed: bool, produced_knowledge: bool) -> bool:
        """檢查任務是否產生了可沉澱的知識。"""
        return task_completed and produced_knowledge
