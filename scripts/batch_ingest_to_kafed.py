#!/usr/bin/env python3
"""
batch_ingest_to_kafed.py — 將目錄下的 .md 文件批量攝入 KAFED ChromaDB。

用法:
  cd ~/KAFED && .venv/bin/python3 scripts/batch_ingest_to_kafed.py <md_dir> [--batch N] [--domain-override DOMAIN]

流程:
  1. 掃描目錄下所有 .md 文件
  2. 用 chunker 分塊 + quality 過濾
  3. classify 分配 domain
  4. 批量嵌入 + 寫入 VectorStore
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure KAFED is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kafed.knowledge.rag.chunker import chunk_document
from kafed.knowledge.rag.vector_store import VectorStore
from kafed.knowledge.classify.classify import classify


def main():
    parser = argparse.ArgumentParser(description="Batch ingest markdown dirs into KAFED")
    parser.add_argument("md_dir", help="Directory containing .md files")
    parser.add_argument("--batch", type=int, default=100, help="Chroma batch size")
    parser.add_argument("--domain-override", help="Force all files to this domain")
    args = parser.parse_args()

    md_dir = Path(args.md_dir)
    if not md_dir.is_dir():
        print(f"ERROR: {md_dir} is not a directory")
        sys.exit(1)

    md_files = sorted(md_dir.glob("*.md"))
    if not md_files:
        md_files = sorted(md_dir.glob("*.MD"))
    if not md_files:
        md_files = sorted(md_dir.rglob("*.md"))

    print(f"Found {len(md_files)} .md files in {md_dir}")

    if len(md_files) == 0:
        print("Nothing to ingest.")
        return

    # Init KAFED
    print("Initializing VectorStore...")
    vs = VectorStore()
    before = vs.count()
    print(f"  KAFED before: {before} chunks")

    # Process files
    total_chunks = 0
    total_files = 0
    errors = 0
    t0 = time.time()
    batch_texts: list[str] = []
    batch_metadatas: list[dict] = []

    for i, md_path in enumerate(md_files):
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"  [{i+1}/{len(md_files)}] SKIP {md_path.name}: {e}")
            errors += 1
            continue

        if len(text.strip()) < 50:
            continue  # too short

        # Determine domain
        if args.domain_override:
            domain = args.domain_override
        else:
            try:
                domain_result = classify(text[:2000])
                domain = domain_result.get("domain", "GENERAL")
            except Exception:
                domain = "GENERAL"

        # Chunk
        try:
            chunks = chunk_document(text, domain=domain)
        except Exception as e:
            print(f"  [{i+1}/{len(md_files)}] CHUNK FAIL {md_path.name}: {e}")
            errors += 1
            continue

        if not chunks:
            continue

        # Build batch
        for ck in chunks:
            batch_texts.append(ck["content"])
            batch_metadatas.append({
                "domain": ck["domain"] or domain,
                "source": md_path.name,
                "heading": ck.get("heading") or "",
                "chars": ck.get("chars", len(ck["content"])),
                "quality_score": ck.get("quality_score", 1.0),
                "chunk_index": ck.get("chunk_index", 0),
            })

        total_chunks += len(chunks)
        total_files += 1

        # Batch write
        if len(batch_texts) >= args.batch:
            try:
                vs.add(batch_texts, batch_metadatas)
                print(f"  [{i+1}/{len(md_files)}] +{len(batch_texts)} chunks ({md_path.name}...)")
            except Exception as e:
                print(f"  [{i+1}/{len(md_files)}] WRITE FAIL: {e}")
                errors += 1
            batch_texts = []
            batch_metadatas = []

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(md_files) - i - 1) / rate if rate > 0 else 0
            print(f"  Progress: {i+1}/{len(md_files)} files, {total_chunks} chunks, "
                  f"{elapsed:.0f}s elapsed, ~{eta:.0f}s remaining")

    # Final batch
    if batch_texts:
        try:
            vs.add(batch_texts, batch_metadatas)
            print(f"  Final: +{len(batch_texts)} chunks")
        except Exception as e:
            print(f"  Final WRITE FAIL: {e}")
            errors += 1

    after = vs.count()
    elapsed = time.time() - t0

    print(f"\n{'='*50}")
    print(f"Done.")
    print(f"  Files processed: {total_files}/{len(md_files)}")
    print(f"  Chunks added:    {total_chunks}")
    print(f"  Errors:          {errors}")
    print(f"  KAFED before:    {before} → after: {after}")
    print(f"  Time:            {elapsed:.0f}s ({total_chunks/max(1,elapsed):.1f} chunks/s)")


if __name__ == "__main__":
    main()
