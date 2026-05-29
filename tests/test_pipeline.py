"""Tests for LOOM v3.0 — recommend + solidify + find_partners bridge."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestRecommend:
    """recommend() 四步強制：問 → 卦 → 召 → 評。"""

    def test_basic_recommend(self):
        from loom.director.recommend import recommend

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
        from loom.director.recommend import recommend

        rec = recommend("測試")
        text = rec.inject()
        assert "5W1H" in text or "知識召回" in text or "難度" in text

    def test_5w1h_extraction(self):
        from loom.director.recommend import _step_5w1h

        w5 = _step_5w1h("如何修復 LOOM 的 Pipeline bug？")
        assert w5.what  # "修復" + "操作指南"
        assert "LOOM" in w5.where

        w5_empty = _step_5w1h("hello")
        assert w5_empty.is_empty() or not w5_empty.what


class TestSolidify:
    """solidify() 將洞察寫入 KM。"""

    def test_solidify_loom_target(self):
        from loom.analyzer.solidifier import solidify

        result = solidify("test insight for loom",
                          domain="TEST", source="pytest")
        assert result["target"] == "loom"
        assert result["status"] in ("ok", "error")

    def test_ingest_memory_target(self):
        from loom.knowledge.ingest import ingest

        result = ingest("test insight", target="memory")
        assert result["status"] == "ok"
        assert result["target"] == "memory"

    def test_session_end_audit(self):
        from loom.analyzer.solidifier import session_end_audit

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
        from loom.finder.router import Router

        router = Router()
        assert router is not None


class TestTools:
    """Hermes 工具層可 import。"""

    def test_tools_importable(self):
        from loom.tools.hermes_tools import (
            loom_recommend, loom_find_partners, loom_solidify,
            loom_query, loom_status,
        )
        assert callable(loom_recommend)
        assert callable(loom_find_partners)
        assert callable(loom_solidify)
        assert callable(loom_query)
        assert callable(loom_status)


class TestScheduler:
    """Task 排程與補償。"""

    def test_task_registry(self):
        from datetime import timedelta
        from loom.scheduler.registry import TaskRegistry, SimpleTask

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
        from loom.scheduler.registry import SimpleTask

        task = SimpleTask(id="due_test", interval=timedelta(seconds=1))
        assert task.is_due  # 從未執行 → 立即到期

    def test_runner_tick(self):
        from datetime import timedelta
        from loom.scheduler.registry import TaskRegistry, SimpleTask
        from loom.scheduler.runner import TaskRunner

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
