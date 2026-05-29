"""
Loom — 三層資料模型。

Turn（原子輪次）→ Session（技術切片）→ Conversation（邏輯主體）
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TurnRecord:
    """對話中的單一輪次（recommend → 行動 → solidify）。"""
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    query: str = ""
    hexagram: dict = field(default_factory=dict)       # {id, name, q_value, candidates}
    knowledge: dict = field(default_factory=dict)       # {memory, wiki, skills, recall, rag}
    eval_score: dict = field(default_factory=dict)      # {tier, score, f1_scope}
    token_usage: dict = field(default_factory=lambda: {"prompt": 0, "completion": 0, "total": 0})
    response_time: float = 0.0                          # 秒
    steps_taken: list[str] = field(default_factory=list) # [D問, D卦, D召, D評, ...]
    reward_signals: list[dict] = field(default_factory=list)
    user_feedback: Optional[str] = None                 # "correction" | "affirmation" | None
    solidify_result: Optional[dict] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def is_efficient(self) -> bool:
        """基本 4 步（問卦召評）+ 最多 2 步額外 = 高效"""
        return len(self.steps_taken) <= 6

    @property
    def had_correction(self) -> bool:
        return self.user_feedback == "correction"

    @property
    def had_affirmation(self) -> bool:
        return self.user_feedback == "affirmation"

    def add_reward(self, source: str, value: float, note: str = ""):
        self.reward_signals.append({
            "source": source, "value": value,
            "note": note, "timestamp": time.time(),
        })


@dataclass
class SessionRecord:
    """技術切片。因 idle、重啟等技術原因自然閉合，不切斷 conversation。"""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    conversation_id: str = ""
    turns: list[TurnRecord] = field(default_factory=list)
    solidify_log: list[dict] = field(default_factory=list)
    event_buffer: list[dict] = field(default_factory=list)
    close_reason: str = ""   # "idle" | "explicit" | "system"
    created_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None

    # ── 匯總（即時計算）──

    def add_turn(self, turn: TurnRecord):
        self.turns.append(turn)

    def add_solidify(self, result: dict):
        self.solidify_log.append(result)
        if self.turns:
            self.turns[-1].solidify_result = result

    def add_event(self, event: dict):
        self.event_buffer.append(event)

    def close(self, reason: str = "idle"):
        self.close_reason = reason
        self.closed_at = time.time()

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def total_tokens(self) -> int:
        return sum(t.token_usage["total"] for t in self.turns)

    @property
    def hexagram_ids(self) -> list[int]:
        return [t.hexagram.get("id", 0) for t in self.turns if t.hexagram.get("id")]

    def hexagram_pattern(self) -> str:
        ids = self.hexagram_ids
        if len(ids) < 2:
            return "single"
        diffs = [abs(ids[i] - ids[i-1]) for i in range(1, len(ids))]
        avg = sum(diffs) / len(diffs)
        if avg <= 1:
            return "stable"
        if avg <= 5:
            return "drift"
        return "jump"

    @property
    def correction_count(self) -> int:
        return sum(1 for t in self.turns if t.had_correction)

    @property
    def token_waste(self) -> int:
        return sum(t.token_usage["total"] for t in self.turns if not t.is_efficient)

    def key_turns(self, n: int = 3) -> list[TurnRecord]:
        """找出最關鍵的 n 個轉折點（有用戶回饋、Q 值劇變、卦跳躍）。"""
        scored = []
        for i, t in enumerate(self.turns):
            score = 0
            if t.had_correction:
                score += 10
            if t.had_affirmation:
                score += 5
            if i > 0 and abs(
                t.hexagram.get("q_value", 0.5) - self.turns[i-1].hexagram.get("q_value", 0.5)
            ) > 0.3:
                score += 3
            scored.append((score, i, t))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [t for _, _, t in scored[:n]]

    def summarize(self) -> dict:
        return {
            "session_id": self.session_id,
            "turns": self.turn_count,
            "total_tokens": self.total_tokens,
            "solidifies": len(self.solidify_log),
            "hexagram_pattern": self.hexagram_pattern(),
            "hexagram_evolution": self.hexagram_ids,
            "corrections": self.correction_count,
            "token_waste": self.token_waste,
            "close_reason": self.close_reason,
            "duration": (self.closed_at or time.time()) - self.created_at,
        }


@dataclass
class ConversationRecord:
    """邏輯主體。跨技術邊界，不因 idle/重啟而終止。"""
    conversation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    sessions: list[SessionRecord] = field(default_factory=list)
    status: str = "active"       # "active" | "closed"
    topic_centroid: list[float] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None

    def add_session(self, session: SessionRecord):
        session.conversation_id = self.conversation_id
        self.sessions.append(session)

    def update_centroid(self, new_embedding: list[float],
                        weight: float = 0.3) -> None:
        """加權滾動平均更新話題 centroid。

        weight 是新嵌入的權重（0∼1）。weight=0.3 表示新輪佔 30%，
        最近話題趨勢比遠古輪更靈敏。
        """
        if not new_embedding:
            return
        if not self.topic_centroid or len(self.topic_centroid) != len(new_embedding):
            self.topic_centroid = list(new_embedding)
            return
        for i in range(len(self.topic_centroid)):
            self.topic_centroid[i] = (
                self.topic_centroid[i] * (1 - weight) + new_embedding[i] * weight
            )

    @property
    def active_session(self) -> Optional[SessionRecord]:
        return self.sessions[-1] if self.sessions else None

    def close(self):
        self.status = "closed"
        self.closed_at = time.time()
        for s in self.sessions:
            if not s.closed_at:
                s.close("parent_closed")

    @property
    def all_turns(self) -> list[TurnRecord]:
        return [t for s in self.sessions for t in s.turns]

    @property
    def total_tokens(self) -> int:
        return sum(s.total_tokens for s in self.sessions)

    @property
    def knowledge_reuse_rate(self) -> float:
        """同一 (卦+召回分佈) 被重複的比例"""
        seen = set()
        reused = 0
        for t in self.all_turns:
            sig = f"{t.hexagram.get('id', 0)}:{str(sorted(t.knowledge.items()))}"
            if sig in seen:
                reused += 1
            seen.add(sig)
        return reused / len(seen) if seen else 0.0

    def session_summaries(self) -> list[dict]:
        return [s.summarize() for s in self.sessions]

    def reward_for_flywheel(self) -> dict:
        """完整獎勵信號包——飛輪的唯一介面。"""
        all_turns = self.all_turns
        total = self.total_tokens
        return {
            "conversation_id": self.conversation_id,
            "n_sessions": len(self.sessions),
            "n_turns": len(all_turns),
            "total_tokens": total,
            "token_efficiency": float(len(all_turns)) / max(total, 1),
            "hexagram_evolution": [t.hexagram.get("id", 0) for t in all_turns],
            "hexagram_q_avg": (
                sum(t.hexagram.get("q_value", 0.5) for t in all_turns) / max(len(all_turns), 1)
            ),
            "session_patterns": [s.hexagram_pattern() for s in self.sessions],
            "correction_rate": (
                sum(1 for t in all_turns if t.had_correction) / max(len(all_turns), 1)
            ),
            "knowledge_reuse_rate": self.knowledge_reuse_rate,
            "total_solidifies": sum(len(s.solidify_log) for s in self.sessions),
            "duration": (self.closed_at or time.time()) - self.created_at,
        }
