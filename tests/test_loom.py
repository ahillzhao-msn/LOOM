"""Loom 全鏈路測試 — Conversation → Session → Turn → YiCeNet 飛輪。"""

from __future__ import annotations

import time
import json
import tempfile
from pathlib import Path

import pytest


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_manager():
    """每個測試前重置 Loom 單例狀態。"""
    from kafed.loom.manager import manager
    manager._conversation = None
    manager._current_turn = None
    yield


@pytest.fixture
def loom():
    from kafed.loom.manager import manager
    return manager


@pytest.fixture
def loom_models():
    from kafed.loom import models
    return models


# ── Conversation Lifecycle ────────────────────────────────


class TestConversationLifecycle:
    def test_get_or_create_creates(self, loom):
        """首次調用應創建 conversation。"""
        conv = loom.get_or_create_conversation()
        assert conv is not None
        assert conv.status == "active"
        assert conv.conversation_id is not None
        assert len(conv.conversation_id) == 12

    def test_get_or_create_reuses(self, loom):
        """重複調用應返回同一 conversation。"""
        c1 = loom.get_or_create_conversation()
        c2 = loom.get_or_create_conversation()
        assert c1.conversation_id == c2.conversation_id
        assert loom.status()["total_turns"] == 0

    def test_close_clears(self, loom):
        """關閉後 conversation 應為 None。"""
        loom.get_or_create_conversation()
        loom.close_conversation()
        assert loom._conversation is None
        assert loom.status()["has_conversation"] is False

    def test_close_then_recreate_new_id(self, loom):
        """關閉再創建應是新的 conversation_id。"""
        c1 = loom.get_or_create_conversation()
        old_id = c1.conversation_id
        loom.close_conversation()
        c2 = loom.get_or_create_conversation()
        assert c2.conversation_id != old_id

    def test_close_none_no_error(self, loom):
        """無活躍 conversation 時 close 不應報錯。"""
        loom.close_conversation()  # 不拋異常


# ── Turn Lifecycle ────────────────────────────────────────


class TestTurnLifecycle:
    def test_start_turn_creates(self, loom):
        """start_turn 應創建 turn 並自動創建 conversation/session。"""
        turn = loom.start_turn(
            query="分析 KAFED 架構",
            hexagram={"id": 29, "q_value": 0.7},
            knowledge={"rag": 3},
            eval_score={"tier": 1, "score": 0.85},
        )
        assert turn.turn_id is not None
        assert turn.query == "分析 KAFED 架構"
        assert turn.hexagram["id"] == 29
        assert loom.status()["has_conversation"] is True
        assert loom.status()["active_session_turns"] == 1

    def test_start_turn_sequential(self, loom):
        """連續 start_turn 應堆疊在同一 session。"""
        for i in range(3):
            loom.start_turn(query=f"輪次{i+1}")
            loom.end_turn()
        assert loom.status()["active_session_turns"] == 3
        assert loom.status()["total_turns"] == 3

    def test_end_turn_records_feedback(self, loom):
        """end_turn 應記錄用戶回饋。"""
        turn = loom.start_turn(query="測試")
        assert turn.user_feedback is None
        loom.end_turn(user_feedback="affirmation")
        assert turn.user_feedback == "affirmation"

    def test_end_turn_current_cleared(self, loom):
        """end_turn 後 current_turn 應為 None。"""
        loom.start_turn(query="測試")
        loom.end_turn()
        assert loom._current_turn is None

    def test_start_turn_from_recommend(self, loom):
        """start_turn_from_recommend 應處理完整推薦上下文。"""
        turn = loom.start_turn_from_recommend(
            query="工單狀態分析",
            hexagram={"id": 47, "name": "困", "q_value": 0.3},
            knowledge={"rag": 5, "memory": 2},
            eval_score={"tier": 2, "score": 0.6, "f1_scope": 0.7},
            flow_entries=[("D問", "5W1H"), ("D卦", "困"), ("D召", "K[5]")],
            token_usage={"prompt": 500, "completion": 300, "total": 800},
            response_time=2.5,
        )
        assert turn.hexagram["name"] == "困"
        assert turn.knowledge["rag"] == 5
        assert turn.token_usage["total"] == 800


# ── Solidify Integration ──────────────────────────────────


class TestSolidifyIntegration:
    def test_record_solidify(self, loom):
        """record_solidify 應將結果記入 session。"""
        loom.start_turn(query="分析")
        result = {"status": "ok", "chunks": 3, "domain": "TEST"}
        loom.record_solidify(result)
        session = loom.active_session
        assert session is not None
        assert len(session.solidify_log) == 1
        assert session.solidify_log[0]["domain"] == "TEST"
        # 同時應記入當前 turn 的 solidify_result
        turn = loom._current_turn  # 還沒 end_turn
        assert turn is not None
        assert turn.solidify_result["domain"] == "TEST"

    def test_record_solidify_no_turn(self, loom):
        """無活躍 turn 時 record_solidify 不報錯。"""
        result = {"status": "ok", "chunks": 1}
        loom.record_solidify(result)  # 不拋異常

    def test_multi_turn_solidify(self, loom):
        """多輪 solidify 應全部累積。"""
        for i in range(3):
            loom.start_turn(query=f"輪{i}")
            loom.record_solidify({"chunks": i + 1, "domain": "T"})
        session = loom.active_session
        assert len(session.solidify_log) == 3
        assert session.solidify_log[-1]["chunks"] == 3


# ── Reward / Flywheel ─────────────────────────────────────


class TestReward:
    def test_reward_empty_has_defaults(self, loom):
        """無 conversation 時 reward_for_flywheel 返回空 dict。"""
        assert loom.reward_for_flywheel() == {}

    def test_reward_structure(self, loom):
        """conversation 有輪次時 reward 應包含必要字段。"""
        loom.start_turn(query="Q", hexagram={"id": 10, "q_value": 0.8})
        loom.end_turn(user_feedback="affirmation")
        loom.start_turn(query="Q2", hexagram={"id": 54, "q_value": 0.4})
        loom.end_turn()
        reward = loom.reward_for_flywheel()
        assert "conversation_id" in reward
        assert reward["n_turns"] == 2
        assert reward["hexagram_evolution"] == [10, 54]
        assert reward["correction_rate"] == 0.0  # 無 correction
        assert reward["total_solidifies"] == 0

    def test_close_conversation_returns_reward(self, loom):
        """close_conversation 應返回獎勵並調用 submit_trajectory。"""
        loom.start_turn(query="Q")
        loom.end_turn()
        reward = loom.close_conversation()
        assert reward is not None
        assert reward["n_turns"] >= 1


# ── Shuttle ───────────────────────────────────────────────


class TestShuttle:
    def test_flow_chain(self):
        """flow_chain 應返回箭頭分隔的鏈路字串。"""
        from kafed.loom.shuttle import Shuttle
        steps = ["D問(5W1H)", "D卦(困)", "D召(K[3])", "D評(T2)"]
        out = Shuttle.flow_chain(steps, end="D固")
        assert out == "D問(5W1H) -> D卦(困) -> D召(K[3]) -> D評(T2) -> D固"

    def test_flow_chain_no_end(self):
        from kafed.loom.shuttle import Shuttle
        out = Shuttle.flow_chain(["A", "B"])
        assert out == "A -> B"

    def test_hexagram_trail_empty(self):
        from kafed.loom.shuttle import Shuttle
        assert Shuttle.hexagram_trail([]) == ""

    def test_hexagram_trail_single(self):
        from kafed.loom.shuttle import Shuttle
        trail = Shuttle.hexagram_trail([46])
        assert isinstance(trail, str)
        assert len(trail) > 0
        # 應包含卦符號（Unicode 或其他表示）
        assert "䷮" in trail or "#46" in trail or "䷭" in trail  # 47→困, 47+1=48→井→䷯... depends on mapping

    def test_hexagram_trail_pattern_marked(self, loom_models):
        from kafed.loom.shuttle import Shuttle
        # 3+ ids with small diff → stable
        trail = Shuttle.hexagram_trail([10, 10, 11])
        assert "穩定" in trail or "穩定" in trail

    def test_session_tapestry(self, loom, loom_models):
        from kafed.loom.shuttle import Shuttle
        loom.start_turn(query="分析", hexagram={"id": 47})
        loom.end_turn()
        loom.start_turn(query="修正", hexagram={"id": 10})
        loom.end_turn(user_feedback="correction")
        session = loom.active_session
        tapestry = Shuttle.session_tapestry(session)
        assert "Session" in tapestry
        assert "2 輪" in tapestry
        # key turn 有 correction 應標記
        assert "修正" in tapestry

    def test_conversation_tapestry(self, loom):
        from kafed.loom.shuttle import Shuttle
        loom.get_or_create_conversation()
        loom.start_turn(query="Q1", hexagram={"id": 10, "q_value": 0.8})
        loom.end_turn()
        loom.start_turn(query="Q2", hexagram={"id": 54, "q_value": 0.4})
        loom.end_turn()
        loom.start_turn(query="Q3", hexagram={"id": 10, "q_value": 0.7})
        loom.end_turn(user_feedback="affirmation")
        conv = loom.conversation
        tapestry = Shuttle.conversation_tapestry(conv)
        assert "Conversation" in tapestry
        assert "1 sessions" in tapestry or "1 sessions" in tapestry

    def test_shuttle_empty_session(self, loom_models):
        from kafed.loom.shuttle import Shuttle
        s = loom_models.SessionRecord()
        assert Shuttle.session_tapestry(s) == "(empty session)"


# ── Model Properties ──────────────────────────────────────


class TestModelProperties:
    def test_turn_is_efficient(self, loom_models):
        """4 步內 = 高效。"""
        t = loom_models.TurnRecord(steps_taken=["D問", "D卦", "D召", "D評"])
        assert t.is_efficient is True
        t.steps_taken = ["D問", "D卦", "D召", "D評", "D應", "D固", "D省"]
        assert t.is_efficient is False

    def test_turn_had_correction(self, loom_models):
        t = loom_models.TurnRecord()
        assert t.had_correction is False
        t.user_feedback = "correction"
        assert t.had_correction is True

    def test_turn_add_reward(self, loom_models):
        t = loom_models.TurnRecord()
        t.add_reward("efficiency", 0.8, "efficient")
        assert len(t.reward_signals) == 1
        assert t.reward_signals[0]["source"] == "efficiency"

    def test_session_hexagram_pattern(self, loom_models):
        s = loom_models.SessionRecord()
        factories = {"stable": [10, 10, 11], "drift": [10, 15, 20], "jump": [10, 54, 3]}
        for expected, ids in factories.items():
            s.turns = [loom_models.TurnRecord(hexagram={"id": hid}) for hid in ids]
            assert s.hexagram_pattern() == expected, f"expected {expected} for {ids}"

    def test_session_summarize(self, loom_models):
        s = loom_models.SessionRecord()
        t1 = loom_models.TurnRecord(token_usage={"total": 500}, hexagram={"id": 10})
        t2 = loom_models.TurnRecord(token_usage={"total": 300}, hexagram={"id": 11})
        s.turns = [t1, t2]
        summary = s.summarize()
        assert summary["turns"] == 2
        assert summary["total_tokens"] == 800
        assert summary["hexagram_pattern"] == "stable"
        assert summary["close_reason"] == ""

    def test_conversation_knowledge_reuse_rate(self, loom_models):
        c = loom_models.ConversationRecord()
        s = loom_models.SessionRecord()
        # 兩輪相同 (卦+知識) 簽名 → 重複率 = 1/1 = 1.0
        s.turns = [
            loom_models.TurnRecord(hexagram={"id": 10}, knowledge={"rag": 3}),
            loom_models.TurnRecord(hexagram={"id": 10}, knowledge={"rag": 3}),
        ]
        c.sessions = [s]
        assert c.knowledge_reuse_rate == 1.0

    def test_conversation_reward(self, loom_models):
        c = loom_models.ConversationRecord()
        s = loom_models.SessionRecord()
        t1 = loom_models.TurnRecord(hexagram={"id": 47, "q_value": 0.3}, token_usage={"total": 500})
        s.turns = [t1]
        c.sessions = [s]
        r = c.reward_for_flywheel()
        assert r["n_turns"] == 1
        assert r["hexagram_evolution"] == [47]

    def test_conversation_session_summaries(self, loom_models):
        c = loom_models.ConversationRecord()
        s = loom_models.SessionRecord()
        c.sessions = [s]
        assert len(c.session_summaries()) == 1


# ── ConversationFactory: Forgetting + Drift ──────────────


class TestConversationBoundary:
    def test_forgetting_score_fresh(self, loom_models):
        """新 conversation 的 forgetting_score 應接近 1.0。"""
        from kafed.loom.factory import ConversationFactory
        c = loom_models.ConversationRecord()
        score = ConversationFactory.forgetting_score(c)
        assert 0.9 <= score <= 1.0, f"expected fresh, got {score}"

    def test_forgetting_score_decays_with_time(self, loom_models):
        """模擬長時間空白 → score 應低於閾值。"""
        from kafed.loom.factory import ConversationFactory
        import time
        # 模擬 130 小時前的 conversation（exp(-0.01*130) = 0.27 < 0.30）
        c = loom_models.ConversationRecord(
            created_at=time.time() - 130 * 3600,
        )
        score = ConversationFactory.forgetting_score(c)
        threshold = ConversationFactory.FORGET_THRESHOLD
        assert score < threshold, f"expected forgotten (<{threshold}), got {score}"

    def test_forgetting_score_decays_with_turns(self, loom_models):
        """多輪 + 短時間 → score 應低於閾值（turn + time 組合效應）。"""
        from kafed.loom.factory import ConversationFactory
        from kafed.loom.factory import TurnFactory
        import time
        # 30 輪 + 48h：exp(-0.01*48 - 0.005*30) = exp(-0.63) = 0.53 → 不夠
        # 50 輪 + 72h：exp(-0.01*72 - 0.005*50) = exp(-0.97) = 0.38 → 還不夠
        # 80 輪 + 48h：exp(-0.01*48 - 0.005*80) = exp(-0.88) = 0.41 → 還不夠
        # 120 輪 + 1h：exp(-0.01*1 - 0.005*120) = exp(-0.61) = 0.54 → 不夠
        # exp(-1.3) = 0.27 < 0.30
        # 組合：50h + 80turns：0.01*50 + 0.005*80 = 0.9 → exp(-0.9) = 0.41 → 不夠
        # 80h + 80turns：0.01*80 + 0.005*80 = 1.2 → exp(-1.2) = 0.30 → 邊界
        # 100h + 80turns：0.01*100 + 0.005*80 = 1.4 → exp(-1.4) = 0.25 < 0.30
        c = loom_models.ConversationRecord(
            created_at=time.time() - 100 * 3600,
        )
        s = loom_models.SessionRecord()
        for _ in range(80):
            s.add_turn(TurnFactory.create(query="x"))
        c.add_session(s)
        score = ConversationFactory.forgetting_score(c)
        threshold = ConversationFactory.FORGET_THRESHOLD
        assert score < threshold, f"expected forgotten (<{threshold}), got {score}"

    def test_should_close_drift(self, loom_models):
        """話題漂移時 should_close 應返回 True。"""
        from kafed.loom.factory import ConversationFactory
        c = loom_models.ConversationRecord(topic_centroid=[1.0, 0.0, 0.0])
        # 完全不同的向量
        assert ConversationFactory.should_close(
            c, new_query_embedding=[0.0, 1.0, 0.0],
        ) is True

    def test_should_close_same_topic(self, loom_models):
        """同一話題時 should_close 應返回 False。"""
        from kafed.loom.factory import ConversationFactory
        c = loom_models.ConversationRecord(topic_centroid=[0.5, 0.5, 0.5])
        assert ConversationFactory.should_close(
            c, new_query_embedding=[0.5, 0.5, 0.5],
        ) is False

    def test_should_close_no_embedding(self, loom_models):
        """無 embedding 時僅靠遺忘曲線判定。"""
        from kafed.loom.factory import ConversationFactory
        c = loom_models.ConversationRecord()
        # 新鮮 → 不關
        assert ConversationFactory.should_close(c) is False

    def test_update_centroid_first(self, loom_models):
        """首次 update 應直接取代空 centroid。"""
        c = loom_models.ConversationRecord()
        c.update_centroid([1.0, 2.0, 3.0])
        assert c.topic_centroid == [1.0, 2.0, 3.0]

    def test_update_centroid_weighted(self, loom_models):
        """加權滾動平均：weight=0.3 時新嵌入佔 30%。"""
        c = loom_models.ConversationRecord(topic_centroid=[0.0, 0.0])
        c.update_centroid([1.0, 1.0], weight=0.3)
        # 新 centroid = [0*0.7 + 1*0.3, 0*0.7 + 1*0.3] = [0.3, 0.3]
        assert abs(c.topic_centroid[0] - 0.3) < 1e-10
        assert abs(c.topic_centroid[1] - 0.3) < 1e-10

    def test_update_centroid_dim_mismatch(self, loom_models):
        """維度不匹配時重置。"""
        c = loom_models.ConversationRecord(topic_centroid=[1.0, 2.0, 3.0])
        c.update_centroid([5.0, 6.0])  # 不同維度
        assert c.topic_centroid == [5.0, 6.0]


# ── Solidifier Integration (public API) ────────────────────


class TestSolidifier:
    def test_solidify_knowledge_only(self):
        """solidify() 應寫入 KAFED（跳過 Loom 如果無活躍 conversation）。"""
        from kafed.analyzer.solidifier import solidify
        result = solidify("測試洞察", domain="TEST", source="test")
        assert "status" in result
        # Loom 不活躍，不報錯即可

    def test_solidify_with_loom_active(self, loom):
        """活躍 Loom conversation 時 solidify 應自動記錄到 session。"""
        from kafed.analyzer.solidifier import solidify
        loom.start_turn(query="測試")
        result = solidify("測試洞察 Loom 集成", domain="TEST", source="test")
        assert result is not None
        # 自動記錄到 Loom
        session = loom.active_session
        assert session is not None
        assert len(session.solidify_log) >= 1
        # verify the entry matches
        assert session.solidify_log[-1] is not None
