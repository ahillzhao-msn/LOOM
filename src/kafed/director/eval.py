"""
KAFED Director — EVAL 复杂度和维度评分。

將 SOUL 核心循環 Step 3 的 EVAL(F1..F5) 形式化為可復用的評分器。
不取代 LLM 的判斷——只提供數據結構和輔助函數。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class F1Scope(Enum):
    """F1: 範圍 (Scope)"""
    SINGLE = 1       # 單知識點查詢
    MULTI = 2        # 多句/多領域提及
    CROSS_DOMAIN = 3 # 跨領域/多步驟/長文


class F2People(Enum):
    """F2: 人 (People)"""
    SELF = 1         # 僅本人
    TEAM = 2         # 涉及他人/團隊
    ORG = 3          # 跨角色/組織級


class F3Freshness(Enum):
    """F3: 新鮮度 (Freshness)"""
    COMMON = 1       # 常見問題
    EXPLORE = 2      # 需調研/探索
    NOVEL_OR_REALTIME = 3  # 全新/訓練/架構，或實時信息
    
    @property
    def is_realtime(self) -> bool:
        """F3=3 是否為實時信息子類型"""
        # 由調用者通過 set_realtime_subtype() 標記
        return self._realtime if hasattr(self, '_realtime') else False
    
    def set_realtime(self, value: bool) -> None:
        self._realtime = value


class F4Risk(Enum):
    """F4: 風險 (Risk)"""
    READ_ONLY = 1    # 讀操作/可逆
    MODIFY = 2       # 修改/寫操作
    DEPLOY = 3       # 部署/生產數據


class F5TokenCost(Enum):
    """F5: Token 成本 (Token Cost)"""
    LOW = 1          # 一句話
    MEDIUM = 2       # 一段話
    HIGH = 3         # 長文/多輪


@dataclass
class EvalScore:
    """EVAL 五維度評分結果。"""
    f1_scope: F1Scope = F1Scope.SINGLE
    f2_people: F2People = F2People.SELF
    f3_freshness: F3Freshness = F3Freshness.COMMON
    f4_risk: F4Risk = F4Risk.READ_ONLY
    f5_token: F5TokenCost = F5TokenCost.LOW
    
    # F3 子類型標記
    f3_realtime: bool = False
    
    # YiCeNet 卦象調製量（可選）
    hexagram_mod: dict[str, int] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.f3_realtime:
            self.f3_freshness = F3Freshness.NOVEL_OR_REALTIME
    
    @property
    def score(self) -> int:
        """Score = max(F1..F5)，非平均。"""
        values = [
            self.f1_scope.value,
            self.f2_people.value,
            self.f3_freshness.value,
            self.f4_risk.value,
            self.f5_token.value,
        ]
        return max(values)
    
    @property
    def tier(self) -> int:
        """Tier 1/2/3 基於 EVAL Score。"""
        s = self.score
        if s <= 1:
            return 1
        elif s <= 2:
            return 2
        else:
            return 3
    
    @property
    def is_realtime_task(self) -> bool:
        """F3=3 且為實時子類型 → 需工具（web search）而非 DAG。"""
        return self.score == 3 and self.f3_realtime and self.f1_scope == F1Scope.SINGLE and self.f4_risk == F4Risk.READ_ONLY
    
    def apply_hexagram_mod(self, mods: dict[str, int]) -> EvalScore:
        """應用 YiCeNet 卦象調製。返回新的 EvalScore。"""
        result = EvalScore(
            f1_scope=self._clamp(F1Scope, self.f1_scope.value + mods.get('F1', 0)),
            f2_people=self._clamp(F2People, self.f2_people.value + mods.get('F2', 0)),
            f3_freshness=self._clamp(F3Freshness, self.f3_freshness.value + mods.get('F3', 0)),
            f4_risk=self._clamp(F4Risk, self.f4_risk.value + mods.get('F4', 0)),
            f5_token=self._clamp(F5TokenCost, self.f5_token.value + mods.get('F5', 0)),
            f3_realtime=self.f3_realtime,
            hexagram_mod=mods,
        )
        return result
    
    @staticmethod
    def _clamp(enum_cls, value: int):
        """將值限制在枚舉範圍內 [1, 3]。"""
        value = max(1, min(3, value))
        return enum_cls(value)
    
    def describe(self) -> str:
        """人類可讀的描述。"""
        lines = [
            f"  F1 範圍:   {self.f1_scope.name} ({self.f1_scope.value})",
            f"  F2 人:     {self.f2_people.name} ({self.f2_people.value})",
            f"  F3 新鮮度: {self.f3_freshness.name} ({self.f3_freshness.value})",
            f"  F4 風險:   {self.f4_risk.name} ({self.f4_risk.value})",
            f"  F5 Token:  {self.f5_token.name} ({self.f5_token.value})",
            f"  Score:     {self.score} → Tier {self.tier}",
        ]
        if self.hexagram_mod:
            lines.append(f"  卦象調製: {self.hexagram_mod}")
        if self.is_realtime_task:
            lines.append("  ⚠ 實時信息子類型 → 需工具非 DAG")
        return "\n".join(lines)


class EvalScorer:
    """EVAL 評分器。
    
    輔助 LLM（Director）進行標準化的 EVAL 評估。
    不取代 LLM 的判斷——只提供快速定界輔助。
    """
    
    @staticmethod
    def from_description(description: str) -> EvalScore:
        """從自然語言描述推導 EVAL 評分（快速估算）。"""
        desc_lower = description.lower()
        
        # 啟發式：關鍵詞匹配
        f1 = F1Scope.CROSS_DOMAIN if any(k in desc_lower for k in ['多領域', '多步驟', '長文', '跨', 'multi', 'complex']) else F1Scope.SINGLE
        f3 = F3Freshness.NOVEL_OR_REALTIME if any(k in desc_lower for k in ['新聞', '最新', 'today', '實時', '訓練', '新建', '架構', 'design']) else F3Freshness.COMMON
        f4 = F4Risk.MODIFY if any(k in desc_lower for k in ['修改', '寫入', '部署', '生產', 'delete', 'remove', '改']) else F4Risk.READ_ONLY
        
        return EvalScore(
            f1_scope=f1,
            f3_freshness=f3,
            f4_risk=f4,
        )
    
    @staticmethod
    def tier_description(tier: int) -> str:
        descriptions = {
            1: "單步直接執行，無需分解",
            2: "簡單分解 + 單模型執行",
            3: "完全分解 → find_partners → DAG 調度 → 合成",
        }
        return descriptions.get(tier, f"未知 Tier: {tier}")
