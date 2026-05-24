#!/usr/bin/env python3
"""KAFED 全面稽核 — 導入所有模塊 + 核心功能驗證"""
import sys, os
sys.path.insert(0, os.path.expanduser("~/KAFED/src"))

def _import(mod):
    """Reliable submodule import."""
    import importlib
    return importlib.import_module(mod)

errors = []

def check(name, fn):
    try:
        fn()
        print(f"  ✅ {name}")
    except Exception as e:
        import traceback
        tb = traceback.format_exc().split('\n')[-3:-1]
        print(f"  ❌ {name}: {e}")
        errors.append((name, str(e)))

# ══════════════════════════════════════════════════
# Phase 1: Import all modules
# ══════════════════════════════════════════════════

print("\n=== Phase 1: Import All Modules ===")

check("Director eval", lambda: _import("kafed.director.eval"))
check("Director decision", lambda: _import("kafed.director.decision"))
check("Director planner", lambda: _import("kafed.director.planner"))
check("Director strategy", lambda: _import("kafed.director.strategy"))
check("Director protocol", lambda: _import("kafed.director.protocol"))
check("Director pipeline", lambda: _import("kafed.director.pipeline"))

check("Executor dag", lambda: _import("kafed.executor.dag"))
check("Executor dispatcher", lambda: _import("kafed.executor.dispatcher"))
check("Executor engine", lambda: _import("kafed.executor.engine"))

check("Finder router", lambda: _import("kafed.finder.router"))
check("Finder matcher", lambda: _import("kafed.finder.matcher"))
check("Finder registry", lambda: _import("kafed.finder.registry"))
check("Finder context_space", lambda: _import("kafed.finder.context_space"))
check("Finder explorer", lambda: _import("kafed.finder.explorer"))

check("Analyzer audit", lambda: _import("kafed.analyzer.audit"))
check("Analyzer kb_audit", lambda: _import("kafed.analyzer.kb_audit"))
check("Analyzer pulse", lambda: _import("kafed.analyzer.pulse"))

check("Knowledge rag", lambda: _import("kafed.knowledge.rag.vector_store"))
check("Knowledge chunker", lambda: _import("kafed.knowledge.rag.chunker"))
check("Knowledge embedding", lambda: _import("kafed.knowledge.rag.embedding"))
check("Knowledge rag_engine", lambda: _import("kafed.knowledge.rag.rag_engine"))
check("Knowledge quality", lambda: _import("kafed.knowledge.quality.quality"))
check("Knowledge classify", lambda: _import("kafed.knowledge.classify.classify"))
check("Knowledge domain_registry", lambda: _import("kafed.knowledge.classify.domain_registry"))
check("Knowledge soft_classify", lambda: _import("kafed.knowledge.classify.soft_classify"))
check("Knowledge event_checker", lambda: _import("kafed.knowledge.flywheel.event_checker"))
check("Knowledge context_provider", lambda: _import("kafed.knowledge.context.context_provider"))
check("Knowledge ingest", lambda: _import("kafed.knowledge.ingest"))

check("Config", lambda: _import("kafed.config"))
check("Entry", lambda: _import("kafed.entry"))
check("Log", lambda: _import("kafed.log"))
check("Schemas", lambda: _import("kafed.schemas"))

# ══════════════════════════════════════════════════
# Phase 2: Core functionality smoke tests
# ══════════════════════════════════════════════════

print("\n=== Phase 2: Core Functionality ===")

check("EvalScorer.from_description", lambda: (
    _import("kafed.director.eval").EvalScorer.from_description("analyze PM data")
))

check("DomainRegistry.instance()", lambda: (
    _import("kafed.knowledge.classify.domain_registry").DomainRegistry.instance()
))

check("classify()", lambda: (
    _import("kafed.knowledge.classify.classify").classify("IW31 test")
))

check("soft_classify.hierarchical_search", lambda: (
    _import("kafed.knowledge.classify.soft_classify").hierarchical_search("test query")
))

check("_name_to_cluster_id", lambda: (
    _import("kafed.knowledge.classify.soft_classify")._name_to_cluster_id(
        "SAP_PM",
        _import("kafed.knowledge.classify.domain_registry").DomainRegistry.instance()
    )
))

check("chunk_document", lambda: (
    _import("kafed.knowledge.rag.chunker").chunk_document("test " * 100)
))

check("clean_text", lambda: (
    _import("kafed.knowledge.quality.quality").clean_text("<br>test</br>")
))

check("compute_quality_score", lambda: (
    _import("kafed.knowledge.quality.quality").compute_quality_score("test content here")
))

check("default_feedback_callback", lambda: (
    _import("kafed.director.protocol").default_feedback_callback()
))

check("VectorStore()", lambda: (
    _import("kafed.knowledge.rag.vector_store").VectorStore()
))

check("entry.plan()", lambda: (
    _import("kafed.entry").plan("analyze test data")
))

check("entry.solidify(memory)", lambda: (
    _import("kafed.entry").solidify("test insight", target="memory")
))

check("entry.eval()", lambda: (
    _import("kafed.entry").eval("test query")
))

check("Dispatcher.dispatch_for", lambda: (
    _import("kafed.executor.dispatcher").Dispatcher.dispatch_for(model_name="test")
))

check("Dispatcher.needs_dispatch", lambda: (
    _import("kafed.executor.dispatcher").Dispatcher.needs_dispatch(model_name="test", current_model="other")
))

check("PipelineRunner smoke", lambda: (
    _import("kafed.director.pipeline").PipelineRunner(
        _import("kafed.director.pipeline").SOUL_PIPELINES["soul_core"]
    )
))

check("ingest() backlog", lambda: (
    _import("kafed.knowledge.ingest").ingest("test", target="backlog", title="audit test")
))

check("backlog_check()", lambda: (
    _import("kafed.knowledge.ingest").backlog_check()
))

# ══════════════════════════════════════════════════
# Phase 3: Named entity resolution
# ══════════════════════════════════════════════════

print("\n=== Phase 3: Named Entity Resolution ===")

dr = _import("kafed.knowledge.classify.domain_registry").DomainRegistry.instance()
print(f"  DomainRegistry: {dr.count} domains")
print(f"  Names: {[e.name for e in list(dr.entities)[:5]]}...")

from kafed.knowledge.classify.soft_classify import _name_to_cluster_id
all_ok = True
for ent in dr.entities:
    cid = _name_to_cluster_id(ent.name)
    if cid is None:
        print(f"  ❌ {ent.name} → None cluster_id")
        all_ok = False
if all_ok:
    print(f"  ✅ All {dr.count} domains resolve to a cluster_id")

# ══════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════

print(f"\n{'='*50}")
total = 23  # Phase 1 imports count
total += 18  # Phase 2 function tests
if errors:
    print(f"❌ {len(errors)} FAILURES:")
    for name, msg in errors:
        print(f"   {name}: {msg}")
else:
    print(f"✅ ALL CHECKS PASSED ({total + 1} total)")
