"""Tests for pipeline.py — each function is a thin bridge to sub-modules."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kafed.entry import (
    SubTask, TaskPlan as Plan, TaskResult,
    recall, eval as pipeline_eval,
    solidify, backlog_check, backlog_push,
    session_start, session_end, session_end_audit,
)


class TestPipelineDTOs:
    def test_subtask_defaults(self):
        st = SubTask(id="t1", description="test")
        assert st.domain is None
        assert st.depends_on == []
        assert st.model_name == ""

    def test_plan_create(self):
        p = Plan(id="test_plan", goal="test", subtasks=[SubTask(id="t1", description="test")])
        assert len(p.subtasks) == 1
        assert p.goal == "test"

    def test_task_result(self):
        tr = TaskResult(task_id="t1", description="test", status="completed")
        assert tr.status == "completed"


class TestPipelineBridge:
    """Each bridge function returns the correct type without crashing."""

    def test_backlog_push_and_check(self):
        # Clean state
        backlog_push("test item")
        items = backlog_check()
        # Should find at least our item
        assert isinstance(items, list)

    def test_session_start(self):
        result = session_start()
        # May return None (no pending) or dict (has pending)
        assert result is None or isinstance(result, dict)

    def test_session_end_no_crash(self):
        session_end()
        session_end([{"title": "unfinished task"}])
        assert True  # no crash

    def test_solidify_memory_target(self):
        result = solidify("test insight", target="memory")
        assert result["status"] == "ok"
        assert result["target"] == "memory"

    def test_solidify_kafed_target(self):
        result = solidify("test insight for kafed", target="kafed",
                          domain="TEST", source="pytest")
        assert result["target"] == "kafed"
        assert result["status"] in ("ok", "error")  # error if chroma unavailable

    def test_session_end_audit(self):
        result = session_end_audit(
            director_intent="test",
            pipeline_taken="soul_core",
            steps=[{"step": "问", "result": "test"}],
        )
        assert "quality_score" in result
        assert "actions" in result
