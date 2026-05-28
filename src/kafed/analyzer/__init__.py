"""KAFED Analyzer — 學習閉環層。

solidifier:      將 Agent 洞察寫入 KM，觸發飛輪
audit:           Session 非同步稽查
knowledge_audit: 離線知識庫稽核
maintenance:     脈動維護（任務註冊、backlog 檢查）
"""

from kafed.analyzer.solidifier import solidify, session_end_audit
from kafed.analyzer.audit import AuditEngine, AuditInput, AuditRule, RuleCondition
from kafed.analyzer.knowledge_audit import KbAuditor, KbAuditReport, KbIssue, KbCheck, KbInspector
from kafed.analyzer.maintenance import (
    TaskConfig, TaskType, ResourceType,
    register_task, unregister_task, list_tasks,
    pulse, status, check_backlog_and_signal, run_task,
)

__all__ = [
    "solidify", "session_end_audit",
    "AuditEngine", "AuditInput", "AuditRule", "RuleCondition",
    "KbAuditor", "KbAuditReport", "KbIssue", "KbCheck", "KbInspector",
    "TaskConfig", "TaskType", "ResourceType",
    "register_task", "unregister_task", "list_tasks",
    "pulse", "status", "check_backlog_and_signal", "run_task",
]
