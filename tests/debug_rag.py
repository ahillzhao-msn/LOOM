#!/usr/bin/env python3
"""Debug RAG result structure"""
import sys, os
sys.path.insert(0, os.path.expanduser("~/KAFED/src"))

from kafed.knowledge.rag.vector_store import VectorStore
from kafed.knowledge.rag.rag_engine import RAGEngine

vs = VectorStore()
engine = RAGEngine(vector_store=vs)

# Check raw result structure
results = engine.query("IW31 notification", top_k=1, soft=True)
print(f"Return type: {type(results).__name__}")
if isinstance(results, dict):
    for k, v in results.items():
        print(f"  Key '{k}': type={type(v).__name__}, len={len(v) if hasattr(v, '__len__') else 'N/A'}")
        if isinstance(v, (list, tuple)) and len(v) > 0:
            item = v[0]
            print(f"  First item type: {type(item).__name__}")
            if isinstance(item, dict):
                for ik, iv in item.items():
                    print(f"    {ik}: {str(iv)[:80]}")
        elif isinstance(v, dict) and v:
            item = v[list(v.keys())[0]]
            print(f"  Dict first val type: {type(item).__name__}")
            if isinstance(item, dict):
                for ik, iv in item.items():
                    print(f"    {ik}: {str(iv)[:80]}")

# Check metadata in Chroma directly
print("\n--- Raw Chroma query ---")
raw = vs._collection.get(limit=5)
print(f"Keys in raw results: {list(raw.keys())}")
print(f"Metadatas sample: {str(raw['metadatas'][0]) if raw['metadatas'] else 'N/A'}")
print(f"Number of docs: {len(raw['ids'])}")
print(f"Chroma count: {vs._collection.count()}")

# Check domain in metadata
sample = vs._collection.get(limit=50)
domains = set(m.get('domain', 'MISSING') for m in sample['metadatas'] if m)
print(f"Domains in first 50 docs: {domains}")
