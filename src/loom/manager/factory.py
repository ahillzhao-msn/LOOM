"""Loom — 工廠類（Factory Pattern）。

每個層級有自己的建立者，支援從零建立、從持久化恢復。

三層 conversation 邊界判定（在 recommend() 中透明調用）：
1. 自然遺忘曲線 — elapsed time × turn count 組合衰減
2. Embedding 漂移 — 語義不連續性
3. 24h idle — 最後兜底
"""

from __future__ import annotations

import math
import time
from typing import Any, Optional

from .models import TurnRecord, SessionRecord, ConversationRecord


class TurnFactory:
    """Turn 建立者。匯集本輪所有原始數據，生成統一的 TurnRecord。"""

    @staticmethod
    def create(
        query: str,
        hexagram: Optional[dict] = None,
        knowledge: Optional[dict] = None,
        eval_score: Optional[dict] = None,
        token_usage: Optional[dict] = None,
        steps_taken: Optional[list[str]] = None,
        response_time: float = 0.0,
    ) -> TurnRecord:
        """從零建立。"""
        return TurnRecord(
            query=query,
            hexagram=hexagram or {},
            knowledge=knowledge or {},
            eval_score=eval_score or {},
            token_usage=token_usage or {"prompt": 0, "completion": 0, "total": 0},
            steps_taken=steps_taken or [],
            response_time=response_time,
        )

    @staticmethod
    def from_recommend(
        query: str,
        hexagram: dict,
        knowledge: dict,
        eval_score: dict,
        flow_entries: list,       # Shuttle flow entries
        token_usage: dict,
        response_time: float,
    ) -> TurnRecord:
        """從 loom_recommend() 結果建立 Turn。"""
        steps = []
        for e in flow_entries:
            if isinstance(e, tuple):
                module_code, detail = e[0], e[1] if len(e) > 1 else ""
            else:
                module_code = f"{e.module}{e.action}"
                detail = e.detail or ""
            code = module_code
            if detail:
                code += f"({detail})"
            steps.append(code)

        return TurnRecord(
            query=query,
            hexagram={
                "id": hexagram.get("id", 0),
                "name": hexagram.get("name", ""),
                "q_value": hexagram.get("q_value", 0.5),
                "candidates": hexagram.get("candidates", []),
            },
            knowledge=dict(knowledge),
            eval_score={
                "tier": eval_score.get("tier", ""),
                "score": eval_score.get("score", 0),
                "f1_scope": eval_score.get("f1_scope", ""),
            },
            token_usage=dict(token_usage),
            steps_taken=steps,
            response_time=response_time,
        )

    @staticmethod
    def from_dict(data: dict) -> TurnRecord:
        """從持久化字典恢復。"""
        return TurnRecord(**data)


class SessionFactory:
    """Session 建立者。管理技術邊界。"""

    MAX_IDLE: float = 1800  # 30 分鐘

    @staticmethod
    def create(conversation_id: str = "") -> SessionRecord:
        return SessionRecord(conversation_id=conversation_id)

    @staticmethod
    def is_expired(session: SessionRecord) -> bool:
        if not session.turns:
            return False
        last = session.turns[-1].timestamp
        return (time.time() - last) > SessionFactory.MAX_IDLE

    @staticmethod
    def from_dict(data: dict) -> SessionRecord:
        turns = [TurnFactory.from_dict(t) for t in data.pop("turns", [])]
        s = SessionRecord(**{k: v for k, v in data.items() if k != "turns"})
        s.turns = turns
        return s


class ConversationFactory:
    """Conversation 建立者。管理邏輯邊界。"""

    # 自然遺忘曲線超參
    FORGET_LAMBDA_TIME: float = 0.01   # per hour 衰減
    FORGET_LAMBDA_TURNS: float = 0.005 # per turn 衰減
    FORGET_THRESHOLD: float = 0.30     # 低於此值視為遺忘
    DRIFT_THRESHOLD: float = 0.50      # cosine similarity 低於此值視為漂移

    @staticmethod
    def create(topic_centroid: Optional[list[float]] = None) -> ConversationRecord:
        return ConversationRecord(topic_centroid=topic_centroid or [])

    @staticmethod
    def forgetting_score(conv: ConversationRecord) -> float:
        """自然遺忘曲線。

        返回 0.0（完全遺忘）∼ 1.0（完全新鮮）。

        公式：exp(-λ_t × elapsed_hours) × exp(-λ_n × turn_count)
        雙指數確保：長時間少輪 > 短時間多輪 > 短時間少輪
        """
        elapsed_hours = (time.time() - conv.created_at) / 3600.0
        n_turns = len(conv.all_turns)
        return math.exp(
            -ConversationFactory.FORGET_LAMBDA_TIME * elapsed_hours
            -ConversationFactory.FORGET_LAMBDA_TURNS * n_turns
        )

    @staticmethod
    def should_close(
        conv: ConversationRecord,
        new_query: str = "",
        new_query_embedding: Optional[list[float]] = None,
    ) -> bool:
        """判斷 conversation 是否應該關閉。

        三層邊界判定（優先級由高到低）：
        1. 自然遺忘 — forgetting_score < FORGET_THRESHOLD
        2. Embedding 漂移 — cosine(new_emb, centroid) < DRIFT_THRESHOLD
        3. 24h idle — 最後兜底
        """
        # 1. 自然遺忘
        if ConversationFactory.forgetting_score(conv) < ConversationFactory.FORGET_THRESHOLD:
            return True

        # 2. Embedding 漂移
        if new_query_embedding and conv.topic_centroid:
            if len(new_query_embedding) == len(conv.topic_centroid):
                dot = sum(a * b for a, b in zip(new_query_embedding, conv.topic_centroid))
                norm_a = math.sqrt(sum(x * x for x in new_query_embedding))
                norm_b = math.sqrt(sum(x * x for x in conv.topic_centroid))
                if norm_a > 0 and norm_b > 0:
                    similarity = dot / (norm_a * norm_b)
                    if similarity < ConversationFactory.DRIFT_THRESHOLD:
                        return True

        # 3. 24h idle（既有規則）
        if conv.sessions:
            last_turn = conv.all_turns[-1]
            if (time.time() - last_turn.timestamp) > 86400:
                return True

        return False

    @staticmethod
    def from_dict(data: dict) -> ConversationRecord:
        sessions = [SessionFactory.from_dict(s) for s in data.pop("sessions", [])]
        c = ConversationRecord(**{k: v for k, v in data.items() if k != "sessions"})
        c.sessions = sessions
        return c
