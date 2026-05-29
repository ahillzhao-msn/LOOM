"""
Loom — ConversationManager。

KAFED 與 Loom 的唯一交互入口。
管理 conversation/session 生命週期，軌跡累積與獎勵聚合。

使用方式（在 recommend() 開頭）：
    from kafed.loom import manager as loom
    loom.start_turn(query, hexagram, knowledge, eval, tokens, flow_entries)
    ...
    loom.end_turn(user_feedback=None)
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .models import TurnRecord, SessionRecord, ConversationRecord
from .factory import TurnFactory, SessionFactory, ConversationFactory


class _ConversationManager:
    """Manager 單例。整個 KAFED 生命週期持有一個。"""

    def __init__(self):
        self._conversation: Optional[ConversationRecord] = None
        self._current_turn: Optional[TurnRecord] = None

    # ── Conversation ──

    @property
    def conversation(self) -> Optional[ConversationRecord]:
        return self._conversation

    def get_or_create_conversation(self) -> ConversationRecord:
        """獲取當前 conversation，不存在則創建。"""
        if self._conversation is None:
            self._conversation = ConversationFactory.create()
        elif ConversationFactory.should_close(self._conversation):
            self.close_conversation()
            self._conversation = ConversationFactory.create()
        return self._conversation

    def close_conversation(self, reason: str = "natural"):
        """關閉當前 conversation → 寫入 SESSION_TRACE → 通知 YiCeNet 飛輪。"""
        if self._conversation is None:
            return
        if self._current_turn:
            self._current_turn = None
        self._conversation.close()
        reward = self._conversation.reward_for_flywheel()

        # 通知 YiCeNet 飛輪（非強制——YiCeNet 可能未安裝）
        try:
            from yicenet.flywheel import submit_trajectory
            submit_trajectory({
                "producer": "loom",
                "version": 1,
                "conversation_id": self._conversation.conversation_id,
                "trajectory": reward,
                "embedding": self._conversation.topic_centroid,
            })
        except (ImportError, AttributeError):
            pass  # YiCeNet 未安裝或 API 不匹配，跳過

        # TODO: 寫入 Chroma domain=SESSION_TRACE
        self._conversation = None
        return reward

    # ── Session ──

    @property
    def active_session(self) -> Optional[SessionRecord]:
        conv = self._conversation
        if conv and conv.sessions:
            return conv.sessions[-1]
        return None

    def _ensure_session(self) -> SessionRecord:
        """確保有活躍 session。過期則自動閉開。"""
        conv = self.get_or_create_conversation()
        session = self.active_session
        if session is None or SessionFactory.is_expired(session):
            # 關閉舊 session
            if session:
                session.close("idle")
            # 創建新 session
            session = SessionFactory.create(conversation_id=conv.conversation_id)
            conv.add_session(session)
        return session

    # ── Turn ──

    def start_turn(
        self,
        query: str,
        hexagram: Optional[dict] = None,
        knowledge: Optional[dict] = None,
        eval_score: Optional[dict] = None,
        token_usage: Optional[dict] = None,
        steps_taken: Optional[list[str]] = None,
        response_time: float = 0.0,
    ) -> TurnRecord:
        """開始新一輪。自動管理 session 邊界。"""
        session = self._ensure_session()
        turn = TurnFactory.create(
            query=query,
            hexagram=hexagram,
            knowledge=knowledge,
            eval_score=eval_score,
            token_usage=token_usage,
            steps_taken=steps_taken,
            response_time=response_time,
        )
        session.add_turn(turn)
        self._current_turn = turn
        return turn

    def start_turn_from_recommend(
        self,
        query: str,
        hexagram: dict,
        knowledge: dict,
        eval_score: dict,
        flow_entries: list,
        token_usage: dict,
        response_time: float,
    ) -> TurnRecord:
        """從 kafed_recommend() 結果開始新輪。"""
        session = self._ensure_session()
        turn = TurnFactory.from_recommend(
            query=query,
            hexagram=hexagram,
            knowledge=knowledge,
            eval_score=eval_score,
            flow_entries=flow_entries,
            token_usage=token_usage,
            response_time=response_time,
        )
        session.add_turn(turn)
        self._current_turn = turn
        return turn

    def end_turn(self, user_feedback: Optional[str] = None):
        """結束當前輪，記錄用戶回饋。"""
        if self._current_turn:
            self._current_turn.user_feedback = user_feedback
            self._current_turn = None

    def record_solidify(self, result: dict):
        """將 solidify() 結果記入當前 session。"""
        session = self.active_session
        if session:
            session.add_solidify(result)

    def reward_for_flywheel(self) -> dict:
        """獲取當前 conversation 的獎勵信號包。"""
        if self._conversation:
            return self._conversation.reward_for_flywheel()
        return {}

    # ── 摘要 ──

    def status(self) -> dict:
        """當前狀態快照。"""
        conv = self._conversation
        session = self.active_session
        return {
            "has_conversation": conv is not None,
            "conversation_id": conv.conversation_id if conv else None,
            "conversation_status": conv.status if conv else None,
            "session_count": len(conv.sessions) if conv else 0,
            "active_session_turns": session.turn_count if session else 0,
            "total_turns": len(conv.all_turns) if conv else 0,
            "current_turn_active": self._current_turn is not None,
        }


# 全域單例
manager = _ConversationManager()


def get_manager() -> _ConversationManager:
    return manager
