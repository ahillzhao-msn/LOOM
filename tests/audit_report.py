#!/usr/bin/env python3
"""KAFED 全面稽核報告 — 匯總"""
import sys, os
sys.path.insert(0, os.path.expanduser("~/KAFED/src"))

# 1. 文件結構
src_root = os.path.expanduser("~/KAFED/src/kafed")
print("=== KAFED 文件結構 ===")
for root, dirs, files in os.walk(src_root):
    py_files = [f for f in files if f.endswith('.py')]
    if py_files:
        rel = os.path.relpath(root, src_root)
        print(f"  {rel}/ ({len(py_files)} files)")
        for f in sorted(py_files):
            fpath = os.path.join(root, f)
            lines = sum(1 for _ in open(fpath))
            print(f"    {f:40s} {lines:>5} lines")

# 2. 代碼統計
total_py = 0
total_lines = 0
for root, dirs, files in os.walk(src_root):
    for f in files:
        if f.endswith('.py'):
            total_py += 1
            fpath = os.path.join(root, f)
            total_lines += sum(1 for _ in open(fpath))

print(f"\n=== 統計 ===")
print(f"  Python 文件: {total_py}")
print(f"  總行數:     {total_lines}")

# 3. Chroma DB
from kafed.config import get_config
cfg = get_config()
chroma_path = cfg.chroma_path
if os.path.exists(chroma_path):
    import shutil
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fn in os.walk(chroma_path) for f in fn)
    from kafed.knowledge.rag.vector_store import VectorStore
    vs = VectorStore()
    count = vs._collection.count()
    print(f"\n=== Chroma DB ===")
    print(f"  路徑: {chroma_path}")
    print(f"  大小: {size/1024/1024:.0f} MB")
    print(f"  Chunks: {count:,}")
else:
    print(f"\n⚠ Chroma DB at {chroma_path} not found")

# 4. 5層模塊統計
layers = ['director', 'executor', 'finder', 'analyzer', 'knowledge']
print(f"\n=== 五層模塊 ===")
for layer in layers:
    path = os.path.join(src_root, layer)
    if os.path.isdir(path):
        files = [f for f in os.listdir(path) if f.endswith('.py') and not f.startswith('__')]
        loc = sum(sum(1 for _ in open(os.path.join(path, f))) for f in files)
        print(f"  {layer:15s} {len(files):2d} modules, {loc:>6} lines")
    else:
        print(f"  {layer:15s} ❌ NOT FOUND")

# 5. Version
print(f"\n=== Version ===")
for line in open(os.path.expanduser("~/KAFED/pyproject.toml")):
    if 'version' in line:
        print(f"  {line.strip()}")
        break
