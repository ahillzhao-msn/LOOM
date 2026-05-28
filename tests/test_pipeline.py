"""Tests for KAFED v3.0 — recommend + solidify + find_partners bridge."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestRecommend:
    """recommend() 四步強制：問 → 卦 → 召 → 評。"""

    def test_basic_recommend(self):
        from kafed.director.recommend import recommend

        rec = recommend("SAP PM 工單分析")
        assert rec.user_input == "SAP PM 工單分析"
        # 5W1H
        assert rec.five_w_one_h.what or rec.five_w_one_h.where
        # 卦（可能為未占——YiCeNet 未安裝時 fallback）
        assert "id" in rec.hexagram
        # 知識
        assert isinstance(rec.knowledge_items, list)
        # EVAL
        assert rec.eval_score is not None
        assert 1 <= rec.eval_score.tier <= 3

    def test_recommend_inject(self):
        from kafed.director.recommend import recommend

        rec = recommend("測試")
        text = rec.inject()
        assert "5W1H" in text or "知識召回" in text or "難度" in text

    def test_5w1h_extraction(self):
        from kafed.director.recommend import _step_5w1h

        w5 = _step_5w1h("如何修復 KAFED 的 Pipeline bug？")
        assert w5.what  # "修復" + "操作指南"
        assert "KAFED" in w5.where

        w5_empty = _step_5w1h("hello")
        assert w5_empty.is_empty() or not w5_empty.what


class TestSolidify:
    """solidify() 將洞察寫入 KM。"""

    def test_solidify_kafed_target(self):
        from kafed.analyzer.solidifier import solidify

        result = solidify("test insight for kafed",
                          domain="TEST", source="pytest")
        assert result["target"] == "kafed"
        assert result["status"] in ("ok", "error")

    def test_ingest_memory_target(self):
        from kafed.knowledge.ingest import ingest

        result = ingest("test insight", target="memory")
        assert result["status"] == "ok"
        assert result["target"] == "memory"

    def test_session_end_audit(self):
        from kafed.analyzer.solidifier import session_end_audit

        result = session_end_audit(
            director_intent="test",
            pipeline_taken="recommend",
            steps=[{"step": "问", "result": "test"}],
        )
        assert "quality_score" in result
        assert "actions" in result


class TestFinder:
    """find_partners() 三向量聚合。"""

    def test_find_partners_module(self):
        from kafed.finder.router import Router

        router = Router()
        assert router is not None


class TestTools:
    """Hermes 工具層可 import。"""

    def test_tools_importable(self):
        from kafed.tools.hermes_tools import (
            kafed_recommend, kafed_find_partners, kafed_solidify,
            kafed_query, kafed_status,
        )
        assert callable(kafed_recommend)
        assert callable(kafed_find_partners)
        assert callable(kafed_solidify)
        assert callable(kafed_query)
        assert callable(kafed_status)


class TestScheduler:
    """Task 排程與補償。"""

    def test_task_registry(self):
        from datetime import timedelta
        from kafed.scheduler.registry import TaskRegistry, SimpleTask

        reg = TaskRegistry()

        def _dummy():
            return "ok"

        task = SimpleTask(id="test_task", interval=timedelta(hours=1), fn=_dummy)
        reg.register(task)
        assert reg.get("test_task") is task
        assert len(reg) == 1
        reg.unregister("test_task")
        assert len(reg) == 0

    def test_task_is_due(self):
        from datetime import timedelta
        from kafed.scheduler.registry import SimpleTask

        task = SimpleTask(id="due_test", interval=timedelta(seconds=1))
        assert task.is_due  # 從未執行 → 立即到期

    def test_runner_tick(self):
        from datetime import timedelta
        from kafed.scheduler.registry import TaskRegistry, SimpleTask
        from kafed.scheduler.runner import TaskRunner

        reg = TaskRegistry()
        results_log = []

        def _record():
            results_log.append("ran")
            return "ok"

        task = SimpleTask(id="tick_test", interval=timedelta(hours=1), fn=_record)
        reg.register(task)
        runner = TaskRunner(reg)
        results = runner.tick()
        assert len(results) >= 1
