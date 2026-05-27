"""
KAFED Action Registry — Command 模式全局註冊表。

每個 Action 是一個自包含的可執行對象：
  - 有永久 ID（不依賴語言）
  - 有多語言標籤
  - 有可選的執行函數
  - 統一注入 flow/log/perf

用法：
    from kafed.action_registry import registry, Action, ExecutionResult

    # 註冊
    registry.register(Action(
        id="knowledge_query",
        code="K",
        labels={"zh": "詢", "en": "Query"},
        description="RAG 向量查詢",
        fn=rag_engine.query,
    ))

    # 執行
    result = registry.get("knowledge_query").execute(question="...")

    # 解析
    action_id = registry.resolve("K", "詢")  # → "knowledge_query"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ── ExecutionResult ─────────────────────────


@dataclass
class ExecutionResult:
    """Action 執行回報——統一承載狀態、耗時、信號。"""
    action_id: str
    status: str = "success"           # success / error / skipped
    elapsed: float = 0.0              # 執行耗時（秒）
    detail: str = ""                  # 摘要資訊
    data: Any = None                  # 執行結果
    signals: dict = field(default_factory=dict)  # 重要回饋信號


# ── Action ─────────────────────────────────


@dataclass
class Action:
    """一個可執行的原子動作。

    id         — 永久唯一標識，"knowledge_query"
    code       — KAFED 層代碼，"K" | "F" | "E" | "D" | "A" | "B" | "S" | "P"
    labels     — 多語言標籤 {"zh": "詢", "en": "Query"}
    description— 人類可讀描述
    fn         — 可選的可調用執行體
    """
    id: str
    code: str
    labels: dict[str, str]
    description: str = ""
    fn: Optional[Callable] = None

    def execute(self, **kwargs) -> ExecutionResult:
        """執行 Action，統一注入 flow/log/perf。

        1. 推入全局 flow chain
        2. 計時 elapsed
        3. 捕獲狀態
        4. 返回 ExecutionResult
        """
        from kafed.client.flow import hop as _flow_hop

        # 推入全局鏈
        _flow_hop(self.code, self.labels.get("zh", self.id),
                  kwargs.get("_detail", ""))

        if self.fn is None:
            # 無實際執行體——純註冊用
            return ExecutionResult(
                action_id=self.id, status="skipped",
                detail=f"{self.id} has no fn"
            )

        start = time.perf_counter()
        try:
            data = self.fn(**kwargs)
            elapsed = time.perf_counter() - start
            detail = kwargs.get("_detail", "")
            result = ExecutionResult(
                action_id=self.id, status="success",
                elapsed=elapsed, detail=detail, data=data,
            )
            # 如果 fn 返回了 ExecutionResult，直接繼承
            if isinstance(data, ExecutionResult):
                result = data
            return result
        except Exception as e:
            elapsed = time.perf_counter() - start
            return ExecutionResult(
                action_id=self.id, status="error",
                elapsed=elapsed, detail=str(e)[:200],
                signals={"error": str(e)},
            )


# ── Registry ─────────────────────────────────


class _Registry:
    """全局 Action 註冊表——單例。"""

    def __init__(self):
        self._actions: dict[str, Action] = {}
        # (code, label) → action_id  用於反向解析
        self._by_code_label: dict[tuple[str, str], str] = {}

    def register(self, action: Action):
        """註冊一個 Action。之後可通過 get() / resolve() 取得。"""
        self._actions[action.id] = action
        for lang, label in action.labels.items():
            self._by_code_label[(action.code, label)] = action.id

    def get(self, action_id: str) -> Optional[Action]:
        """通過 action_id 取得 Action。"""
        return self._actions.get(action_id)

    def resolve(self, code: str, label: str) -> Optional[str]:
        """給定 (code, label)，返回 action_id。
        例如 resolve("K", "詢") → "knowledge_query"
        """
        return self._by_code_label.get((code, label))

    def all_actions(self) -> dict[str, Action]:
        """返回所有已註冊 Action 的拷貝。"""
        return dict(self._actions)

    def by_layer(self, code: str) -> dict[str, Action]:
        """返回指定層的所有 Action。"""
        return {aid: a for aid, a in self._actions.items() if a.code == code}


# 全局單例
registry = _Registry()