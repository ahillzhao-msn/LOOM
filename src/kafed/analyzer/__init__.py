"""
KAFED Analyzer — 全自主數據分析、模式發現、定時洞察、湧現計算。

分析器是 KAFED 五層飛輪的自律神經系統：
  後台定時分析 → 模式發現 → 洞察生成 → 餵回 Director

Analyzer = pulse_manager（定時排程）的超集。
"""

from kafed.analyzer.engine import AnalyzerEngine, AnalysisReport
from kafed.analyzer.pulse import pulse, status as pulse_status, run_task
from kafed.analyzer.patterns import PatternDetector, Pattern, DomainUsageSnapshot, SessionPattern
from kafed.analyzer.emergence import EmergenceCalculator, EmergenceSignal, DriftReport, StaleReport
from kafed.analyzer.insights import InsightGenerator, Insight
from kafed.analyzer.maintenance import MaintenanceScheduler, MaintenanceReport
from kafed.analyzer.config import TaskConfig, TaskType, ResourceType, DEFAULT_TASKS

__all__ = [
    "AnalyzerEngine", "AnalysisReport",
    "pulse", "pulse_status", "run_task",
    "PatternDetector", "Pattern", "DomainUsageSnapshot", "SessionPattern",
    "EmergenceCalculator", "EmergenceSignal", "DriftReport", "StaleReport",
    "InsightGenerator", "Insight",
    "MaintenanceScheduler", "MaintenanceReport",
    "TaskConfig", "TaskType", "ResourceType", "DEFAULT_TASKS",
]
