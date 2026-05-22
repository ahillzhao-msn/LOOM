"""
KAFED Analyzer — 模式發現器。

從累積數據中發現重複模式：
- Session 模式（用戶反覆問什麼？）
- 領域使用模式（哪個域最熱？何時查詢？）
- 知識缺口（哪些問題 KAFED 返回空結果？）
- 行為模式（用戶偏好什麼類型的回答？）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Pattern:
    """發現的模式。"""
    pattern_type: str          # session_pattern / domain_usage / knowledge_gap / behavior
    description: str
    confidence: float          # 0.0 - 1.0
    frequency: int             # 出現次數
    example: str = ""          # 一個實例
    recommendation: str = ""   # 建議動作
    
    def describe(self) -> str:
        return (
            f"[{self.pattern_type}] {self.description}\n"
            f"  置信度: {self.confidence:.0%}, 頻率: {self.frequency}x\n"
            f"  建議: {self.recommendation}"
        )


@dataclass
class DomainUsageSnapshot:
    """領域使用快照。"""
    domain: str
    query_count: int
    avg_relevance: float
    top_queries: list[str] = field(default_factory=list)
    last_queried: Optional[str] = None  # ISO timestamp


@dataclass
class SessionPattern:
    """會話模式。"""
    topic: str
    frequency: int                    # 會話中出現次數
    avg_response_length: int = 0
    domain: str = ""
    common_tool: str = ""             # 最常用的工具
    
    def describe(self) -> str:
        return (
            f"話題: {self.topic} ({self.frequency}x)\n"
            f"  域: {self.domain}, 常用工具: {self.common_tool}"
        )


class PatternDetector:
    """模式發現器。
    
    分析累積數據尋找重複模式。
    結果餵給 Insight Generator 生成有意義的洞察。
    """
    
    def __init__(self):
        self.patterns: list[Pattern] = []
    
    def detect_knowledge_gaps(self, zero_result_queries: list[str]) -> list[Pattern]:
        """檢測知識缺口：KAFED 返回空結果的查詢。"""
        if not zero_result_queries:
            return []
        
        # 按查詢內容聚類
        from collections import Counter
        query_counter = Counter(zero_result_queries)
        
        patterns = []
        for query, count in query_counter.most_common(10):
            if count >= 2:  # 同一問題問了至少 2 次
                patterns.append(Pattern(
                    pattern_type="knowledge_gap",
                    description=f"KAFED 缺少 \"{query}\" 的知識（缺失 {count}x）",
                    confidence=0.8,
                    frequency=count,
                    example=query,
                    recommendation=f"考慮將 \"{query}\" 相關知識攝入 KAFED",
                ))
        
        return patterns
    
    def detect_frequent_topics(self, session_topics: list[tuple[str, str]]) -> list[Pattern]:
        """檢測頻繁話題。"""
        from collections import Counter
        topic_counter = Counter(t[0] for t in session_topics)
        
        patterns = []
        for topic, count in topic_counter.most_common(5):
            if count >= 3:
                patterns.append(Pattern(
                    pattern_type="session_pattern",
                    description=f"話題 \"{topic}\" 反覆出現 {count} 次",
                    confidence=0.85,
                    frequency=count,
                    recommendation="考慮將此領域知識深入攝入或建立專門的 wiki 頁面",
                ))
        
        return patterns
    
    def detect_domain_shift(self, snapshots: list[DomainUsageSnapshot]) -> list[Pattern]:
        """檢測領域使用變化。"""
        if len(snapshots) < 2:
            return []
        
        patterns = []
        for snap in snapshots:
            if snap.query_count < 5:
                continue
            if snap.avg_relevance < 0.3:
                patterns.append(Pattern(
                    pattern_type="domain_usage",
                    description=f"域 {snap.domain} 查詢 {snap.query_count} 次但相關性偏低 ({snap.avg_relevance:.2f})",
                    confidence=0.7,
                    frequency=snap.query_count,
                    recommendation="檢查 KAFED 中該域的 chunk 質量，可能需要重新攝入或清理",
                ))
        
        return patterns
