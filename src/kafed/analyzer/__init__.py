"""KAFED Analyzer — 任務規劃 + 稽查引擎。

分析器 = 定義任務、制定排程、register_task API。
       + 異步稽查：對比意圖 vs 執行，生成反饋，更新 KM。
"""

from kafed.analyzer.pulse import (
    pulse, status as pulse_status, status,
    run_task, list_tasks, register_task, unregister_task,
    TaskConfig, RECOMMENDED_TASKS, check_backlog_and_signal,
)
from kafed.analyzer.config import TaskConfig, TaskType, ResourceType
from kafed.analyzer.audit import AuditEngine, AuditInput, AuditReport, AuditAction, AuditRule, RuleCondition
from kafed.analyzer.kb_audit import KbAuditor, KbAuditReport, KbIssue, KbCheck, KbInspector

__all__ = [
    "pulse", "pulse_status", "status", "run_task",
    "list_tasks", "register_task", "unregister_task",
    "TaskConfig", "TaskType", "ResourceType",
    "RECOMMENDED_TASKS",
    "AuditEngine", "AuditInput", "AuditReport", "AuditAction",
    "AuditRule", "RuleCondition",
    "KbAuditor", "KbAuditReport", "KbIssue", "KbCheck", "KbInspector",
]
