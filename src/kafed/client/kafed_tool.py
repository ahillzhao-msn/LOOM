"""
KAFED Hermes Tool — in-process RAG query, ingest, classify.

Deployment: editable package in Hermes env (pip install -e ~/KAFED).

Usage from Hermes session:
  > kafed_query(query="PM notification process", k=5)
  → {"results": [...], "total": 5, "domain": "SAP_PM"}

  > kafed_ingest(text="...", domain="SAP_PM")
  → {"chunks": 12, "domain": "SAP_PM"}

  > kafed_status()
  → {"chunks": 93115, "domains": 38, "engine": "ready"}
"""

from __future__ import annotations

import json


# Hermes tools discovery
try:
    from tools.registry import registry
except ModuleNotFoundError:
    registry = None


def _safe_result(data, error_prefix="KAFED error"):
    """Wrap result in JSON, catching serialization errors."""
    try:
        if isinstance(data, dict) and "error" in data:
            return json.dumps(data)
        return json.dumps(data, default=str, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"{error_prefix}: {e}"})


# ── Tool functions ──────────────────────────


def kafed_query(query: str, domain: str = "", k: int = 5,
                soft: bool = True) -> str:
    """Query KAFED knowledge base via RAG.

    Args:
        query: Search query text
        domain: Optional domain filter (e.g. "SAP_PM"). Empty = auto-detect
        k: Number of results to return (1-20)
        soft: Enable soft classification for boundary queries
    """
    try:
        from kafed.knowledge.rag.vector_store import VectorStore
        from kafed.knowledge.rag.rag_engine import RAGEngine

        vs = VectorStore()
        engine = RAGEngine(vs)
        results = engine.query(
            question=query,
            top_k=min(max(k, 1), 20),
            domain=domain if domain else None,
            soft=soft,
        )
        return _safe_result(results)
    except Exception as e:
        return _safe_result({"error": str(e)})


def kafed_ingest(text: str, domain: str = "GENERAL",
                 source: str = "hermes_tool") -> str:
    """Ingest text into KAFED knowledge base.

    Args:
        text: Text content to ingest
        domain: Target domain (e.g. "SAP_PM", "CSP_IID")
        source: Source identifier for provenance
    """
    try:
        from kafed.knowledge.ingest import ingest

        result = ingest(text=text, domain=domain, source=source)
        return _safe_result(result)
    except Exception as e:
        return _safe_result({"error": str(e)})


def kafed_status() -> str:
    """KAFED system status: chunk count, domains, engine health."""
    try:
        from kafed.knowledge.rag.vector_store import VectorStore
        from kafed.config import get_config

        cfg = get_config()
        vs = VectorStore()

        # Access Chroma collection for stats
        collection = vs._collection
        count = collection.count()

        # Domain distribution
        results = collection.get(include=["metadatas"])
        domains = {}
        for meta in results.get("metadatas", []):
            d = meta.get("domain", "UNKNOWN") if meta else "UNKNOWN"
            domains[d] = domains.get(d, 0) + 1

        return _safe_result({
            "chunks": count,
            "domains": len(domains),
            "domain_distribution": domains,
            "chroma_path": str(cfg.chroma_path),
            "engine": "ready",
        })
    except Exception as e:
        return _safe_result({
            "chunks": 0,
            "domains": 0,
            "engine": "error",
            "error": str(e),
        })


def kafed_classify(text: str) -> str:
    """Classify text into KAFED domain.

    Args:
        text: Text to classify
    """
    try:
        from kafed.knowledge.classify.classify import classify

        result = classify(text)
        return _safe_result(result)
    except Exception as e:
        return _safe_result({"error": str(e)})


# ── Hermes tool registration ────────────────

if registry is not None:

    def _check_kafed():
        """Check if KAFED is importable."""
        try:
            import kafed  # noqa: F401
            return True
        except ImportError:
            return False

    # ── Existing tools: query / ingest / status / classify ──

    registry.register(
        name="kafed_query",
        toolset="kafed",
        schema={
            "name": "kafed_query",
            "description": "Search KAFED knowledge base via RAG. Returns ranked chunks with domain classification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query text"
                    },
                    "domain": {
                        "type": "string",
                        "description": "Optional domain filter (e.g. SAP_PM). Empty = auto-detect",
                        "default": ""
                    },
                    "k": {
                        "type": "integer",
                        "description": "Number of results (1-20)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20
                    },
                    "soft": {
                        "type": "boolean",
                        "description": "Enable soft classification for boundary queries",
                        "default": True
                    }
                },
                "required": ["query"]
            }
        },
        handler=lambda args, **kw: kafed_query(
            query=args.get("query", ""),
            domain=args.get("domain", ""),
            k=args.get("k", 5),
            soft=args.get("soft", True),
        ),
        check_fn=_check_kafed,
        requires_env=[],
    )

    registry.register(
        name="kafed_ingest",
        toolset="kafed",
        schema={
            "name": "kafed_ingest",
            "description": "Ingest text content into KAFED knowledge base. Chunks, embeds, and stores.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text content to ingest"
                    },
                    "domain": {
                        "type": "string",
                        "description": "Target domain (e.g. SAP_PM)",
                        "default": "GENERAL"
                    },
                    "source": {
                        "type": "string",
                        "description": "Source identifier",
                        "default": "hermes_tool"
                    }
                },
                "required": ["text"]
            }
        },
        handler=lambda args, **kw: kafed_ingest(
            text=args.get("text", ""),
            domain=args.get("domain", "GENERAL"),
            source=args.get("source", "hermes_tool"),
        ),
        check_fn=_check_kafed,
        requires_env=[],
    )

    registry.register(
        name="kafed_status",
        toolset="kafed",
        schema={
            "name": "kafed_status",
            "description": "KAFED system status: chunk count, domain distribution, engine health.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        },
        handler=lambda args, **kw: kafed_status(),
        check_fn=_check_kafed,
        requires_env=[],
    )

    registry.register(
        name="kafed_classify",
        toolset="kafed",
        schema={
            "name": "kafed_classify",
            "description": "Classify text into a KAFED domain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to classify"
                    }
                },
                "required": ["text"]
            }
        },
        handler=lambda args, **kw: kafed_classify(
            text=args.get("text", ""),
        ),
        check_fn=_check_kafed,
        requires_env=[],
    )

    # ── Pipeline tools ────────────────────────

    # Module-level state: 同一 turn 內跨 tool call 共享
    _PIPELINE_RUNNER = None

    def _pipeline_step_response(step, runner, done_ids, total):
        """Build response dict for a pipeline step."""
        if step is None:
            return json.dumps({
                "done": True,
                "report": runner.report(),
                "completed": done_ids,
                "total_steps": total,
            })
        return json.dumps({
            "done": False,
            "step_id": step.step_id,
            "name": step.name,
            "optional": step.optional,
            "depends_on": step.depends_on,
            "completed": done_ids,
            "total_steps": total,
            "report": runner.report(),
        })

    def _count_done(runner):
        return sum(1 for r in runner._records.values()
                   if r.status.name in ("DONE", "SKIPPED"))

    def kafed_pipeline_start(pipeline_name: str = "soul_core") -> str:
        """Start a new pipeline run. Resets any previous state.

        Args:
            pipeline_name: Which pipeline to run: soul_core (default), soul_quick, or soul_deep
        """
        global _PIPELINE_RUNNER
        try:
            from kafed.director.pipeline import SOUL_PIPELINES, PipelineRunner
            pipe = SOUL_PIPELINES.get(pipeline_name)
            if not pipe:
                return json.dumps(
                    {"error": f"Unknown pipeline: {pipeline_name}. Choose: {list(SOUL_PIPELINES.keys())}"}
                )
            _PIPELINE_RUNNER = PipelineRunner(pipe)
            step = _PIPELINE_RUNNER.next_step()
            if step is None:
                return json.dumps({"error": "Pipeline has no steps"})
            return _pipeline_step_response(
                step, _PIPELINE_RUNNER, _count_done(_PIPELINE_RUNNER), len(pipe.steps)
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

    def kafed_pipeline_complete(result: str = "", note: str = "") -> str:
        """Complete current pipeline step and advance to next.

        Args:
            result: Summary of what was done in this step
            note: Optional note for flow header (defaults to result text)
        """
        global _PIPELINE_RUNNER
        if _PIPELINE_RUNNER is None:
            return json.dumps({"error": "No pipeline started. Call kafed_pipeline_start first."})
        if _PIPELINE_RUNNER._current_step_id is None:
            return json.dumps({"error": "No current step to complete."})
        step_id = _PIPELINE_RUNNER._current_step_id
        try:
            _PIPELINE_RUNNER.complete(step_id, result={"action": result}, note=note or result)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        step = _PIPELINE_RUNNER.next_step()
        return _pipeline_step_response(
            step, _PIPELINE_RUNNER, _count_done(_PIPELINE_RUNNER), len(_PIPELINE_RUNNER.pipeline.steps)
        )

    def kafed_pipeline_skip(note: str = "") -> str:
        """Skip current optional step and advance. Only works on optional steps."""
        global _PIPELINE_RUNNER
        if _PIPELINE_RUNNER is None:
            return json.dumps({"error": "No pipeline started."})
        if _PIPELINE_RUNNER._current_step_id is None:
            return json.dumps({"error": "No current step to skip."})
        step_id = _PIPELINE_RUNNER._current_step_id
        try:
            _PIPELINE_RUNNER.skip(step_id, note=note)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        step = _PIPELINE_RUNNER.next_step()
        return _pipeline_step_response(
            step, _PIPELINE_RUNNER, _count_done(_PIPELINE_RUNNER), len(_PIPELINE_RUNNER.pipeline.steps)
        )

    def kafed_pipeline_status() -> str:
        """Return current pipeline status and flow report."""
        global _PIPELINE_RUNNER
        if _PIPELINE_RUNNER is None:
            return json.dumps({"pipeline": None, "status": "inactive"})
        return json.dumps({
            "pipeline": _PIPELINE_RUNNER.pipeline.id,
            "current_step": _PIPELINE_RUNNER._current_step_id,
            "report": _PIPELINE_RUNNER.report(),
            "done": _PIPELINE_RUNNER.done(),
            "core_done": _PIPELINE_RUNNER.core_done(),
        })

    # ── Register pipeline tools ───────────────

    registry.register(
        name="kafed_pipeline_start",
        toolset="kafed",
        schema={
            "name": "kafed_pipeline_start",
            "description": "Start a KAFED Pipeline run for this turn. Returns the first step.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pipeline_name": {
                        "type": "string",
                        "description": "soul_core (default, 9 steps), soul_quick (6 steps), soul_deep (9 steps)",
                        "default": "soul_core"
                    }
                }
            }
        },
        handler=lambda args, **kw: kafed_pipeline_start(
            pipeline_name=args.get("pipeline_name", "soul_core"),
        ),
        check_fn=_check_kafed,
        requires_env=[],
    )

    registry.register(
        name="kafed_pipeline_complete",
        toolset="kafed",
        schema={
            "name": "kafed_pipeline_complete",
            "description": "Complete the current pipeline step and advance to the next. Returns next step info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "string",
                        "description": "Summary of what was done in this step"
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional note for flow header"
                    }
                }
            }
        },
        handler=lambda args, **kw: kafed_pipeline_complete(
            result=args.get("result", ""),
            note=args.get("note", ""),
        ),
        check_fn=_check_kafed,
        requires_env=[],
    )

    registry.register(
        name="kafed_pipeline_skip",
        toolset="kafed",
        schema={
            "name": "kafed_pipeline_skip",
            "description": "Skip the current optional step and advance. Only works on optional steps (e.g. 編).",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {
                        "type": "string",
                        "description": "Reason for skipping"
                    }
                }
            }
        },
        handler=lambda args, **kw: kafed_pipeline_skip(
            note=args.get("note", ""),
        ),
        check_fn=_check_kafed,
        requires_env=[],
    )

    registry.register(
        name="kafed_pipeline_status",
        toolset="kafed",
        schema={
            "name": "kafed_pipeline_status",
            "description": "Get current pipeline status and flow report.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        },
        handler=lambda args, **kw: kafed_pipeline_status(),
        check_fn=_check_kafed,
        requires_env=[],
    )
