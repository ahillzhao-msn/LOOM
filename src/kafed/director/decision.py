"""
KAFED Director — 自決決策樹。

輔助 LLM（Director）判斷：
- 成本可估？不可逆？有先例？為目標服務？
- 決定：直接做 / 提方案+排期 / 提案+討論 / 委託
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Decision(Enum):
    """自決決策樹的輸出決策。"""
    EXECUTE_DIRECT = "execute_direct"          # 可逆+低成本 → 直接做
    PROPOSE_SCHEDULE = "propose_schedule"      # 不可逆/高成本 → 提方案+排期
    PROPOSE_DISCUSS = "propose_discuss"        # 涉偏好/新領域 → 提案討論
    DEFER = "defer"                            # 不符合目標 → 推遲
    ESCALATE = "escalate"                      # 無先例+高風險 → 上報用戶
    DELEGATE = "delegate"                      # 明確可委託 → 委託給子代理


class Reversibility(Enum):
    """可逆性評估。"""
    REVERSIBLE = "reversible"           # 可逆，無後遺症
    PARTIALLY_REVERSIBLE = "partial"    # 部分可逆，需清理
    IRREVERSIBLE = "irreversible"       # 不可逆
    UNKNOWN = "unknown"                 # 無法判斷


class CostLevel(Enum):
    """成本等級。"""
    NEGLIGIBLE = 1     # 可忽略
    LOW = 2            # 低
    MEDIUM = 3         # 中
    HIGH = 4           # 高
    PROHIBITIVE = 5    # 禁止級


@dataclass
class DecisionContext:
    """決策上下文。"""
    # 任務描述
    task_description: str
    
    # 成本評估
    estimated_cost: CostLevel = CostLevel.LOW
    cost_details: str = ""
    
    # 可逆性
    reversibility: Reversibility = Reversibility.REVERSIBLE
    
    # 先例
    has_precedent: bool = False
    precedent_ref: str = ""
    
    # 目標相關性
    aligns_with_goal: bool = True
    
    # YiCeNet Q 值調節
    yicenet_q: Optional[float] = None
    
    # 自省記錄
    reflection_notes: list[str] = field(default_factory=list)


@dataclass
class DecisionResult:
    """決策結果。"""
    decision: Decision
    reasoning: str
    confidence: float  # 0.0 - 1.0
    next_steps: list[str] = field(default_factory=list)
    
    def describe(self) -> str:
        """人類可讀的決策描述。"""
        action_names = {
            Decision.EXECUTE_DIRECT: "🚀 直接執行",
            Decision.PROPOSE_SCHEDULE: "📋 提案+排期",
            Decision.PROPOSE_DISCUSS: "💬 提案討論",
            Decision.DEFER: "⏸️ 推遲",
            Decision.ESCALATE: "🔔 上報用戶",
            Decision.DELEGATE: "🤝 委託",
        }
        lines = [
            f"決策: {action_names.get(self.decision, self.decision.value)}",
            f"置信度: {self.confidence:.0%}",
            f"理由: {self.reasoning}",
        ]
        if self.next_steps:
            lines.append("下一步:")
            for s in self.next_steps:
                lines.append(f"  · {s}")
        return "\n".join(lines)


class DecisionTree:
    """自決決策樹（L2 默認模式）。
    
    規則:
    - 成本可估算 → 估
    - 不可逆/高成本 → 提方案 + 排期
    - 有先例 → 復現
    - 無先例 → 試跑
    - 可逆/低成本/為目標服務 → 直接做
    """
    
    @staticmethod
    def evaluate(ctx: DecisionContext) -> DecisionResult:
        """執行決策樹推理。"""
        notes = []
        
        # Step 1: 目標校準
        if not ctx.aligns_with_goal:
            return DecisionResult(
                decision=Decision.DEFER,
                reasoning="任務不符合當前目標，推遲執行。",
                confidence=0.95,
                next_steps=["等待目標對齊後重新評估"],
            )
        
        # Step 2: 不可逆檢查
        if ctx.reversibility == Reversibility.IRREVERSIBLE:
            if ctx.estimated_cost.value >= CostLevel.HIGH.value:
                return DecisionResult(
                    decision=Decision.ESCALATE,
                    reasoning="不可逆操作且高成本，必須上報用戶決策。",
                    confidence=0.95,
                    next_steps=["提供詳細風險評估", "準備替代方案"],
                )
            return DecisionResult(
                decision=Decision.PROPOSE_SCHEDULE,
                reasoning=f"不可逆操作（{ctx.reversibility.value}），需提方案讓用戶確認。",
                confidence=0.90,
                next_steps=["撰寫操作方案", "列出風險和回滾計劃"],
            )
        
        # Step 3: 成本檢查
        if ctx.estimated_cost.value >= CostLevel.HIGH.value:
            return DecisionResult(
                decision=Decision.PROPOSE_SCHEDULE,
                reasoning=f"高成本操作（{ctx.estimated_cost.name}），需提方案+排期。",
                confidence=0.85,
                next_steps=["估算時間和資源", "提供排期選項"],
            )
        
        # Step 4: 先例檢查
        if ctx.has_precedent:
            if ctx.reversibility == Reversibility.REVERSIBLE and ctx.estimated_cost.value <= CostLevel.LOW.value:
                return DecisionResult(
                    decision=Decision.EXECUTE_DIRECT,
                    reasoning=f"有先例（{ctx.precedent_ref}），可逆低成本，直接執行。",
                    confidence=0.95,
                    next_steps=["復現先例模式"],
                )
        
        # Step 5: 偏好/新領域
        if ctx.estimated_cost.value >= CostLevel.MEDIUM.value or ctx.reversibility == Reversibility.PARTIALLY_REVERSIBLE:
            return DecisionResult(
                decision=Decision.PROPOSE_DISCUSS,
                reasoning=f"中等成本（{ctx.estimated_cost.name}）或部分可逆，適合提案討論。",
                confidence=0.80,
                next_steps=["提供 2-3 個選項", "說明各選項的權衡"],
            )
        
        # Step 6: 默認——直接做
        q_mod = ""
        if ctx.yicenet_q is not None:
            if ctx.yicenet_q >= 0.8:
                q_mod = f" YiCeNet Q={ctx.yicenet_q:.2f}（高置信）進一步確認了直接做的傾向。"
            elif ctx.yicenet_q <= 0.3:
                q_mod = f" YiCeNet Q={ctx.yicenet_q:.2f}（低置信），但任務本身可逆低成本，仍直接執行。"
        
        return DecisionResult(
            decision=Decision.EXECUTE_DIRECT,
            reasoning=f"可逆低成本，直接執行。{q_mod}",
            confidence=0.90,
            next_steps=["一步一驗執行"],
        )
    
    @staticmethod
    def estimate_cost(description: str) -> CostLevel:
        """快速成本估算（啟發式）。"""
        desc_lower = description.lower()
        high_signals = ['部署', '生產', '批量', '大量', '數百', '數千', '重構', '遷移']
        medium_signals = ['修改', '更新', '新增', '創建', '開發', 'implement', 'build']
        
        if any(k in desc_lower for k in high_signals):
            return CostLevel.HIGH
        if any(k in desc_lower for k in medium_signals):
            return CostLevel.MEDIUM
        return CostLevel.LOW
    
    @staticmethod
    def estimate_reversibility(description: str) -> Reversibility:
        """快速可逆性估算（啟發式）。"""
        desc_lower = description.lower()
        irreversible = ['刪除', '移除', '銷毀', '覆蓋', '生產', 'deploy', 'prod']
        partial = ['修改', '更新', '改動', '重命名', 'rename', 'update']
        
        if any(k in desc_lower for k in irreversible):
            return Reversibility.IRREVERSIBLE
        if any(k in desc_lower for k in partial):
            return Reversibility.PARTIALLY_REVERSIBLE
        return Reversibility.REVERSIBLE
