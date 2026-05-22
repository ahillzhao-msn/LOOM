"""
KAFED Analyzer — 分析器引擎。

統籌脈動排程、模式發現、湧現檢測、洞察生成、背景維護。
Analyzer 是 pulse_manager 的超集——除了排程執行，還有自主分析意圖。

調用關係圖：
  Director（定時觸發 / 手動調用）
      │
      └── Analyzer.cycle()
              │
              ├── Pulse Engine（定時任務排程 → 執行）
              ├── Pattern Detector（模式發現）
              ├── Emergence Calculator（湧現檢測）
              ├── Insight Generator（洞察合成 → 回 Director）
              └── Maintenance Scheduler（背景維護）

與 YiCeNet 的關係：
  YiCeNet 是湧現計算的工具——Analyzer 調用 yicenet_flywheel 任務，
  EmergenceCalculator 消費 YiCeNet 的數據做交叉驗證。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from kafed.analyzer.pulse import pulse, status as pulse_status, run_task
from kafed.analyzer.patterns import PatternDetector, Pattern
from kafed.analyzer.emergence import EmergenceCalculator, EmergenceSignal
from kafed.analyzer.insights import InsightGenerator, Insight
from kafed.analyzer.maintenance import MaintenanceScheduler, MaintenanceReport


@dataclass
class AnalysisReport:
    """一次分析循環的完整報告。"""
    pulse_result: dict = field(default_factory=dict)
    patterns: list[Pattern] = field(default_factory=list)
    emergence_signals: list[EmergenceSignal] = field(default_factory=list)
    insights: list[Insight] = field(default_factory=list)
    maintenance: list[MaintenanceReport] = field(default_factory=list)
    
    def summarize(self) -> str:
        lines = ["📊 Analyzer 循環報告", ""]
        lines.append(f"脈動: {self.pulse_result.get('status', 'N/A')}")
        lines.append(f"模式: {len(self.patterns)} 個")
        lines.append(f"湧現: {len(self.emergence_signals)} 個信號")
        lines.append(f"洞察: {len(self.insights)} 條")
        lines.append(f"維護: {len(self.maintenance)} 項")
        
        if self.insights:
            lines.append("")
            lines.append("Top 洞察:")
            for ins in self.insights[:3]:
                lines.append(f"  {ins.describe()}")
        
        return "\n".join(lines)


class AnalyzerEngine:
    """分析器引擎。
    
    一次 cycle() 調用執行完整分析流程。
    通常由 Director 定時觸發（如每 15 分鐘脈動）。
    """
    
    def __init__(self):
        self.pattern_detector = PatternDetector()
        self.emergence_calculator = EmergenceCalculator()
        self.insight_generator = InsightGenerator()
        self.maintenance = MaintenanceScheduler()
    
    def cycle(self) -> AnalysisReport:
        """執行一次完整的分析循環。"""
        report = AnalysisReport()
        
        # 1. 脈動排程（執行定時任務）
        report.pulse_result = pulse()
        
        # 2. 模式發現（需要數據來源，非阻塞）
        # 此處調用 pattern_detector 的方法，
        # 實際調用由 Director 提供數據
        
        # 3. 湧現檢測（需要 KAFED event_state.json 數據）
        # 此處調用 emergence_calculator.check_* 方法，
        # 實際調用由 Knowledge 層提供數據
        
        # 4. 洞察合成
        report.insights = self.insight_generator.summarize()
        
        # 5. 維護檢查
        # memory 壓縮等由 Director 調用
        
        return report
    
    def run_pattern_analysis(self, zero_result_queries: list[str],
                              session_topics: list[tuple[str, str]]) -> list[Insight]:
        """運行模式分析。返回洞察。"""
        patterns = self.pattern_detector.detect_knowledge_gaps(zero_result_queries)
        patterns.extend(self.pattern_detector.detect_frequent_topics(session_topics))
        
        insights = self.insight_generator.from_patterns(patterns)
        if patterns:
            insights.extend(self.insight_generator.from_knowledge_gaps(
                [p for p in patterns if p.pattern_type == "knowledge_gap"]
            ))
        
        return insights
    
    def run_emergence_scan(self, current_domains: dict[str, int],
                            previous_domains: dict[str, int],
                            domain_queries: dict[str, Optional[str]],
                            domain_counts: dict[str, int]) -> list[Insight]:
        """運行湧現掃描。返回洞察。"""
        drift_reports = self.emergence_calculator.check_centroid_drift(
            current_domains, previous_domains
        )
        stale_reports = self.emergence_calculator.check_stale(
            domain_queries, domain_counts
        )
        new_domain_signals = self.emergence_calculator.check_new_domain(
            set(current_domains.keys()),
            set(previous_domains.keys()),
            domain_counts,
        )
        
        all_signals = self.emergence_calculator.signals
        if all_signals:
            return self.insight_generator.from_emergence(all_signals)
        return []
    
    @staticmethod
    def trigger_pulse() -> dict:
        """手動觸發一次脈動。"""
        return pulse()
    
    @staticmethod
    def force_task(task_name: str) -> dict:
        """強制運行特定任務。"""
        return run_task(task_name)
    
    @staticmethod
    def get_status() -> dict:
        """查看分析器狀態。"""
        return pulse_status()
