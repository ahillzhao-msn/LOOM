"""KAFED Director — Pipeline 承諾鏈。

不是執行引擎——是執行清單。
不代替 LLM 做判斷——保證 LLM 不會跳步驟。

用法：
    pipe = SOUL_PIPELINES["soul_core"]
    ctx = PipelineContext(pipe)
    while not ctx.done():
        step = ctx.next_step()
        if step:
            # 我（LLM）自己決定怎麼做這步
            result = do_my_thing(step)
            ctx.complete(step.step_id, result)
    ctx.report()  # 走完了
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ── 步驟定義 ──────────────────────────────────


@dataclass
class PipelineStep:
    """Pipeline 中的一個步驟。

    只定義「什麼」，不定義「怎麼做」——怎麼做由 LLM 自己決定。
    """
    step_id: str             # 短碼：卦、評、界、決 ...
    name: str                # 人類可讀：YiCeNet卦象預判、EVAL評估 ...
    optional: bool = False   # True → 此步可跳過
    depends_on: list[str] = field(default_factory=list)  # 前置步驟 ID


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass
class StepRecord:
    """步驟的運行記錄。"""
    step: PipelineStep
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    note: str = ""


# ── Pipeline 定義 ────────────────────────────


@dataclass
class Pipeline:
    """Pipeline 定義——有序的步驟列表。

    SOUL 可以定義多個 Pipeline（快速 vs 深度），
    由 LLM 在每次交互開始時選擇哪條走。
    """
    id: str
    name: str
    steps: list[PipelineStep]


# ── 默認 Pipeline ────────────────────────────
#
# 步序（v2.0 更新）：
#   問 → 卦 → 召(強制,KM知識召回) → 評(帶文脈) → 界 → 決 → 編? → 應 → 固
#
# 「查」已被「召」吸收——知識召回是強制的、在評之前的、跨全源的
#（RAG + Wiki 嵌入命中，Memory/Sessions/Skills 只讀掃描）。
# EVAL 不再從零開始——帶著知識上下文做評估。


SOUL_CORE = Pipeline(
    id="soul_core",
    name="核心循環",
    steps=[
        PipelineStep("問", "5W1H 分解"),
        PipelineStep("卦", "YiCeNet 卦象預判"),
        PipelineStep("召", "KM知識召回 — 嵌入命中, 全源, 強制",
                     depends_on=["卦"]),
        PipelineStep("評", "EVAL 帶文脈評估 — 五維, 已被卦象+知識調製",
                     depends_on=["召"]),
        PipelineStep("界", "Scope 檢查 — 估範圍, 控聯想, 帶問題學",
                     depends_on=["評"]),
        PipelineStep("決", "自決決策樹 — 成本/可逆/先例/目標+知識",
                     depends_on=["界"]),
        PipelineStep("編", "任務編排", optional=True, depends_on=["決"]),
        PipelineStep("應", "生成回應"),
        PipelineStep("固", "固化 — 洞察萃取·知識分流·啟動稽查",
                     depends_on=["應"]),
    ],
)

SOUL_QUICK = Pipeline(
    id="soul_quick",
    name="輕量循環",
    steps=[
        PipelineStep("問", "5W1H 分解"),
        PipelineStep("卦", "YiCeNet 卦象預判"),
        PipelineStep("召", "KM知識召回（輕量）",
                     depends_on=["卦"]),
        PipelineStep("評", "EVAL 快速評估", depends_on=["召"]),
        PipelineStep("應", "生成回應"),
        PipelineStep("固", "固化", depends_on=["應"]),
    ],
)

SOUL_DEEP = Pipeline(
    id="soul_deep",
    name="深度循環",
    steps=[
        PipelineStep("問", "5W1H 分解"),
        PipelineStep("卦", "YiCeNet 卦象預判"),
        PipelineStep("召", "KM深度知識召回",
                     depends_on=["卦"]),
        PipelineStep("評", "EVAL 五維評估", depends_on=["召"]),
        PipelineStep("界", "Scope 檢查", depends_on=["評"]),
        PipelineStep("決", "自決決策樹", depends_on=["界"]),
        PipelineStep("編", "任務編排", depends_on=["決"]),
        PipelineStep("應", "生成回應"),
        PipelineStep("固", "固化深度壓縮", depends_on=["應"]),
    ],
)

SOUL_PIPELINES: dict[str, Pipeline] = {
    "soul_core": SOUL_CORE,
    "soul_quick": SOUL_QUICK,
    "soul_deep": SOUL_DEEP,
}


# ── Runner ────────────────────────────────────


class PipelineRunner:
    """Pipeline 運行時追蹤器。

    三步流程：
    1. next_step() → 告訴我下一步是什麼
    2. 我執行它（自由決定內容）
    3. complete() / skip() → 報告完成

    不走完 non-optional steps，done() 不會返回 True。
    """

    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self._records = {s.step_id: StepRecord(s) for s in pipeline.steps}

    def next_step(self) -> Optional[PipelineStep]:
        """返回第一個就緒的未完成步驟，或 None（全部完成）。"""
        done_ids = {sid for sid, r in self._records.items()
                    if r.status in (StepStatus.DONE, StepStatus.SKIPPED)}
        for step in self.pipeline.steps:
            rec = self._records[step.step_id]
            if rec.status == StepStatus.PENDING:
                # 檢查依賴
                if all(d in done_ids for d in step.depends_on):
                    rec.status = StepStatus.RUNNING
                    return step
                else:
                    rec.status = StepStatus.BLOCKED
        return None

    def complete(self, step_id: str, result: Any = None, note: str = "") -> None:
        """標記步驟完成。"""
        rec = self._records.get(step_id)
        if rec is None:
            raise ValueError(f"未知步驟: {step_id}")
        rec.status = StepStatus.DONE
        rec.result = result
        rec.note = note

    def skip(self, step_id: str, note: str = "") -> None:
        """跳過可選步驟。"""
        rec = self._records.get(step_id)
        if rec is None:
            raise ValueError(f"未知步驟: {step_id}")
        if not rec.step.optional:
            raise ValueError(f"不可跳過 non-optional 步驟: {step_id}")
        rec.status = StepStatus.SKIPPED
        rec.note = note

    def done(self) -> bool:
        """所有步驟（含 optional）都走到了終態 (done / skipped)？"""
        for rec in self._records.values():
            if rec.status not in (StepStatus.DONE, StepStatus.SKIPPED):
                return False
        return True

    def core_done(self) -> bool:
        """僅檢查 non-optional 步驟是否完成（不含 optional pending）。"""
        for rec in self._records.values():
            if not rec.step.optional and rec.status not in (StepStatus.DONE, StepStatus.SKIPPED):
                return False
        return True

    def pending(self) -> list[PipelineStep]:
        """返回尚未完成的步驟列表（用於報告）。"""
        return [r.step for r in self._records.values()
                if r.status in (StepStatus.PENDING, StepStatus.BLOCKED, StepStatus.RUNNING)]

    def report(self) -> str:
        """生成路線圖字串。"""
        parts = []
        for step in self.pipeline.steps:
            rec = self._records[step.step_id]
            icon = {
                StepStatus.DONE: "✓",
                StepStatus.SKIPPED: "—",
                StepStatus.RUNNING: "→",
                StepStatus.BLOCKED: "✗",
                StepStatus.PENDING: "·",
            }.get(rec.status, "?")
            label = step.step_id
            if rec.note:
                label += f"({rec.note})"
            parts.append(f"{icon}{label}")
        return " → ".join(parts)

    def status_of(self, step_id: str) -> StepStatus:
        return self._records[step_id].status

    def result_of(self, step_id: str) -> Any:
        return self._records[step_id].result
