"""
KAFED Hermes Tool — in-process RAG query, ingest, classify, pipeline runner.

All tool functions are always importable. Hermes registry registration is
conditional (requires Hermes tool discovery chain). This means you can:

  python3 -c "from kafed.client.kafed_tool import kafed_pipeline_start; print(kafed_pipeline_start())"

without needing the Hermes agent in sys.path.
"""

from __future__ import annotations

import json
from typing import Optional

# ── Pipeline state (module-level, shared across tool calls in same process) ──
_PIPELINE_RUNNER: Optional[object] = None


def _safe_result(data, error_prefix="KAFED error"):
    """Wrap result in JSON, catching serialization errors."""
    try:
        if isinstance(data, dict) and "error" in data:
            return json.dumps(data)
        return json.dumps(data, default=str, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"{error_prefix}: {e}"})


# ── Helper: Hermes registry (optional) ──
try:
    from tools.registry import registry as _REGISTRY
except ModuleNotFoundError:
    _REGISTRY = None


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline Runner — unconditional (always importable)
# ═══════════════════════════════════════════════════════════════════════════

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
        pipeline_name: soul_core (default, 9 steps), soul_quick (6 steps), soul_deep (9 steps)
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


# ═══════════════════════════════════════════════════════════════════════════
# Knowledge tools — unconditional (always importable)
# ═══════════════════════════════════════════════════════════════════════════

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

        collection = vs._collection
        count = collection.count()

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


# ═══════════════════════════════════════════════════════════════════════════
# FlowVisualizer — KAFED 公交站牌式信息流可視化
# ═══════════════════════════════════════════════════════════════════════════

def kafed_flow(title: str = "KAFED Flow", mode: str = "compact",
               stations: str = "[]", end: str = "done") -> str:
    """Render a KAFED flow visualization.

    Args:
        title: Flow title
        mode: 'compact' (arrow chain) or 'detailed' (bus-route tree)
        stations: JSON list of [module_code, action, description] tuples
        end: End marker text
    Returns:
        Empty string (output goes to stderr)
    """
    try:
        from kafed.client.flow import chain, hop, stop, divider
        sts = json.loads(stations) if isinstance(stations, str) else stations
        if mode == "detailed":
            divider(title)
            station_tuples = [(s[0], s[1], s[2] if len(s) > 2 else "") for s in sts]
            chain(title, station_tuples, end=end)
        else:
            parts = []
            for s in sts:
                m, a = s[0], s[1]
                d = s[2] if len(s) > 2 else ""
                parts.append(f"{m}{a}({d})" if d else f"{m}{a}")
            import sys
            text = f"[ {title} ]  {' -> '.join(parts)} -> {end}"
            print(text, file=sys.stderr)
        return ""
    except Exception as e:
        return _safe_result({"error": str(e)})


def kafed_flow_chain(steps: str, title: str = "Flow", end: str = "done") -> str:
    """Quick compact flow chain from a JSON list of step dicts.

    Args:
        steps: JSON list of {"m": module, "a": action, "d": description}
        title: Flow title
        end: End marker
    """
    try:
        parsed = json.loads(steps) if isinstance(steps, str) else steps
        sts = [[s["m"], s["a"], s.get("d", "")] for s in parsed]
        return kafed_flow(title=title, mode="compact", stations=json.dumps(sts), end=end)
    except Exception as e:
        return _safe_result({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════════════
# Hermes tool registration (conditional — requires registry)
# ═══════════════════════════════════════════════════════════════════════════

if _REGISTRY is not None:

    def _check_kafed():
        try:
            import kafed  # noqa: F401
            return True
        except ImportError:
            return False

    # ── Knowledge tools ──
    _REGISTRY.register(
        name="kafed_query",
        toolset="kafed",
        schema={
            "name": "kafed_query",
            "description": "Search KAFED knowledge base via RAG. Returns ranked chunks with domain classification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query text"},
                    "domain": {"type": "string", "description": "Optional domain filter", "default": ""},
                    "k": {"type": "integer", "description": "Number of results (1-20)", "default": 5, "minimum": 1, "maximum": 20},
                    "soft": {"type": "boolean", "description": "Enable soft classification", "default": True},
                },
                "required": ["query"],
            },
        },
        handler=lambda args, **kw: kafed_query(
            query=args.get("query", ""), domain=args.get("domain", ""),
            k=args.get("k", 5), soft=args.get("soft", True),
        ),
        check_fn=_check_kafed, requires_env=[],
    )

    _REGISTRY.register(
        name="kafed_ingest",
        toolset="kafed",
        schema={
            "name": "kafed_ingest",
            "description": "Ingest text content into KAFED knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text content to ingest"},
                    "domain": {"type": "string", "description": "Target domain", "default": "GENERAL"},
                    "source": {"type": "string", "description": "Source identifier", "default": "hermes_tool"},
                },
                "required": ["text"],
            },
        },
        handler=lambda args, **kw: kafed_ingest(
            text=args.get("text", ""), domain=args.get("domain", "GENERAL"),
            source=args.get("source", "hermes_tool"),
        ),
        check_fn=_check_kafed, requires_env=[],
    )

    _REGISTRY.register(
        name="kafed_status",
        toolset="kafed",
        schema={
            "name": "kafed_status",
            "description": "KAFED system status: chunk count, domain distribution, engine health.",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=lambda args, **kw: kafed_status(),
        check_fn=_check_kafed, requires_env=[],
    )

    _REGISTRY.register(
        name="kafed_classify",
        toolset="kafed",
        schema={
            "name": "kafed_classify",
            "description": "Classify text into a KAFED domain.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text to classify"}},
                "required": ["text"],
            },
        },
        handler=lambda args, **kw: kafed_classify(text=args.get("text", "")),
        check_fn=_check_kafed, requires_env=[],
    )

    # ── Pipeline tools ──
    _REGISTRY.register(
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
                        "default": "soul_core",
                    }
                },
            },
        },
        handler=lambda args, **kw: kafed_pipeline_start(
            pipeline_name=args.get("pipeline_name", "soul_core"),
        ),
        check_fn=_check_kafed, requires_env=[],
    )

    _REGISTRY.register(
        name="kafed_pipeline_complete",
        toolset="kafed",
        schema={
            "name": "kafed_pipeline_complete",
            "description": "Complete the current pipeline step and advance to the next.",
            "parameters": {
                "type": "object",
                "properties": {
                    "result": {"type": "string", "description": "Summary of what was done"},
                    "note": {"type": "string", "description": "Optional note for flow header"},
                },
            },
        },
        handler=lambda args, **kw: kafed_pipeline_complete(
            result=args.get("result", ""), note=args.get("note", ""),
        ),
        check_fn=_check_kafed, requires_env=[],
    )

    _REGISTRY.register(
        name="kafed_pipeline_skip",
        toolset="kafed",
        schema={
            "name": "kafed_pipeline_skip",
            "description": "Skip the current optional step and advance.",
            "parameters": {
                "type": "object",
                "properties": {"note": {"type": "string", "description": "Reason for skipping"}},
            },
        },
        handler=lambda args, **kw: kafed_pipeline_skip(note=args.get("note", "")),
        check_fn=_check_kafed, requires_env=[],
    )

    _REGISTRY.register(
        name="kafed_pipeline_status",
        toolset="kafed",
        schema={
            "name": "kafed_pipeline_status",
            "description": "Get current pipeline status and flow report.",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=lambda args, **kw: kafed_pipeline_status(),
        check_fn=_check_kafed, requires_env=[],
    )

    # ── FlowVisualizer tools ──
    _REGISTRY.register(
        name="kafed_flow",
        toolset="kafed",
        schema={
            "name": "kafed_flow",
            "description": "Render KAFED flow visualization (bus-route style, stderr output).",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Flow title", "default": "KAFED Flow"},
                    "mode": {"type": "string", "description": "compact (arrow chain) or detailed (bus-route tree)", "default": "compact"},
                    "stations": {"type": "string", "description": "JSON list of [module_code, action, description]"},
                    "end": {"type": "string", "description": "End marker text", "default": "done"},
                },
            },
        },
        handler=lambda args, **kw: kafed_flow(
            title=args.get("title", "KAFED Flow"),
            mode=args.get("mode", "compact"),
            stations=args.get("stations", "[]"),
            end=args.get("end", "done"),
        ),
        check_fn=_check_kafed, requires_env=[],
    )
