"""
KAFED Orchestrator — 五層編排器。

將 D→F→E→A→K→Backlog 接成有機整體。
供 SOUL Pipeline 各步驟調用。

Usage:
    from kafed.orchestrator import plan, execute, absorb, backlog_check, backlog_push

    # "決" 步驟：plan
    p = plan("分析SAP PM工單數據", domain="SAP_PM")
    p.subtasks       # [SubTask(id, desc, domain, best_model)]
    p.summary        # 可視化摘要

    # "編" 步驟：execute  
    results = execute(p)
    for r in results:
        print(r.status, r.output[:100])

    # "固" 步驟：absorb
    report = absorb(results, source="session_xxx")
    report.memory_items   # 存了哪些 memory
    report.skill_updates  # 存了哪些 skill
    report.backlog_items  # 推了哪些 backlog

    # Session 結束前
    backlog_push(unfinished_tasks)   # 未完成推回
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── KAFED 內部依賴（已安裝，無需 sys.path hack） ─────────

from kafed.finder.router import Router as FinderRouter
from kafed.finder.matcher import WorkerCandidate
from kafed.executor.dag import Task as DAGTask
from kafed.executor.dispatcher import Dispatcher, DispatchResult
from kafed.director.planner import Planner, TaskPlan, SubTask as PlannerSubTask, ExecutionStrategy
from kafed.config import get_config


# ── 數據結構 ─────────────────────────────────────

@dataclass
class SubTask:
    """Director 分解後的子任務。"""
    id: str
    description: str
    domain: str = "GENERAL"
    depends_on: list[str] = field(default_factory=list)
    model: Optional[WorkerCandidate] = None
    budget: str = "any"


@dataclass
class Plan:
    """plan() 的輸出——任務+模型列表。"""
    subtasks: list[SubTask]
    original_task: str = ""
    summary: str = ""


@dataclass
class TaskResult:
    """單個子任務的執行結果。"""
    task_id: str
    description: str
    status: str  # completed / failed / skipped
    output: str = ""
    error: str = ""
    duration: float = 0.0
    # Finder 選中的模型（供 delegate_task 使用）
    model_name: str = ""
    model_provider: str = ""


@dataclass
class AbsorptionReport:
    """absorb() 的輸出。"""
    memory_items: list[str] = field(default_factory=list)
    skill_updates: list[str] = field(default_factory=list)
    rag_entries: int = 0
    backlog_items: list[str] = field(default_factory=list)
    summary: str = ""


# ── Finder（全局 singleton） ─────────────────────

_finder: Optional[FinderRouter] = None


def _get_finder() -> FinderRouter:
    global _finder
    if _finder is None:
        _finder = FinderRouter()
    return _finder


# ══════════════════════════════════════════════════
# D→F 橋接：plan()
# ══════════════════════════════════════════════════

def plan(task: str, domain: str = "GENERAL",
         budget: str = "any", prefer_local: bool = True,
         subtasks: list[tuple[str, str, str]] | None = None,
         tier: int = 1) -> Plan:
    """Director 分解任務 + Finder 找模型 → Plan。

    參數:
        task: 任務描述（Tier 1 使用；高 Tier 改傳 subtasks）
        domain: 領域
        budget: 預算 any/free
        prefer_local: 本地優先
        subtasks: 可選的預分解子任務列表 [(id, desc, domain)]
        tier: 任務複雜度級別（1=單步, 2=簡單多步, 3=全分解）

    支援兩路：
      Path A（Tier 1）: 單任務 + 找最佳模型
      Path B（Tier 2+）: 使用 Planner 順序/並行分解子任務
    """
    finder = _get_finder()

    if tier >= 2:
        if subtasks:
            # 使用調用者提供的預分解子任務
            plan_subtasks = [
                PlannerSubTask(id=s[0], description=s[1], domain=s[2] if s[2] else domain,
                               strategy=ExecutionStrategy.DIRECT)
                for s in subtasks
            ]
        else:
            # 使用 Planner 順序分解（fallback）
            plan_subtasks = Planner.sequential_subtasks([
                (f"step_{i}", s, domain)
                for i, s in enumerate(_auto_split(task))
            ]) if _auto_split(task) else []

        if plan_subtasks:
            # 每個子任務找模型
            results = []
            for ps in plan_subtasks:
                result = finder.find_partners(
                    brief=ps.description, budget=budget,
                    prefer_local=prefer_local, top_k=3, domain=ps.domain,
                )
                best = result.best()
                results.append(SubTask(
                    id=ps.id, description=ps.description,
                    domain=ps.domain, model=best, budget=budget,
                    depends_on=ps.depends_on,
                ))

            subtasks_processed = results
            lines = [f"  任務分解: {len(results)} 子任務"]
            for r in results:
                model_str = f"{r.model.name} ({r.model.match_score:.2f})" if r.model else "默認"
                dep_str = f" [依賴: {r.depends_on}]" if r.depends_on else ""
                lines.append(f"    · {r.id:12s} {r.description[:40]:40s} → {model_str}{dep_str}")

            return Plan(
                subtasks=subtasks_processed,
                original_task=task,
                summary="\n".join(lines),
            )

    # Path A: Tier 1 — 單任務（原邏輯）
    result = finder.find_partners(
        brief=task, budget=budget, prefer_local=prefer_local,
        top_k=3, domain=domain,
    )
    best = result.best()
    subtask = SubTask(
        id="task_1", description=task, domain=domain,
        model=best, budget=budget,
    )

    lines = [f"  任務: {task[:60]}{'...' if len(task) > 60 else ''}"]
    lines.append(f"  域: {domain} | 預算: {budget} | 本地優先: {prefer_local}")
    if best:
        lines.append(f"  最佳模型: {best.name} ({best.provider}) | 匹配度: {best.match_score:.2f}")
    if result.candidates:
        lines.append("  候選:")
        for c in result.candidates[:3]:
            lines.append(f"    · {c.name:20s} {c.provider:12s} score={c.match_score:.2f} "
                         f"{'🟢' if c.is_online else '🔴'}")
    else:
        lines.append("   ⚠ 無可用模型（將使用默認）")

    return Plan(
        subtasks=[subtask],
        original_task=task,
        summary="\n".join(lines),
    )


def _auto_split(task: str) -> list[str]:
    """簡單的自動分解：按 '然後' '接著' '，再' 等關鍵詞分割。"""
    import re
    parts = re.split(r'(?:然後|接著|之後|下一步|，再|，然後)', task)
    return [p.strip() for p in parts if len(p.strip()) > 5]


def plan_multi(subtasks: list[SubTask]) -> Plan:
    """批量版：已分解好的子任務，每個找模型。"""
    finder = _get_finder()
    for st in subtasks:
        if st.model is None:
            result = finder.find_partners(
                brief=st.description,
                budget=st.budget,
                prefer_local=True,
                top_k=1,
                domain=st.domain,
            )
            st.model = result.best()

    lines = [f"  子任務數: {len(subtasks)}"]
    for st in subtasks:
        model_str = f"{st.model.name}" if st.model else "默認"
        dep_str = f" 依賴: {st.depends_on}" if st.depends_on else ""
        lines.append(f"    · {st.id:12s} {st.description[:40]:40s} → {model_str}{dep_str}")

    return Plan(
        subtasks=subtasks,
        summary="\n".join(lines),
    )


# ══════════════════════════════════════════════════
# E 橋接：execute()
# ══════════════════════════════════════════════════
# E→D→A→K 橋接
# ══════════════════════════════════════════════════

def execute(
    plan: Plan,
    dispatcher=None,
    director_callback: Callable | None = None,
) -> list[TaskResult]:
    """Plan → ExecutorEngine DAG 執行 → TaskResult[]。

    整合監督回饋環：
    - 正常流：Executor 自動執行 DAG
    - 任務失敗：調用 director_callback(task_id, status, result) 決定後續
    - 回饋決策：continue（繼續）/replan（重規劃）/abort（終止）

    director_callback 簽名:
        def callback(task_id: str, status: str, result: DispatchResult) -> FeedbackDecision:
            if status == "failed":
                return FeedbackDecision(action=FeedbackAction.REPLAN, ...)
            return FeedbackDecision(action=FeedbackAction.CONTINUE)

    若未提供，默認行為：失敗時 continue（不干預 DAG）。
    """
    from kafed.executor.engine import (
        ExecutorEngine, ExecutionReport,
        FeedbackAction, FeedbackDecision,
    )

    # 轉換 Plan.subtasks → DAGTask[]
    dag_tasks = []
    for st in plan.subtasks:
        dag_tasks.append(DAGTask(
            id=st.id,
            description=st.description,
            depends_on=st.depends_on,
        ))

    # 默認 director_callback：首次失敗→replan，後續失敗→continue
    _fail_count: dict[str, int] = {"count": 0}

    def _default_director_callback(
        task_id: str, status: str, result: Any,
    ) -> FeedbackDecision:
        if status == "failed":
            _fail_count["count"] += 1
            if _fail_count["count"] == 1:
                # 首次失敗 → 要求 Director 重新規劃
                return FeedbackDecision(
                    action=FeedbackAction.REPLAN,
                    message=f"Task {task_id} failed, requesting replan",
                )
        return FeedbackDecision(action=FeedbackAction.CONTINUE)

    cb = director_callback or _default_director_callback

    # 構建 feedback wrapper（適配 DispatchResult）
    def _feedback(task_id: str, status: str, dr: DispatchResult) -> FeedbackDecision:
        return cb(task_id, status, dr)

    # 執行
    engine = ExecutorEngine()
    report = engine.execute_dag(dag_tasks, feedback_callback=_feedback)

    # ExecutionReport → TaskResult[]
    results = []
    for dr in report.subtask_results:
        # 匹配 SubTask 的 model 信息
        st = next((s for s in plan.subtasks if s.id == dr.task_id), None)
        results.append(TaskResult(
            task_id=dr.task_id,
            description=st.description if st else dr.task_id,
            status=dr.status,
            output=dr.output,
            error=dr.error,
            duration=dr.duration_ms / 1000.0,
            model_name=st.model.name if st and st.model else "",
            model_provider=st.model.provider if st and st.model else "",
        ))

    # 若 DAG 被 abort，補上跳過的子任務
    if report.status == "aborted":
        completed_ids = {r.task_id for r in results}
        for st in plan.subtasks:
            if st.id not in completed_ids:
                results.append(TaskResult(
                    task_id=st.id,
                    description=st.description,
                    status="skipped",
                    output="(aborted by director feedback)",
                ))

    return results


# ══════════════════════════════════════════════════
# A→K 橋接：absorb()
# ══════════════════════════════════════════════════

def absorb(results: list[TaskResult], source: str = "",
           memory_keys: Optional[list[str]] = None,
           skill_names: Optional[list[str]] = None,
           rag_domain: str = "") -> AbsorptionReport:
    """執行結果 → Analyzer 實際寫入 KM。

    與之前不同：此函數不再只是生成建議。
    當 rag_domain 指定時，**實際將 completed 任務內容寫入 KAFED 向量庫**。

    Args:
        results: execute() 的輸出
        source: 來源標識
        memory_keys: 要存入 memory 的洞察列表（建議，由 Agent 執行）
        skill_names: 要更新/創建的 skill 列表（建議，由 Agent 執行）
        rag_domain: 要存入 KAFED 向量庫的域（空=不存）。非空=實際寫入

    Returns:
        AbsorptionReport — 含實際寫入的統計
    """
    completed = [r for r in results if r.status == "completed"]
    failed = [r for r in results if r.status == "failed"]
    skipped = [r for r in results if r.status == "skipped"]

    rag_entries = 0
    # 如果指定了 rag_domain，將 completed 任務內容實際寫入 KAFED
    if rag_domain and completed:
        try:
            from kafed.knowledge.rag.vector_store import VectorStore
            from kafed.knowledge.rag.chunker import chunk_document
            from kafed.knowledge.flywheel.event_checker import EventChecker

            vs = VectorStore()
            ec = EventChecker(vs, None)  # RAGEngine not needed for after_ingest

            for r in completed:
                if r.output and len(r.output) > 20:
                    # 分塊（如果內容較長）
                    chunks = chunk_document(r.output)
                    if not chunks:
                        chunks = [r.output]

                    texts = []
                    metadatas = []
                    ids = []
                    for j, chunk in enumerate(chunks):
                        texts.append(chunk)
                        metadatas.append({
                            "domain": rag_domain,
                            "source": source or "absorb",
                            "task_id": r.task_id,
                            "description": r.description[:100],
                        })
                        import hashlib
                        _uid = hashlib.md5(str(chunk).encode()).hexdigest()[:12]
                        ids.append(f"{rag_domain}_absorb_{r.task_id}_{_uid}")

                    vs.add(texts, metadatas=metadatas, ids=ids)
                    rag_entries += len(texts)

                    # 觸發 E1 事件檢查（里程碑）
                    ec.after_ingest(rag_domain, vs.count_by_domain(rag_domain))

        except Exception as e:
            import logging
            logging.getLogger("kafed.orchestrator").warning(
                "absorb RAG 寫入失敗: %s", e
            )

    report = AbsorptionReport(
        memory_items=memory_keys or [],
        skill_updates=skill_names or [],
        rag_entries=rag_entries,
        summary=f"  {len(completed)} 完成, {len(failed)} 失敗, "
                f"{len(skipped)} 跳過, RAG寫入 {rag_entries} 條",
    )

    # 失敗任務 → backlog 建議
    for r in failed:
        report.backlog_items.append(f"{r.task_id}: {r.description} (失敗: {r.error})")

    return report


def solidify(insight: str, target: str = "memory", domain: str = "GENERAL",
             title: str = "") -> dict:
    """將一條洞察固話到指定的存儲目標。

    這是 D固 步驟的實際執行函數。
    一次調用寫入一個目標，避免 Agent 跳過 KAFED 知識管道的問題。

    Args:
        insight: 洞察內容
        target: "memory" → Hermes memory
                "kafed" → KAFED 向量庫
                "backlog" → backlog 待辦
                "event" → 觸發飛輪事件檢查
        domain: 域名（用於 kafed/event 目標）
        title: 可選標題（用於 backlog/memory）

    Returns:
        {"status": str, "target": str, "detail": str}
    """
    result = {"target": target, "status": "ok", "detail": ""}

    if target == "memory":
        # 建議 Agent 調用 memory() 工具
        result["detail"] = f"建議寫入 memory: {insight[:80]}..."
        result["agent_action"] = "memory"

    elif target == "kafed":
        try:
            from kafed.knowledge.rag.vector_store import VectorStore
            from kafed.knowledge.rag.chunker import chunk_document
            from kafed.knowledge.flywheel.event_checker import EventChecker

            vs = VectorStore()
            chunks = chunk_document(insight) or [insight]

            texts = []
            metadatas = []
            ids = []
            for j, chunk in enumerate(chunks):
                texts.append(chunk)
                metadatas.append({"domain": domain, "source": "solidify"})
                import hashlib
                _uid = hashlib.md5(chunk.encode()).hexdigest()[:12]
                ids.append(f"{domain}_solidify_{_uid}")

            vs.add(texts, metadatas=metadatas, ids=ids)

            ec = EventChecker(vs, None)
            ec.after_ingest(domain, vs.count_by_domain(domain))

            result["detail"] = f"已寫入 KAFED {domain}: {len(chunks)} 條"
        except Exception as e:
            result["status"] = "error"
            result["detail"] = str(e)

    elif target == "backlog":
        try:
            from kafed.orchestrator import backlog_push
            backlog_push(title or "洞察", value=0.5, effort=insight[:80])
            result["detail"] = f"已推入 backlog: {insight[:60]}..."
        except Exception as e:
            result["status"] = "error"
            result["detail"] = str(e)

    elif target == "event":
        try:
            from kafed.knowledge.rag.vector_store import VectorStore
            from kafed.knowledge.flywheel.event_checker import EventChecker

            vs = VectorStore()
            ec = EventChecker(vs, None)
            count = vs.count_by_domain(domain)
            events = ec.after_ingest(domain, count)
            result["detail"] = f"E1-E5 檢查 {domain}: {len(events)} 事件"
        except Exception as e:
            result["status"] = "error"
            result["detail"] = str(e)

    return result


# ══════════════════════════════════════════════════
# Backlog 橋接
# ── Backlog 橋接（路徑由全局 config 管理） ──────────────


def backlog_check() -> list[dict]:
    """檢查 backlog 待辦。返回 pending items。"""
    try:
        bdp = get_config().backlog_data
        data = json.loads(bdp.read_text())
        items = data.get("items", [])
        pending = [i for i in items if i.get("status") == "pending"]
        pending.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
        return pending
    except Exception:
        return []


def backlog_push(title: str, value: float = 0.7,
                 urgency: float = 0.5, effort: str = "?",
                 category: str = "backlog") -> bool:
    """推入 backlog。返回是否成功。"""
    import subprocess
    try:
        bs = get_config().backlog_script
        r = subprocess.run(
            [sys.executable, str(bs), "--add", title, str(value), str(urgency)],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def backlog_done(task_id: str) -> bool:
    """標記 backlog 完成。返回是否成功。"""
    import subprocess
    try:
        bs = get_config().backlog_script
        r = subprocess.run(
            [sys.executable, str(bs), "--done", task_id],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


# ══════════════════════════════════════════════════
# F→E 真實調度橋接
# ══════════════════════════════════════════════════

def dispatch_for(task_result: TaskResult, goal: str = "", context: str = "") -> DispatchResult:
    """Finder 選中模型 → Executor delegate_to_subagent 參數。

    使用 Executor 層的 delegate_to_subagent() 生成完整的子代理委託方案，
    包括 KAFED root 路徑自動檢測和 context 注入。

    調用者（Agent）：
        dr = dispatch_for(result, goal="審計代碼")
        if dr.is_success:
            params = json.loads(dr.output)
            delegate_task(**params)

    若 model 為空（Finder 未指定），返回默認 delegate（不指定模型）。
    """
    from kafed.executor.dispatcher import Dispatcher
    model_name = task_result.model_name or ""
    model_provider = task_result.model_provider or ""
    return Dispatcher.delegate_to_subagent(
        goal=goal,
        context=context,
        model_name=model_name,
        model_provider=model_provider,
        task_id=task_result.task_id if hasattr(task_result, 'task_id') else "dispatch",
    )


def needs_dispatch(task_result: TaskResult, current_model: str = "") -> bool:
    """當前模型是否即 Finder 選中的模型？不同則需要 delegate_task。"""
    if not task_result.model_name:
        return False  # Finder 未指定，用默認
    if current_model and task_result.model_name == current_model:
        return False  # 當前模型即 Finder 選中，直接執行
    return True       # 需要 dispatch 到 Finder 選中的模型


# ══════════════════════════════════════════════════
# Session 生命周期
# ══════════════════════════════════════════════════

def session_start() -> Optional[dict]:
    """Session 開始時調用。返回最高優先的 backlog 待辦（如有）。"""
    pending = backlog_check()
    if pending:
        top = pending[0]
        print(f"  backlog 待辦: {top.get('title', '?')[:60]} "
              f"(優先級: {top.get('priority_score', 0):.3f})")
        return top
    return None


def session_end(unfinished: list[dict] = None):
    """Session 結束前調用。將未完成任務推回 backlog。"""
    if unfinished:
        for u in unfinished:
            backlog_push(
                title=u.get("title", u.get("description", "未完成任務")),
                value=u.get("value", 0.6),
                urgency=u.get("urgency", 0.5),
                category=u.get("category", "backlog"),
            )
        print(f"  → {len(unfinished)} 未完成推回 backlog")
    if backlog_check():
        print(f"  backlog 待辦: {len(backlog_check())} 項")


# ══════════════════════════════════════════════════
# 總結
# ══════════════════════════════════════════════════

def status() -> str:
    """完整五層狀態。"""
    lines = ["= KAFED Orchestrator 狀態 ="]
    lines.append("")

    # D 層
    lines.append("D Director — 活躍 (SOUL Pipeline)")
    lines.append("  · YiCeNet 🔮 卦象預判")
    lines.append("  · EVAL 五維評估")
    lines.append("  · PipelineRunner 3條")

    # F 層
    finder = _get_finder()
    try:
        registry = finder.registry
        workers_count = len(registry._cache) if hasattr(registry, '_cache') else 0
        lines.append(f"F Finder — 活躍 ({workers_count} workers)")
    except Exception:
        lines.append("F Finder — 導入成功")

    # E 層
    lines.append("E Executor — DAG 調度器就緒")

    # A 層
    from kafed.analyzer import list_tasks as a_tasks
    lines.append(f"A Analyzer — {len(a_tasks())} 規劃任務")

    # K 層
    try:
        from kafed.client.local_backend import KafedLocalBackend
        kb = KafedLocalBackend()
        s = kb.stats()
        lines.append(f"K Knowledge — {s.get('total_chunks', '?')} chunks")
    except Exception as e:
        lines.append(f"K Knowledge — 導入錯誤: {e}")

    # Backlog
    pending = backlog_check()
    lines.append(f"B Backlog — {len(pending)} 待辦")
    if pending:
        for p in pending[:3]:
            lines.append(f"  · {p.get('title', '?')[:50]} ({p.get('priority_score', 0):.3f})")

    return "\n".join(lines)
