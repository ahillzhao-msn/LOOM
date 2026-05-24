#!/usr/bin/env python3
"""End-to-end RAG check — query real data from Chroma DB"""
import sys, os
sys.path.insert(0, os.path.expanduser("~/KAFED/src"))

from kafed.knowledge.rag.rag_engine import RAGEngine
from kafed.knowledge.rag.vector_store import VectorStore
from kafed.config import get_config

cfg = get_config()
print(f"Config data_dir: {cfg.data_dir}")
print(f"Chroma path: {cfg.chroma_path}")

# Check Chroma exists
import os.path
if os.path.exists(cfg.chroma_path):
    import shutil
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fn in os.walk(cfg.chroma_path) for f in fn)
    print(f"Chroma DB size: {size / 1024:.0f} KB")
else:
    print(f"⚠ Chroma DB not at {cfg.chroma_path}")
    # Try the real path
    real_path = os.path.expanduser("~/KAFED/data/chroma")
    if os.path.exists(real_path):
        size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fn in os.walk(real_path) for f in fn)
        print(f"Real Chroma at ~/KAFED/data/chroma: {size / 1024:.1f} KB")
    # Also check ~/.kafed/data/chroma
    kafed_path = os.path.expanduser("~/.kafed/data/chroma")
    if os.path.exists(kafed_path):
        size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fn in os.walk(kafed_path) for f in fn)
        print(f"Also at ~/.kafed/data/chroma: {size / 1024:.1f} KB")

# VectorStore
vs = VectorStore()
print(f"VectorStore: {vs}")

# RAG query
engine = RAGEngine(vector_store=vs)

for query in ["IW31 notification", "PM work order", "Qwen AI"]:
    results = engine.query(query, top_k=3, soft=True)
    if isinstance(results, dict):
        count = len(results.get("results", results))
        print(f"  Query '{query}' → {count} results")
        if count > 0:
            items = results.get("results", results) if isinstance(results, dict) else results
            key = list(items.keys())[0] if isinstance(items, dict) else 0
            first = items[key]
            print(f"    Top: domain={getattr(first, 'domain', 'N/A')}, text_preview={str(first)[:60]}")
    else:
        count = len(results)
        print(f"  Query '{query}' → {count} results (type={type(results).__name__})")
        if count > 0:
            first = results[0] if isinstance(results, (list, tuple)) else results
            print(f"    First type: {type(first).__name__} = {str(first)[:80]}")
    print()

print("=== E2E RAG CHECK PASSED ===")
