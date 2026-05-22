"""
KAFED Analyzer — 洞察生成器。

從模式（Pattern）和湧現信號（EmergenceSignal）中，
生成有意義的洞察，餵回 Director 做決策。

洞察不是「指標彙報」——是「有意義的發現，該做什麼」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Insight:
    """一條洞察。"""
    title: str                          # 一句話摘要
    description: str                    # 詳細說明
    insight_type: str                   # pattern / emergence / gap / opportunity
    priority: int                       # 1-5, 5 最高
    source: str                         # 來源：pattern_detector / emergence / maintenance
    
    # 建議動作
    recommended_action: str = ""
    target_layer: str = ""              # director / knowledge / executor
    
    # 元數據
    created_at: str = ""
    related_data: dict = field(default_factory=dict)
    
    def describe(self) -> str:
        priority_labels = {1: "🔹", 2: "🔸", 3: "⚠️", 4: "🔴", 5: "🚨"}
        icon = priority_labels.get(self.priority, "📌")
        return (
            f"{icon} [{self.insight_type}] {self.title}\n"
            f"  優先級: {self.priority}/5 | 目標: {self.target_layer}\n"
            f"  {self.description}\n"
            f"  建議: {self.recommended_action}"
        )


class InsightGenerator:
    """洞察生成器。
    
    將模式和湧現信號轉化為可供 Director 消費的洞察。
    """
    
    def __init__(self):
        self.insights: list[Insight] = []
    
    def from_patterns(self, patterns: list) -> list[Insight]:
        """從模式生成洞察。"""
        insights = []
        for p in patterns:
            priority = min(int(p.frequency / 2) + 2, 5)  # 頻率映射到優先級
            insights.append(Insight(
                title=f"發現模式: {p.description[:50]}",
                description=p.description,
                insight_type="pattern",
                priority=priority,
                source="pattern_detector",
                recommended_action=p.recommendation,
                target_layer="knowledge",
                related_data={"frequency": p.frequency, "confidence": p.confidence},
            ))
        return insights
    
    def from_emergence(self, signals: list) -> list[Insight]:
        """從湧現信號生成洞察。"""
        insights = []
        for s in signals:
            priority_levels = {
                "centroid_drift": 3,
                "domain_stale": 2,
                "new_domain_emergence": 4,
            }
            priority = priority_levels.get(s.signal_type, 2)
            insights.append(Insight(
                title=s.description[:60],
                description=s.description,
                insight_type="emergence",
                priority=priority,
                source="emergence_calculator",
                target_layer="knowledge",
                related_data=s.data,
            ))
        return insights
    
    def from_knowledge_gaps(self, patterns: list) -> list[Insight]:
        """從知識缺口生成洞察。"""
        insights = []
        for p in patterns:
            insights.append(Insight(
                title=f"知識缺口: {p.example[:40]}",
                description=p.description,
                insight_type="gap",
                priority=min(p.frequency, 4),
                source="pattern_detector",
                recommended_action=p.recommendation,
                target_layer="knowledge",
                related_data={"query": p.example, "frequency": p.frequency},
            ))
        return insights
    
    def summarize(self, max_count: int = 5) -> list[Insight]:
        """返回優先級最高的洞察。"""
        sorted_insights = sorted(self.insights, key=lambda x: x.priority, reverse=True)
        return sorted_insights[:max_count]
    
    def report_to_director(self) -> str:
        """生成給 Director 的報告。"""
        top = self.summarize(5)
        if not top:
            return "無顯著洞察。"
        
        lines = ["## Analyzer 洞察報告", ""]
        for insight in top:
            lines.append(insight.describe())
            lines.append("")
        
        return "\n".join(lines)
