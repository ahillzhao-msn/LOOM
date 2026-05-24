#!/usr/bin/env python3
"""
Level/Type 域名美化 — LLM 命名。

為每個 Level (32) 和 Type (98) 採樣文本 → LLM 命名 → 更新 Registry。

用法:
  cd ~/KAFED && source .venv/bin/activate
  python3 scripts/name_subclusters.py [--dry-run] [--level-only]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

import numpy as np

sys.stdout.reconfigure(line_buffering=True)

from kafed.knowledge.rag.vector_store import VectorStore
from kafed.knowledge.classify.sub_registry import (
    get_level_registry, get_type_registry,
)
from kafed.knowledge.classify.embedding_space import name_to_uuid

LLAMA_API = "http://localhost:8000/v1/chat/completions"
LLAMA_MODEL = "leader"
LLAMA_KEY = "hermes-local"

LEVEL_PROMPT = """You are analyzing a sub-cluster (Level) within a larger knowledge domain. Each Level represents a distinct subtopic or depth-layer within the domain.

Domain: {domain_name}

Below are representative text samples from this Level. They share a common sub-theme. Suggest a concise label (2-4 words) that captures what this sub-cluster is about.

Guidelines:
- Be specific to the sub-topic, not a repeat of the domain name
- Use general terminology
- If it's clearly about a specific concept (e.g., 'Notification Types', 'Permit Fees', 'Query Filters'), name it directly

Samples:
{samples}

Suggested label (2-4 words, no explanation):"""

TYPE_PROMPT = """You are analyzing a sub-sub-cluster (Type) within a Level. Each Type represents a specific category or variant within that Level.

Level: {level_name} (in Domain: {domain_name})

Below are representative text samples. They share a very specific theme. Suggest a concise label (1-3 words).

Samples:
{samples}

Suggested label (1-3 words, no explanation):"""


def _call_llm(prompt: str, max_tokens: int = 20,
              temperature: float = 0.3) -> str:
    payload = json.dumps({
        "model": LLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                LLAMA_API, data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {LLAMA_KEY}",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                name = data["choices"][0]["message"]["content"].strip()
                name = name.strip('"\'"\' """').strip()
                name = name.replace("Label: ", "").replace("label: ", "").strip()
                if name:
                    return name[:60]
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"    [WARN] LLM failed: {e}")
    return ""


def _sample_texts(collection, entity, is_type: bool = False,
                  n_samples: int = 5) -> list[str]:
    """Sample texts from ChromaDB for a given level/type entity."""
    where_key = "type_id" if is_type else "level_id"
    where = {where_key: entity.id}

    results = collection.query(
        query_texts=[entity.name[:200]], n_results=n_samples,
        where=where,
        include=["documents"],
    )
    docs = results["documents"][0] if results["documents"] else []
    return [d[:300] for d in docs if d][:n_samples]


def main():
    parser = argparse.ArgumentParser(description="Name sub-clusters")
    parser.add_argument("--dry-run", action="store_true", help="審核不改")
    parser.add_argument("--level-only", action="store_true", help="只命名 Level")
    parser.add_argument("--type-only", action="store_true", help="只命名 Type")
    args = parser.parse_args()

    print("=" * 60)
    print("Level/Type Domain Name Assignment (LLM)")
    print("=" * 60)

    vs = VectorStore()
    collection = vs._collection
    lr = get_level_registry()
    tr = get_type_registry()

    level_entities = lr.entities
    type_entities = tr.entities if not args.level_only else []

    if args.type_only:
        level_entities = []

    print(f"\nLevels to name: {len(level_entities)}")
    print(f"Types to name:  {len(type_entities)}")

    if args.dry_run:
        print("\nLevels:")
        for ent in sorted(level_entities, key=lambda e: e.name):
            print(f"  {ent.name}")
        print(f"\nTypes ({len(type_entities)} total):")
        for ent in sorted(type_entities, key=lambda e: e.name):
            print(f"  {ent.name}")
        return

    # Name Levels
    named_levels = 0
    for ent in sorted(level_entities, key=lambda e: e.name):
        dom_name = ent.metadata.get("domain_name", "")
        samples = _sample_texts(collection, ent, is_type=False)
        if not samples:
            print(f"  [SKIP] {ent.name} (no samples)")
            continue

        formatted = "\n".join(f"- {s}" for s in samples)
        prompt = LEVEL_PROMPT.format(domain_name=dom_name, samples=formatted)
        new_name = _call_llm(prompt)

        if new_name:
            full_name = f"{dom_name} — {new_name}"
            old_name = ent.name
            ent.name = full_name
            if old_name not in ent.aliases:
                ent.aliases.append(old_name)
            lr._dirty = True
            named_levels += 1
            print(f"  [{named_levels}] {old_name:55s} → {full_name}")
        else:
            print(f"  [SKIP] {ent.name} (LLM returned empty)")

        time.sleep(0.3)

    lr._save()
    print(f"\n  Levels named: {named_levels}/{len(level_entities)}")

    # Name Types
    named_types = 0
    for ent in sorted(type_entities, key=lambda e: e.name):
        level_name = ent.metadata.get("level_name", "")
        # Get domain from parent
        lid = ent.metadata.get("level_id", "")
        parent_level = lr.get(lid)
        domain_name = parent_level.metadata.get("domain_name", "") if parent_level else ""

        samples = _sample_texts(collection, ent, is_type=True)
        if not samples:
            print(f"  [SKIP] {ent.name} (no samples)")
            continue

        formatted = "\n".join(f"- {s}" for s in samples)
        prompt = TYPE_PROMPT.format(
            level_name=level_name, domain_name=domain_name, samples=formatted,
        )
        new_name = _call_llm(prompt)

        if new_name:
            full_name = f"{level_name} — {new_name}"
            old_name = ent.name
            ent.name = full_name
            if old_name not in ent.aliases:
                ent.aliases.append(old_name)
            tr._dirty = True
            named_types += 1
            print(f"  [{named_types}] {old_name[:55]} → {new_name}")
        else:
            print(f"  [SKIP] {ent.name} (LLM returned empty)")

        if named_types % 10 == 0:
            tr._save()
        time.sleep(0.3)

    tr._save()
    print(f"\n  Types named: {named_types}/{len(type_entities)}")

    # Final save
    lr._save()
    tr._save()

    print(f"\n✅ Complete")
    print(f"  LevelRegistry: {lr.count} entities ({named_levels} named)")
    print(f"  TypeRegistry:  {tr.count} entities ({named_types} named)")


if __name__ == "__main__":
    main()
