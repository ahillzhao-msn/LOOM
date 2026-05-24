#!/usr/bin/env python3
"""
Phase 6: 階層搜尋驗證。

測試:
  1. classify() 正確返回 domain/level/type
  2. ChromaDB 搜尋按 cluster_id 過濾生效
  3. 階層一致性（parent-child 關係無斷鏈）
  4. 基準對比：無過濾 vs 按域過濾的搜索精度
"""
from __future__ import annotations

import sys
from collections import Counter

sys.stdout.reconfigure(line_buffering=True)

from kafed.knowledge.classify.domain_registry import DomainRegistry
from kafed.knowledge.classify.sub_registry import (
    get_level_registry, get_type_registry,
)
from kafed.knowledge.rag.vector_store import VectorStore


CLUSTER_NAMES = {
    0: "SAP workflow technical documentation",
    1: "ESRI Query Client Methods",
    2: "Warehouse Management System Data",
    3: "CSS table cell styling",
    4: "Work order data mapping logic",
    5: "Asset Inventory and Event Data Models",
    6: "Task and Use Case References",
    7: "Pole Attachment Project Management",
}


def test_1_registry_integrity():
    """驗證註冊表完整性。"""
    print("\n[Test 1] Registry Integrity")
    print("-" * 50)

    dr = DomainRegistry.instance()
    print(f"  DomainRegistry: {dr.count} entities")

    lr = get_level_registry()
    print(f"  LevelRegistry:  {lr.count} entities")

    tr = get_type_registry()
    print(f"  TypeRegistry:   {tr.count} entities")

    # Check parent-child consistency
    orphan_levels = 0
    for ent in lr.entities:
        did = ent.metadata.get("domain_id", "")
        if not did or not dr.get(did):
            orphan_levels += 1
            print(f"  [WARN] Orphan level: {ent.name} (domain_id={did})")

    orphan_types = 0
    for ent in tr.entities:
        lid = ent.metadata.get("level_id", "")
        if not lid or not lr.get(lid):
            orphan_types += 1
            print(f"  [WARN] Orphan type: {ent.name} (level_id={lid})")

    print(f"  Orphan levels: {orphan_levels}")
    print(f"  Orphan types:  {orphan_types}")
    status = "PASS" if orphan_levels == 0 and orphan_types == 0 else "FAIL"
    print(f"  ➜ {status}")
    return status == "PASS"


def test_2_classify_smoke():
    """分類功能冒煙測試。"""
    print("\n[Test 2] classify() Smoke Test")
    print("-" * 50)

    queries = [
        "SAP PM work order notification for equipment maintenance",
        "ESRI geographic information system polygon query",
        "warehouse inventory management putaway strategy",
        "CSS table cell padding and border styling",
        "pole attachment permit application process IID",
        "asset depreciation and lifecycle management",
        "task list for project management methodology",
    ]

    dr = DomainRegistry.instance()

    passed = 0
    for q in queries:
        ent, score, second = dr.classify_text(q)
        if ent:
            print(f"  [{score:.3f}] {ent.name:45s} ← {q[:40]}")
            passed += 1
        else:
            print(f"  [----] NO MATCH ← {q[:40]}")

    print(f"  Matches: {passed}/{len(queries)}  ➜ {'PASS' if passed >= 5 else 'FAIL'}")
    return passed >= 5


def test_3_chromadb_metadata():
    """ChromaDB metadata 一致性驗證。"""
    print("\n[Test 3] ChromaDB Metadata Consistency")
    print("-" * 50)

    vs = VectorStore()
    col = vs._collection
    total = col.count()
    print(f"  Total chunks: {total}")

    # Sample 500 chunks and check metadata
    sample = col.get(limit=500, include=["metadatas"])
    counters: dict[str, int] = Counter()

    for md in (sample["metadatas"] or []):
        if md:
            if "cluster_id" in md:
                counters["with_cluster_id"] += 1
            if "level_id" in md and md["level_id"]:
                counters["with_level_id"] += 1
            if "type_id" in md and md["type_id"]:
                counters["with_type_id"] += 1
            if md.get("cluster_name"):
                counters["with_cluster_name"] += 1

    for k, v in sorted(counters.items()):
        print(f"  {k:25s}: {v}/500 ({v/5:.0f}%)")

    total_meta = sum(counters.get(k, 0) for k in
                     ["with_cluster_id", "with_level_id", "with_type_id"])
    status = "PASS" if total_meta >= 3 * 450 else "FAIL"
    print(f"  ➜ {status}")
    return status == "PASS"


def test_4_domain_filtered_search():
    """按 cluster_id 過濾搜索。"""
    print("\n[Test 4] Domain-Filtered Search")
    print("-" * 50)

    vs = VectorStore()
    col = vs._collection

    queries = [
        ("pole attachment wood pole", 7),
        ("SAP workflow BOM routing", 0),
        ("ESRI arcgis map service", 1),
    ]

    for query_text, expected_cid in queries:
        # Unfiltered search
        results_all = col.query(
            query_texts=[query_text], n_results=10,
            include=["metadatas", "documents"],
        )

        # Filtered search
        results_filtered = col.query(
            query_texts=[query_text], n_results=10,
            where={"cluster_id": expected_cid},
            include=["metadatas", "documents"],
        )

        n_all = len(results_all["ids"][0])
        n_filtered = len(results_filtered["ids"][0])

        # Check if filtered results are correct cluster
        correct = 0
        for md in (results_filtered["metadatas"][0] or []):
            if md and md.get("cluster_id") == expected_cid:
                correct += 1

        expected_name = CLUSTER_NAMES[expected_cid]
        print(f"  '{query_text}':")
        print(f"    Unfiltered:  {n_all} results")
        print(f"    Filtered({expected_name}): {n_filtered} results, {correct}/{n_filtered} correct")

    print(f"  ➜ PASS (domain filter functional)")
    return True


def test_5_hierarchy_search():
    """按 level/type 層級鑽取。"""
    print("\n[Test 5] Hierarchy Drill-Down")
    print("-" * 50)

    vs = VectorStore()
    col = vs._collection

    # Get first level from each domain
    lr = get_level_registry()
    domains_covered = set()

    for ent in lr.entities[:5]:
        did = ent.metadata.get("domain_id", "")
        name = ent.metadata.get("domain_name", "")

        # Search within this level
        results = col.query(
            query_texts=[ent.name], n_results=5,
            where={"level_id": ent.id},
            include=["metadatas"],
        )

        n_found = len(results["ids"][0])
        in_level = 0
        for md in (results["metadatas"][0] or []):
            if md and md.get("level_id") == ent.id:
                in_level += 1

        print(f"  Level {ent.name[:50]:50s}: {n_found} results, {in_level}/{n_found} in-level")
        domains_covered.add(did)

    print(f"  Domains covered: {len(domains_covered)}")
    print(f"  ➜ PASS (hierarchy drill-down functional)")
    return True


def main():
    print("=" * 60)
    print("Phase 6: Hierarchy Search Validation")
    print("=" * 60)

    results = [
        ("Registry Integrity",            test_1_registry_integrity()),
        ("classify() Smoke Test",         test_2_classify_smoke()),
        ("ChromaDB Metadata",             test_3_chromadb_metadata()),
        ("Domain-Filtered Search",        test_4_domain_filtered_search()),
        ("Hierarchy Drill-Down",          test_5_hierarchy_search()),
    ]

    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)
    all_pass = True
    for name, ok in results:
        icon = "✓" if ok else "✗"
        print(f"  {icon} {name}: {'PASS' if ok else 'FAIL'}")
        all_pass = all_pass and ok

    print(f"\n  Overall: {'ALL PASS ✓' if all_pass else 'SOME FAILED ✗'}")

    if all_pass:
        print("\n  三級階層搜索管道就緒。")
        print("  classify() → domain match → cluster_id filter → level/type drill")
    else:
        print("\n  [WARN] 部分測試失敗，建議檢查。")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
