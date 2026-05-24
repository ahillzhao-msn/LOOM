"""KAFED Pipeline — Pipeline 步驟入口層。

Pipeline 定義了 SOUL Pipeline 步驟與 KAFED 五層引擎之間的橋接方法。
每個方法對應 Pipeline 的一個步驟，是薄橋接（< 10 行業務邏輯）。

方法與 Pipeline 步驟映射：
  recall(query, domain)     → 召（知識召回）
  eval(context)             → 評（EVAL 評估）
  plan(task, domain, ...)   → 決（任務分解 + 找模型）
  execute(plan)             → 編（DAG 執行）
  solidify(insight, ...)    → 固（知識固化）
  backlog_*()               → 跨 session 待辦
  session_*()               → session 生命周期
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ── Pipeline 數據結構 ─────────────────────────────

@dataclass
class SubTask:
    """Pipeline 級子任務（與 Director/Executor 內部 DTO 解耦）。"""
    id: str
    description: str
    domain: str = "GENERAL"
    depends_on: list[str] = field(default_factory=list)
    model_name: str = ""
    model_provider: str = ""
    budget: str = "any"


@dataclass
class Plan:
    """plan() 的輸出。"""
    subtasks: list[SubTask]
    original_task: str = ""


@dataclass
class TaskResult:
    """單個子任務的執行結果。"""
    task_id: str
    description: str
    status: str  # completed / failed / skipped
    output: str = ""
    error: str = ""
    duration: float = 0.0
    model_name: str = ""
    model_provider: str = ""


# ══════════════════════════════════════════════════
# 召 — 知識召回
# ══════════════════════════════════════════════════

def recall(query: str, domain: str = "",
           top_k: int = 5, soft: bool = True) -> list[dict]:
    """從 KAFED 召回知識片段。"""
    from kafed.knowledge.rag.rag_engine import RAGEngine
    from kafed.knowledge.rag.vector_store import VectorStore

    vs = VectorStore()
    engine = RAGEngine(vs)
    result = engine.query(query, top_k=top_k, domain=domain or None, soft=soft)
    return result.get("results", [])


# ══════════════════════════════════════════════════
# 評 — EVAL 評估
# ══════════════════════════════════════════════════

def eval(text: str, domain: str = "") -> dict:
    """對輸入進行五維 EVAL 評估。返回評分 dict。"""
    from kafed.director.eval import EvalScorer
    score = EvalScorer.from_description(text)
    return {
        "f1_scope": score.f1_scope.value if hasattr(score.f1_scope, 'value') else str(score.f1_scope),
        "f3_freshness": score.f3_freshness.value if hasattr(score.f3_freshness, 'value') else str(score.f3_freshness),
        "f4_risk": score.f4_risk.value if hasattr(score.f4_risk, 'value') else str(score.f4_risk),
    }


# ══════════════════════════════════════════════════
# 決 — 任務分解 + 找模型
# ══════════════════════════════════════════════════

def plan(task: str, domain: str = "GENERAL",
         budget: str = "any", prefer_local: bool = True,
         top_k: int = 1) -> Plan:
    """D→F 橋接：Finder 找模型 → Plan。"""
    from kafed.finder.router import Router as FinderRouter

    finder = FinderRouter()
    result = finder.find_partners(
        brief=task, budget=budget, prefer_local=prefer_local,
        top_k=top_k, domain=domain,
    )
    best = result.best()
    return Plan(
        subtasks=[SubTask(
            id="task_1", description=task, domain=domain,
            model_name=best.name if best else "",
            model_provider=best.provider if best else "",
            budget=budget,
        )],
        original_task=task,
    )


# ══════════════════════════════════════════════════
# 編 — DAG 執行
# ══════════════════════════════════════════════════

def execute(plan: Plan,
            feedback_callback: Optional[Any] = None) -> list[TaskResult]:
    """E 橋接：Plan → ExecutorEngine DAG 執行 → TaskResult[]。"""
    from kafed.executor.engine import ExecutorEngine
    from kafed.executor.dag import Task as DAGTask
    from kafed.director.protocol import default_feedback_callback

    dag_tasks = [
        DAGTask(id=st.id, description=st.description,
                depends_on=st.depends_on)
        for st in plan.subtasks
    ]
    cb = feedback_callback or default_feedback_callback()
    engine = ExecutorEngine()
    report = engine.execute_dag(dag_tasks, feedback_callback=cb)

    results = []
    for dr in report.subtask_results:
        st = next((s for s in plan.subtasks if s.id == dr.task_id), None)
        results.append(TaskResult(
            task_id=dr.task_id,
            description=st.description if st else dr.task_id,
            status=dr.status,
            output=dr.output,
            error=dr.error,
            duration=dr.duration_ms / 1000.0 if hasattr(dr, 'duration_ms') else 0.0,
            model_name=st.model_name if st else "",
            model_provider=st.model_provider if st else "",
        ))

    # Abort 時補跳過的子任務
    if report.status == "aborted":
        completed_ids = {r.task_id for r in results}
        for st in plan.subtasks:
            if st.id not in completed_ids:
                results.append(TaskResult(
                    task_id=st.id, description=st.description,
                    status="skipped", output="(aborted)",
                ))
    return results


# ══════════════════════════════════════════════════
# 固 — 知識固化
# ══════════════════════════════════════════════════

def solidify(insight: str, target: str = "kafed",
             domain: str = "GENERAL", source: str = "",
             title: str = "") -> dict:
    """A→K 橋接：將洞察寫入指定目標。"""
    from kafed.knowledge.ingest import ingest
    return ingest(insight, target=target, domain=domain,
                  source=source, title=title)


# ══════════════════════════════════════════════════
# Backlog — 跨 session 待辦
# ══════════════════════════════════════════════════

def backlog_check() -> list[dict]:
    """檢查 backlog 待辦。"""
    from kafed.knowledge.ingest import backlog_check as bc
    return bc()


def backlog_push(title: str, value: float = 0.7) -> bool:
    """推入 backlog。"""
    from kafed.knowledge.ingest import backlog_push as bp
    return bp(title, value=value)


# ══════════════════════════════════════════════════
# Session 生命周期
# ══════════════════════════════════════════════════

def session_start() -> Optional[dict]:
    """Session 開始時檢查 backlog 待辦。返回最高優先項（如有）。"""
    pending = backlog_check()
    if pending:
        return pending[0]
    return None


def session_end(unfinished: Optional[list[dict]] = None):
    """Session 結束前將未完成推回 backlog。"""
    if unfinished:
        for u in unfinished:
            backlog_push(
                title=u.get("title", u.get("description", "未完成任務")),
                value=u.get("value", 0.6),
            )


def session_end_audit(director_intent: str = "", hexagram_id: int = 0,
                      pipeline_taken: str = "",
                      steps: Optional[list] = None,
                      task_results: Optional[list] = None,
                      solidified: Optional[list] = None,
                      outcome_quality: float = 0.5) -> dict:
    """Session 結束後觸發 Analyzer 稽查。"""
    from kafed.analyzer.audit import AuditEngine, AuditInput

    inp = AuditInput(
        director_intent=director_intent,
        hexagram_id=hexagram_id,
        pipeline_taken=pipeline_taken,
        steps=steps or [],
        task_results=task_results or [],
        solidified=solidified or [],
        outcome_quality=outcome_quality,
    )
    engine = AuditEngine()
    report = engine.audit(inp)
    return {
        "quality_score": report.quality_score,
        "pattern_detected": report.pattern_detected,
        "actions": [{"action": a.action, "target": a.target,
                      "confidence": a.confidence, "reason": a.reason}
                     for a in report.actions],
        "summary": report.summary,
    }
